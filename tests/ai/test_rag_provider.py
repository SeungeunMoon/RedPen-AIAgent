import asyncio
import json
from datetime import date
from pathlib import Path

import pytest
from langchain_core.documents import Document

from app.core.config import Settings
from app.kb.provider import UnsupportedRegulationDateError
from app.kb.search import RagRegulationProvider
from app.schemas.claim import Claim
from ingest.normalize import NormalizedDocument

SOURCE = Path(__file__).resolve().parents[2] / 'data/regulations/processed/20261021T043743991211Z-whole-article-v1/consumer_protection_act.normalized.json'


class Store:
    def __init__(self, documents):
        self.documents = documents
        self.queries = []
    def similarity_search(self, query, *, k, filter):
        self.queries.append((query, filter))
        return self.documents[:k]


def test_real_schema_restoration_deduplication_and_filter():
    chunks = NormalizedDocument.model_validate_json(SOURCE.read_bytes()).chunks[:2]
    documents = [Document(page_content=c.text, metadata={'corpus_hash':'a', 'regulation':c.model_dump(mode='json')}) for c in chunks]
    store = Store(documents)
    provider = RagRegulationProvider(store, snapshot_date=date(2026,10,21), corpus_hash='a')
    claims = [Claim(id='c1', quote='누구나 조건 없이 수익 보장', kind='guarantee')]
    results = asyncio.run(provider.provide(claims, as_of_date=date(2026,10,21)))
    assert results == chunks
    assert len(store.queries) == 2
    assert store.queries[0][1]['$and'][1] == {'effective_from':{'$lte':'2026-10-21'}}
    assert '누구나 조건 없이' in store.queries[1][0]
    assert asyncio.run(provider.provide([], as_of_date=date(2026,10,21))) == chunks


def test_unsupported_date_fails_before_search():
    store = Store([])
    provider = RagRegulationProvider(store, snapshot_date=date(2026,10,21), corpus_hash='a')
    with pytest.raises(UnsupportedRegulationDateError):
        asyncio.run(provider.provide([], as_of_date=date(2026,10,22)))
    assert store.queries == []


def test_search_failure_is_not_an_empty_success():
    class FailedStore(Store):
        def similarity_search(self, *args, **kwargs):
            raise ConnectionError('합성 DB 장애')
    provider = RagRegulationProvider(FailedStore([]), snapshot_date=date(2026,10,21), corpus_hash='a')
    with pytest.raises(ConnectionError):
        asyncio.run(provider.provide([], as_of_date=date(2026,10,21)))


def test_different_corpus_is_rejected():
    store = Store([Document(page_content='합성', metadata={'corpus_hash':'wrong'})])
    provider = RagRegulationProvider(store, snapshot_date=date(2026,10,21), corpus_hash='a')
    with pytest.raises(ValueError, match='corpus'):
        asyncio.run(provider.provide([], as_of_date=date(2026,10,21)))


def test_incomplete_index_is_rejected_without_db(tmp_path):
    report = tmp_path / 'report.json'
    report.write_text(json.dumps({'status':'failed'}))
    with pytest.raises(ValueError, match='완료 검증'):
        RagRegulationProvider.from_settings(Settings(rag_index_report=report))
