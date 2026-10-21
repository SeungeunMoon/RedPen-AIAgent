"""임베딩/LLM 호출 없이 로컬 청크와 실제 pgvector 적재 상태를 대조한다."""

import argparse
import json
import re
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.core.config import Settings
from app.core.environment import load_runtime_environment
from app.kb.vectorstore import embedding_spec
from ingest.index import load_documents, prepare_documents


def inspect_rows(documents, rows, dimensions: int) -> dict:
    """DB 행과 기대 문서 비교. 벡터 자체를 결과 JSON에 출력하지 않는다."""
    expected = {document.id:document for document in documents}
    actual = {str(row['langchain_id']):row for row in rows}
    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    wrong_dimensions = []
    missing_vectors = []
    mismatches = []
    for identifier, row in actual.items():
        if row['dimensions'] is None:
            missing_vectors.append(identifier)
        elif row['dimensions'] != dimensions:
            wrong_dimensions.append(identifier)
        document = expected.get(identifier)
        if document and (row['content'] != document.page_content or row['langchain_metadata'] != document.metadata):
            mismatches.append(identifier)
    problems = {'missing_ids':missing,'unexpected_ids':unexpected,
                'missing_vectors':missing_vectors,'wrong_dimensions':wrong_dimensions,
                'content_or_metadata_mismatch':mismatches}
    return {'status':'ready' if not any(problems.values()) else 'invalid',
            'expected_chunks':len(expected),'stored_chunks':len(rows),
            'expected_dimensions':dimensions,**problems}


def check_status(settings: Settings, report_path: Path, input_dir: Path | None = None) -> dict:
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if report.get('status') != 'indexed' or not report.get('documents') or report.get('verified') != report['documents']:
        raise ValueError('완료 검증된 적재 보고서가 필요합니다')
    if report.get('embedding') != embedding_spec(settings):
        raise ValueError('현재 임베딩 설정과 적재 보고서가 다릅니다')
    if len(report.get('snapshot_dates', [])) != 1:
        raise ValueError('적재 보고서의 스냅샷 조회일을 확인하세요')
    input_dir = input_dir if input_dir is not None else report_path.parent
    documents, corpus_hash = load_documents(input_dir)
    table_name, documents, _ = prepare_documents(documents, settings, corpus_hash)
    if report.get('corpus_hash') != corpus_hash or report.get('table_name') != table_name or len(documents) != report['documents']:
        raise ValueError('적재 보고서와 청크 파일의 데이터 식별 정보가 다릅니다')
    if not re.fullmatch(r'regulations_[0-9a-f]{24}',table_name):
        raise ValueError('규정 테이블 이름이 올바르지 않습니다')
    connection = settings.pgvector_connection.get_secret_value()
    if not connection.startswith('postgresql+psycopg://'):
        raise ValueError('PGVECTOR_CONNECTION은 postgresql+psycopg:// 형식이어야 합니다')
    # 트랜잭션도 read-only로 선언한다. 테이블/확장을 만들거나 임베딩하지 않는다.
    with psycopg.connect(connection.replace('postgresql+psycopg://','postgresql://',1),
                         connect_timeout=5, row_factory=dict_row) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        extension = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
        if not extension:
            raise ValueError('pgvector 확장이 설치되지 않았습니다')
        rows = conn.execute(sql.SQL(
            'SELECT langchain_id, content, langchain_metadata, vector_dims(embedding) AS dimensions FROM {}'
        ).format(sql.Identifier('public',table_name))).fetchall()
    result = inspect_rows(documents,rows,settings.embedding_dimensions)
    result.update(table_name=table_name,embedding=report['embedding'],
                  pgvector_version=extension['extversion'],corpus_hash=corpus_hash,
                  snapshot_dates=report['snapshot_dates'],supplementary_indexed=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index-report',type=Path,help='기본값: RAG_INDEX_REPORT 설정')
    parser.add_argument('--input',type=Path,help='청크 폴더. 기본값: 보고서가 있는 폴더')
    parser.add_argument('--output',type=Path,help='점검 결과 JSON 저장 위치')
    args = parser.parse_args()
    load_runtime_environment()
    try:
        settings = Settings()
        result = check_status(settings,args.index_report or settings.rag_index_report,args.input)
    except ValueError as error:
        message = str(error) if type(error) is ValueError else type(error).__name__
        parser.exit(1,f'상태 점검 실패: {message}\n')
    except Exception as error:
        # DB 예외에 포함될 수 있는 접속 문자열을 출력하지 않는다.
        parser.exit(1,f'상태 점검 실패 ({type(error).__name__}). DB 실행 및 보고서 경로를 확인하세요.\n')
    text = json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text,encoding='utf-8')
    print(text,end='')
    if result['status'] != 'ready':
        parser.exit(1)


if __name__ == '__main__':
    main()
