"""정규화된 조문을 검색용 청크로 나눈다. 모델 호출·임베딩은 하지 않는다."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.regulation import RegulationChunk
from ingest.normalize import NormalizedDocument


class ChunkingConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    chunk_size: int = Field(default=1200, ge=100)
    # 첫 기준선은 중복 없이 원문을 복원할 수 있도록 한다.
    # 항·호를 해석한 의미 단위 분할과 overlap 비교는 검색 평가 단계에서 수행한다.
    strategy: Literal['recursive-character-v1'] = 'recursive-character-v1'


class SearchChunk(BaseModel):
    """인용 원문과 임베딩용 문맥을 분리한다. 위치는 부모 text의 [start,end)."""

    model_config = ConfigDict(extra='forbid')
    regulation: RegulationChunk
    parent_chunk_id: str
    chunk_index: int
    start_char: int
    end_char: int
    context: str

    def to_document(self) -> Document:
        """Vector store가 받을 LangChain Document. metadata는 스칼라만 사용한다."""
        regulation = self.regulation
        metadata = regulation.model_dump(mode='json', exclude={'text', 'hierarchy'})
        metadata = {key: value for key, value in metadata.items() if value is not None}
        metadata.update(
            parent_chunk_id=self.parent_chunk_id, chunk_index=self.chunk_index,
            start_char=self.start_char, end_char=self.end_char, context=self.context,
        )
        return Document(
            id=regulation.chunk_id,
            page_content=f'{self.context}\n\n{regulation.text}', metadata=metadata,
        )


def chunk_article(article: RegulationChunk, config: ChunkingConfig) -> list[SearchChunk]:
    """조문을 넘나들지 않고 경계 우선 분할. 원문 손실 시 즉시 실패한다."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.chunk_size, chunk_overlap=0, length_function=len,
        separators=['\n\n', '\n', '. ', '。', ' ', ''],
        keep_separator='end', strip_whitespace=False,
    )
    parts = splitter.split_text(article.text)
    if ''.join(parts) != article.text:
        raise ValueError('청킹 중 원문이 변경되거나 누락되었습니다')
    context = '\n'.join([
        article.law_name, *article.hierarchy,
        f'제{article.article_no}조' + (f'({article.title})' if article.title else ''),
    ])
    # 가지번호는 법령 표기 관례인 제11조의2로 표시한다.
    if '의' in article.article_no:
        number, branch = article.article_no.split('의', 1)
        context = context.replace(f'제{article.article_no}조', f'제{number}조의{branch}')
    result = []
    start = 0
    for index, text in enumerate(parts):
        end = start + len(text)
        identity = f'{article.chunk_id}:{config.model_dump_json()}:{start}:{end}'
        chunk_id = 'search:' + hashlib.sha256(identity.encode()).hexdigest()
        regulation = article.model_copy(update={'chunk_id': chunk_id, 'text': text})
        # 현재 분할기는 항·호 번호를 추론하지 않는다. 부모 위치만 확실히 보존한다.
        result.append(SearchChunk(
            regulation=regulation, parent_chunk_id=article.chunk_id,
            chunk_index=index, start_char=start, end_char=end, context=context,
        ))
        start = end
    return result


def chunk_snapshot(input_dir: Path, output_dir: Path, config: ChunkingConfig) -> dict:
    manifest = json.loads((input_dir / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['status'] != 'normalized':
        raise ValueError('정규화 완료된 manifest만 청킹합니다')
    documents = []
    for record in manifest['documents']:
        path = (input_dir / record['file']).resolve()
        if not path.is_relative_to(input_dir.resolve()):
            raise ValueError('입력 파일 경로가 정규화 폴더 밖입니다')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != record['sha256']:
            raise ValueError('정규화 파일 해시 불일치')
        document = NormalizedDocument.model_validate_json(data)
        chunks = [chunk for article in document.chunks for chunk in chunk_article(article, config)]
        documents.append((record, document, chunks))
    if not documents:
        raise ValueError('청킹할 규정이 없습니다')
    output_dir.mkdir(parents=True, exist_ok=False)
    summary = {
        'schema_version': 1, 'status': 'chunked', 'config': config.model_dump(),
        'normalized_snapshot': input_dir.name, 'supplementary_indexed': False,
        'documents': [],
    }
    for record, document, chunks in documents:
        filename = Path(record['file']).stem + '.chunks.jsonl'
        content = ''.join(chunk.model_dump_json() + '\n' for chunk in chunks)
        (output_dir / filename).write_text(content, encoding='utf-8')
        summary['documents'].append({
            'file': filename, 'name': document.name, 'articles': len(document.chunks),
            'chunks': len(chunks), 'normalized_file': record['file'],
            'normalized_sha256': record['sha256'],
            'sha256': hashlib.sha256(content.encode()).hexdigest(),
        })
        print(f'{document.name}: 조문 {len(document.chunks)}개 → 청크 {len(chunks)}개')
    (output_dir / 'manifest.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8',
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--chunk-size', type=int, default=1200)
    args = parser.parse_args()
    config = ChunkingConfig(chunk_size=args.chunk_size)
    output = args.output or args.input.parent / f'{args.input.name}-chunks-{config.chunk_size}-v1'
    chunk_snapshot(args.input, output, config)
    print('저장 위치:', output)


if __name__ == '__main__':
    main()
