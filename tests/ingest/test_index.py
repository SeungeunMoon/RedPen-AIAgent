"""실제 청크 검증 및 합성 저장소의 재실행/부분 실패 복구 계약."""

import json
import os
from pathlib import Path

import pytest
from langchain_core.documents import Document

from app.ai.embeddings import get_embeddings
from app.core.config import Settings
from ingest.index import load_documents, prepare_documents, write_documents

SOURCE = Path(__file__).resolve().parents[2] / 'data/regulations/processed/20261021T043743991211Z-whole-article-v1-chunks-1200-v1'


@pytest.fixture(autouse=True)
def isolate_embedding_environment(monkeypatch):
    for name in os.environ:
        if name.startswith('EMBEDDING_'):
            monkeypatch.delenv(name)


class FakeStore:
    def __init__(self):
        self.rows = {}
        self.calls = 0
        self.fail_once = False

    def get_by_ids(self, ids):
        return [self.rows[id] for id in ids if id in self.rows]

    def add_documents(self, documents, *, ids):
        self.calls += 1
        for document in documents:
            self.rows[document.id] = document
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError('합성: 일부 행 commit 후 실패')
        return ids


def test_real_chunk_input_is_valid():
    documents, digest = load_documents(SOURCE)
    assert len(documents) == 202
    assert len(digest) == 64
    assert len({document.id for document in documents}) == 202
    for document in documents:
        assert document.metadata['regulation']['text'] in document.page_content


def test_tampered_chunk_rejected(tmp_path):
    manifest = json.loads((SOURCE / 'manifest.json').read_text())
    manifest['documents'] = manifest['documents'][:1]
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    (tmp_path / manifest['documents'][0]['file']).write_text('{}\n')
    with pytest.raises(ValueError, match='해시'):
        load_documents(tmp_path)


def test_rerun_skips_embeddings_and_partial_commits_can_resume():
    documents = [Document(id=str(index), page_content=f'합성 {index}') for index in range(5)]
    store = FakeStore()
    store.fail_once = True
    with pytest.raises(RuntimeError):
        write_documents(store, documents, batch_size=2)
    result = write_documents(store, documents, batch_size=2)
    assert result == {'inserted': 4, 'skipped': 1, 'verified': 5}
    calls = store.calls
    assert write_documents(store, documents) == {'inserted': 0, 'skipped': 5, 'verified': 5}
    assert store.calls == calls


def test_existing_content_mismatch_rejected():
    store = FakeStore()
    store.rows['a'] = Document(id='a', page_content='변조')
    with pytest.raises(ValueError, match='입력과 다릅니다'):
        write_documents(store, [Document(id='a', page_content='원문')])


def test_missing_final_rows_are_not_reported_complete():
    class DroppingStore(FakeStore):
        def add_documents(self, documents, *, ids):
            return ids
    with pytest.raises(ValueError, match='검증 실패'):
        write_documents(DroppingStore(), [Document(id='a', page_content='합성')])


def test_embedding_factory_is_independent_of_chat_provider():
    settings = Settings(_env_file=None, embedding_provider='openai', openai_api_key='test-key', llm_base_url='http://localhost:9999')
    embeddings = get_embeddings(settings=settings)
    assert embeddings.model == 'text-embedding-3-small'
    assert embeddings.dimensions == 1536
    assert embeddings.openai_api_base == 'https://api.openai.com/v1'
    assert embeddings.check_embedding_ctx_length is False
    with pytest.raises(ValueError, match='OPENAI_API_KEY'):
        get_embeddings(settings=Settings(_env_file=None, embedding_provider='openai', openai_api_key=None))


def test_token_limit_and_embedding_identity(monkeypatch):
    class SyntheticEncoding:
        def encode(self, text, **kwargs):
            return list(text)
    monkeypatch.setattr('ingest.index.tiktoken.encoding_for_model', lambda model: SyntheticEncoding())
    settings = Settings(_env_file=None, embedding_provider='openai')
    docs = [Document(id='chunk-a', page_content='합성 문장')]
    first, prepared, maximum = prepare_documents(docs, settings, 'corpus-a')
    assert maximum == 5
    assert prepare_documents(docs, settings, 'corpus-a')[1] == prepared
    assert prepare_documents(docs, settings, 'corpus-b')[0] != first
    assert prepare_documents(docs, settings.model_copy(update={'embedding_base_url': 'https://example.test/v1'}), 'corpus-a')[0] != first
    with pytest.raises(ValueError, match='토큰 초과'):
        prepare_documents([Document(id='long', page_content='가' * 8192)], settings, 'corpus-a')
