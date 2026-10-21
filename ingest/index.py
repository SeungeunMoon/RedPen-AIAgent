"""청킹 결과를 검증하고 OpenAI 임베딩을 pgvector에 적재한다."""

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import psycopg
import tiktoken
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_postgres import PGEngine, PGVectorStore

from app.ai.embeddings import EMBEDDING_DIMENSIONS, EMBEDDING_MAX_TOKENS, get_embeddings
from app.core.config import Settings
from app.core.environment import load_runtime_environment
from ingest.chunk import ChunkingConfig, SearchChunk


def load_documents(input_dir: Path) -> tuple[list[Document], str]:
    """외부 호출 전에 manifest·파일 해시·개수·ID·문자 범위를 검사한다."""
    manifest_bytes = (input_dir / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest['status'] != 'chunked' or manifest['schema_version'] != 1:
        raise ValueError('청킹 완료된 v1 manifest가 필요합니다')
    ChunkingConfig.model_validate(manifest['config'])
    documents = []
    seen = set()
    for record in manifest['documents']:
        path = (input_dir / record['file']).resolve()
        if not path.is_relative_to(input_dir.resolve()):
            raise ValueError('청크 파일 경로가 입력 폴더 밖입니다')
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != record['sha256']:
            raise ValueError('청크 파일 해시 불일치')
        chunks = [SearchChunk.model_validate_json(line) for line in content.splitlines()]
        if len(chunks) != record['chunks']:
            raise ValueError('manifest와 청크 개수 불일치')
        for chunk in chunks:
            if chunk.regulation.chunk_id in seen:
                raise ValueError('중복 청크 ID')
            seen.add(chunk.regulation.chunk_id)
            if chunk.start_char < 0 or chunk.end_char - chunk.start_char != len(chunk.regulation.text):
                raise ValueError('청크 문자 범위 불일치')
            document = chunk.to_document()
            # 추후 검색 결과를 내부 계약으로 복원할 수 있도록 원문 모델도 저장한다.
            document.metadata['regulation'] = chunk.regulation.model_dump(mode='json')
            documents.append(document)
    if not documents:
        raise ValueError('적재할 청크가 없습니다')
    return documents, hashlib.sha256(manifest_bytes).hexdigest()


def embedding_spec(settings: Settings) -> dict:
    return {
        'provider': 'openai', 'model': settings.embedding_model,
        'base_url': settings.embedding_base_url, 'dimensions': EMBEDDING_DIMENSIONS,
        'document_format': 'context-and-original-v1',
    }


def prepare_documents(documents: list[Document], settings: Settings, corpus_hash: str) -> tuple[str, list[Document], int]:
    spec = embedding_spec(settings)
    digest = hashlib.sha256(json.dumps(
        {'corpus': corpus_hash, 'embedding': spec}, sort_keys=True,
    ).encode()).hexdigest()
    table_name = f'regulations_{digest[:24]}'
    encoding = tiktoken.encoding_for_model(settings.embedding_model)
    maximum = 0
    prepared = []
    for document in documents:
        tokens = len(encoding.encode(document.page_content, disallowed_special=()))
        if tokens > EMBEDDING_MAX_TOKENS:
            raise ValueError(f'임베딩 입력 토큰 초과: {document.id}; 청크 크기를 줄이세요')
        maximum = max(maximum, tokens)
        prepared.append(Document(
            id=str(uuid5(NAMESPACE_URL, f'{table_name}:{document.id}')),
            page_content=document.page_content,
            metadata={**document.metadata, 'corpus_hash': corpus_hash, 'embedding_spec': spec},
        ))
    return table_name, prepared, maximum


def write_documents(store, documents: list[Document], batch_size: int = 32) -> dict:
    """공식 upsert API를 사용한다. 이미 일치하는 행은 임베딩 호출을 생략한다."""
    if batch_size < 1:
        raise ValueError('batch_size는 양수여야 합니다')
    inserted = skipped = 0
    for start in range(0, len(documents), batch_size):
        batch = documents[start:start + batch_size]
        existing = {str(doc.id): doc for doc in store.get_by_ids([doc.id for doc in batch])}
        pending = []
        for document in batch:
            stored = existing.get(document.id)
            if stored is None:
                pending.append(document)
            elif stored.page_content != document.page_content or stored.metadata != document.metadata:
                raise ValueError('동일 ID의 DB 내용이 입력과 다릅니다')
            else:
                skipped += 1
        if pending:
            store.add_documents(pending, ids=[doc.id for doc in pending])
            inserted += len(pending)
    # 라이브러리는 행별 commit을 수행하므로 최종 개수·내용까지 재검증한다.
    for start in range(0, len(documents), batch_size):
        batch = documents[start:start + batch_size]
        actual = {str(doc.id): doc for doc in store.get_by_ids([doc.id for doc in batch])}
        for document in batch:
            stored = actual.get(document.id)
            if stored is None or stored.page_content != document.page_content or stored.metadata != document.metadata:
                raise ValueError('적재 후 DB 검증 실패')
    return {'inserted': inserted, 'skipped': skipped, 'verified': len(documents)}


def open_store(settings: Settings, table_name: str, embeddings: Embeddings):
    """데이터/모델별 전용 테이블. 기존 테이블이나 데이터를 삭제하지 않는다."""
    connection = settings.pgvector_connection.get_secret_value()
    if not connection.startswith('postgresql+psycopg://'):
        raise ValueError('PGVECTOR_CONNECTION은 postgresql+psycopg:// 형식이어야 합니다')
    engine = PGEngine.from_connection_string(url=connection, connect_args={'connect_timeout': 5})
    try:
        with psycopg.connect(connection.replace('postgresql+psycopg://', 'postgresql://', 1), connect_timeout=5) as conn:
            exists = conn.execute('SELECT to_regclass(%s)', (f'public.{table_name}',)).fetchone()[0]
        if exists is None:
            engine.init_vectorstore_table(table_name=table_name, vector_size=EMBEDDING_DIMENSIONS)
        store = PGVectorStore.create_sync(engine=engine, table_name=table_name, embedding_service=embeddings)
        return engine, store
    except Exception:
        asyncio.run(engine.close())
        raise


def index_snapshot(input_dir: Path, output: Path, settings: Settings, *, dry_run: bool = False) -> dict:
    documents, corpus_hash = load_documents(input_dir)
    table_name, documents, maximum = prepare_documents(documents, settings, corpus_hash)
    summary = {
        'schema_version': 1, 'status': 'validated', 'table_name': table_name,
        'chunk_snapshot': input_dir.name, 'corpus_hash': corpus_hash,
        'embedding': embedding_spec(settings), 'documents': len(documents),
        'max_input_tokens': maximum, 'supplementary_indexed': False,
    }
    if dry_run:
        return summary
    embeddings = get_embeddings(settings=settings)
    # 완료 보고서는 모든 행 검증 뒤에만 기록한다. 실패한 테이블은 재실행으로 복구한다.
    output.parent.mkdir(parents=True, exist_ok=True)
    def save(status: str):
        summary['status'] = status
        summary['updated_at'] = datetime.now(timezone.utc).isoformat()
        temporary = output.with_suffix(output.suffix + '.tmp')
        temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(output)
    save('indexing')
    engine = None
    try:
        engine, store = open_store(settings, table_name, embeddings)
        summary.update(write_documents(store, documents))
        save('indexed')
    except Exception as error:
        summary['error_type'] = type(error).__name__
        # API 응답 원문 대신 진단에 필요한 알려진 오류 코드만 남긴다.
        code = getattr(error, 'code', None)
        if code in {'insufficient_quota', 'rate_limit_exceeded', 'invalid_api_key'}:
            summary['error_code'] = code
        status_code = getattr(error, 'status_code', None)
        if isinstance(status_code, int):
            summary['error_status_code'] = status_code
        save('failed')
        raise
    finally:
        if engine is not None:
            asyncio.run(engine.close())
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--dry-run', action='store_true', help='파일·토큰만 검사. API/DB 호출 없음')
    args = parser.parse_args()
    load_runtime_environment()
    output = args.output or args.input / 'index-report.json'
    try:
        summary = index_snapshot(args.input, output, Settings(), dry_run=args.dry_run)
    except Exception as error:
        # SDK·DB 예외 문자열에는 접속 정보가 포함될 수 있어 기본 CLI에 출력하지 않는다.
        parser.exit(1, f'적재 실패 ({type(error).__name__}). 환경 설정과 index-report.json의 상태를 확인하세요.\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
