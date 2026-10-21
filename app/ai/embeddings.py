"""적재와 검색에서 함께 사용하는 LangChain 임베딩 팩토리."""

from langchain_openai import OpenAIEmbeddings

from app.core.config import Settings, get_settings

EMBEDDING_DIMENSIONS = 1536
EMBEDDING_MAX_TOKENS = 8191


def get_embeddings(*, settings: Settings | None = None) -> OpenAIEmbeddings:
    config = settings if settings is not None else get_settings()
    if config.openai_api_key is None:
        raise ValueError('규정 임베딩에는 OPENAI_API_KEY가 필요합니다')
    return OpenAIEmbeddings(
        model=config.embedding_model, dimensions=EMBEDDING_DIMENSIONS,
        api_key=config.openai_api_key, base_url=config.embedding_base_url,
        request_timeout=config.embedding_timeout_seconds,
        max_retries=config.embedding_max_retries, chunk_size=32,
        # 인덱서가 context를 포함한 전체 입력 토큰을 검증한다.
        # 초과 입력을 내부에서 자동 분할·평균하여 숨기지 않는다.
        check_embedding_ctx_length=False,
    )
