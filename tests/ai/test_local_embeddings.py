"""로컬 임베딩 프로필과 자동 입력 잘라내기 방지를 검증한다."""

import asyncio

import pytest
from pydantic import ValidationError

from app.ai.embeddings import StrictOllamaEmbeddings, get_embeddings
from app.core.config import Settings
from ingest.index import prepare_documents
from langchain_core.documents import Document


def local_settings():
    return Settings(_env_file=None, embedding_provider='ollama', embedding_model='bge-m3',
                    embedding_base_url='http://localhost:11434', openai_api_key=None)


def test_local_factory_needs_no_openai_key():
    settings = local_settings()
    embeddings = get_embeddings(settings=settings)
    assert isinstance(embeddings, StrictOllamaEmbeddings)
    assert embeddings.model == 'bge-m3'
    assert embeddings.num_ctx == 8192
    assert settings.embedding_dimensions == 1024
    with pytest.raises(ValidationError, match='프로필'):
        Settings(_env_file=None, embedding_provider='ollama', embedding_model='text-embedding-3-small')


def test_local_validation_does_not_use_openai_tokenizer(monkeypatch):
    def unexpected(*args):
        raise AssertionError('bge-m3에는 tiktoken을 적용하지 않는다')
    monkeypatch.setattr('ingest.index.tiktoken.encoding_for_model', unexpected)
    _, documents, maximum = prepare_documents([Document(id='a', page_content='합성')], local_settings(), 'corpus')
    assert maximum is None
    assert documents[0].metadata['embedding_spec']['input_validation'] == 'ollama-no-truncation-v1'


def test_sync_and_async_query_disable_truncation():
    embeddings = get_embeddings(settings=local_settings())
    calls = []
    class Client:
        def embed(self, model, texts, **kwargs):
            calls.append(kwargs)
            return {'embeddings': [[1.0, 2.0] for text in texts]}
    class AsyncClient:
        async def embed(self, model, texts, **kwargs):
            calls.append(kwargs)
            return {'embeddings': [[1.0, 2.0] for text in texts]}
    embeddings._client = Client()
    embeddings._async_client = AsyncClient()
    assert embeddings.embed_query('합성') == [1.0, 2.0]
    assert asyncio.run(embeddings.aembed_query('합성')) == [1.0, 2.0]
    assert len(calls) == 2
    assert all(call['truncate'] is False for call in calls)
