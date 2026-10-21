"""LangChain pgvector 검색을 RegulationProvider 계약으로 제공한다."""

import asyncio
import json
import re
from collections.abc import Sequence
from datetime import date

from app.ai.embeddings import get_embeddings
from app.core.config import Settings
from app.kb.provider import UnsupportedRegulationDateError
from app.schemas.claim import Claim
from app.schemas.regulation import RegulationChunk


class RagRegulationProvider:
    def __init__(self, store, *, snapshot_date: date, corpus_hash: str, top_k: int = 4,
                 max_chunks: int = 12, engine=None):
        self._store = store
        self._snapshot_date = snapshot_date
        self._corpus_hash = corpus_hash
        self._top_k = top_k
        self._max_chunks = max_chunks
        self._engine = engine

    @classmethod
    def from_settings(cls, settings: Settings):
        # 적재와 같은 공식 store와 fingerprint 계약을 공유한다.
        from app.kb.vectorstore import embedding_spec, open_store
        report = json.loads(settings.rag_index_report.read_text(encoding='utf-8'))
        if report.get('status') != 'indexed' or report.get('verified') != report.get('documents'):
            raise ValueError('완료 검증된 인덱스 보고서가 필요합니다')
        if report['embedding'] != embedding_spec(settings):
            raise ValueError('적재와 검색의 임베딩 설정이 다릅니다')
        if len(report.get('snapshot_dates', [])) != 1:
            raise ValueError('하나의 규정 스냅샷 조회일이 필요합니다. 인덱서를 재실행하세요')
        table = report['table_name']
        if not re.fullmatch(r'regulations_[0-9a-f]{24}', table):
            raise ValueError('인덱스 테이블명이 올바르지 않습니다')
        engine, store = open_store(settings, table, get_embeddings(settings=settings), create_if_missing=False)
        return cls(store, snapshot_date=date.fromisoformat(report['snapshot_dates'][0]),
                   corpus_hash=report['corpus_hash'], top_k=settings.rag_top_k,
                   max_chunks=settings.rag_max_chunks, engine=engine)

    async def provide(self, claims: Sequence[Claim], *, as_of_date: date) -> list[RegulationChunk]:
        # 종료일 미확정인 현행 스냅샷: 조회일 외의 효력을 추정하지 않는다.
        if as_of_date != self._snapshot_date:
            raise UnsupportedRegulationDateError('RAG 규정은 스냅샷 조회일에만 제공할 수 있습니다')
        queries = ['금융상품 광고 준수사항 필수 표시사항 금리 우대조건 광고 금지행위']
        queries.extend(f'금융상품 광고 {claim.kind}: {claim.quote}' for claim in claims)
        queries = list(dict.fromkeys(queries))
        filters = {'$and': [
            {'corpus_hash': {'$eq': self._corpus_hash}},
            {'effective_from': {'$lte': as_of_date.isoformat()}},
        ]}
        # 동기 PGVectorStore 작업을 이벤트 루프 밖에서 실행한다.
        def search():
            return [self._store.similarity_search(query, k=self._top_k, filter=filters) for query in queries]
        groups = await asyncio.to_thread(search)
        selected = {}
        # 쿼리별 첫 근거부터 순환해 긴 광고의 뒤쪽 클레임도 기회를 갖도록 한다.
        for rank in range(self._top_k):
            for group in groups:
                if rank >= len(group):
                    continue
                document = group[rank]
                if document.metadata.get('corpus_hash') != self._corpus_hash:
                    raise ValueError('다른 corpus의 검색 결과입니다')
                chunk = RegulationChunk.model_validate(document.metadata['regulation'])
                if chunk.effective_from > as_of_date or (chunk.effective_to and as_of_date >= chunk.effective_to):
                    continue
                if chunk.chunk_id not in selected and len(selected) < self._max_chunks:
                    selected[chunk.chunk_id] = chunk
        return list(selected.values())

    async def aclose(self):
        if self._engine is not None:
            await self._engine.close()
