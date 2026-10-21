"""선택 실행: 실제 pgvector + 합성 임베딩. 실제 OpenAI 호출을 검증하지 않는다."""

import asyncio
import os
from uuid import NAMESPACE_URL, uuid5

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

from app.core.config import Settings
from ingest.index import open_store, write_documents


@pytest.mark.skipif(os.environ.get('REDPEN_PGVECTOR_INTEGRATION') != '1', reason='로컬 pgvector 선택 실행')
def test_actual_pgvector_roundtrip_and_idempotency():
    settings = Settings(_env_file=None, llm_provider='ollama')
    embeddings = DeterministicFakeEmbedding(size=1536)
    engine, store = open_store(settings, 'test_regulation_ingest_v1', embeddings)
    documents = [Document(
        id=str(uuid5(NAMESPACE_URL, f'redpen-synthetic-integration-{index}')),
        page_content=text, metadata={'synthetic': True, 'source': {'article': index}},
    ) for index, text in enumerate(['합성: 광고 금리 표시 규정', '합성: 우대 조건 설명 규정'])]
    try:
        assert write_documents(store, documents)['verified'] == 2
        assert write_documents(store, documents) == {'inserted': 0, 'skipped': 2, 'verified': 2}
        result = store.similarity_search(documents[0].page_content, k=1)
        assert str(result[0].id) == documents[0].id
        assert result[0].metadata['synthetic'] is True
    finally:
        asyncio.run(engine.close())
