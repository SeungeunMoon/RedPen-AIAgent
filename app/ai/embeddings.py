"""적재와 검색에서 함께 사용하는 LangChain 임베딩 팩토리."""

from langchain_openai import OpenAIEmbeddings
from langchain_ollama import OllamaEmbeddings
from langchain_core.embeddings import Embeddings

from app.core.config import Settings, get_settings

EMBEDDING_MAX_TOKENS = 8191


class StrictOllamaEmbeddings(OllamaEmbeddings):
    """Ollama의 자동 잘라내기를 끈 LangChain 어댑터.

    현재 OllamaEmbeddings에는 truncate 옵션이 없어 공식 클라이언트의
    embed 호출에 truncate=False만 명시한다. 초과 입력을 조용히 손실하지 않는다.
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed(
            self.model, texts, truncate=False, options=self._default_params,
            keep_alive=self.keep_alive,
        )['embeddings']

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return (await self._async_client.embed(
            self.model, texts, truncate=False, options=self._default_params,
            keep_alive=self.keep_alive,
        ))['embeddings']


def get_embeddings(*, settings: Settings | None = None) -> Embeddings:
    config = settings if settings is not None else get_settings()
    if config.embedding_provider == 'ollama':
        return StrictOllamaEmbeddings(
            model=config.embedding_model, base_url=config.embedding_base_url,
            num_ctx=8192, client_kwargs={'timeout': config.embedding_timeout_seconds},
        )
    if config.openai_api_key is None:
        raise ValueError('규정 임베딩에는 OPENAI_API_KEY가 필요합니다')
    return OpenAIEmbeddings(
        model=config.embedding_model, dimensions=config.embedding_dimensions,
        api_key=config.openai_api_key, base_url=config.embedding_base_url,
        request_timeout=config.embedding_timeout_seconds,
        max_retries=config.embedding_max_retries, chunk_size=32,
        # 인덱서가 context를 포함한 전체 입력 토큰을 검증한다.
        # 초과 입력을 내부에서 자동 분할·평균하여 숨기지 않는다.
        check_embedding_ctx_length=False,
    )
