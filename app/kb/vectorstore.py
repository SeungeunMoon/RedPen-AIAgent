"""적재와 검색에서 공유하는 LangChain pgvector 설정."""

import asyncio

import psycopg
from langchain_core.embeddings import Embeddings
from langchain_postgres import PGEngine, PGVectorStore

from app.core.config import Settings


def embedding_spec(settings: Settings) -> dict:
    return {
        'provider': settings.embedding_provider, 'model': settings.embedding_model,
        'base_url': settings.embedding_base_url, 'dimensions': settings.embedding_dimensions,
        'document_format': 'context-and-original-v1',
        'input_validation': 'ollama-no-truncation-v1' if settings.embedding_provider == 'ollama' else 'tiktoken-v1',
    }


def open_store(settings: Settings, table_name: str, embeddings: Embeddings, *, create_if_missing: bool = True):
    """데이터/모델별 전용 테이블. 기존 테이블이나 데이터를 삭제하지 않는다."""
    connection = settings.pgvector_connection.get_secret_value()
    if not connection.startswith('postgresql+psycopg://'):
        raise ValueError('PGVECTOR_CONNECTION은 postgresql+psycopg:// 형식이어야 합니다')
    engine = PGEngine.from_connection_string(url=connection, connect_args={'connect_timeout': 5})
    try:
        with psycopg.connect(connection.replace('postgresql+psycopg://', 'postgresql://', 1), connect_timeout=5) as conn:
            exists = conn.execute('SELECT to_regclass(%s)', (f'public.{table_name}',)).fetchone()[0]
        if exists is None:
            if not create_if_missing:
                raise ValueError('완료 보고서의 벡터 테이블이 DB에 없습니다')
            engine.init_vectorstore_table(table_name=table_name, vector_size=settings.embedding_dimensions)
        store = PGVectorStore.create_sync(engine=engine, table_name=table_name, embedding_service=embeddings)
        return engine, store
    except Exception:
        asyncio.run(engine.close())
        raise


