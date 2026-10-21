"""환경변수와 프로젝트 루트의 .env에서 모델 설정을 읽는다."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ModelRole = Literal["extract", "retrieve", "judge", "verify"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8",
        extra="ignore", env_ignore_empty=True,
    )

    llm_provider: Literal["openai", "ollama"] = "ollama"
    llm_model: str = Field(default="qwen2.5:7b", min_length=1)
    llm_base_url: str | None = None
    llm_temperature: float | None = None
    llm_timeout_seconds: float = Field(default=60, gt=0)
    llm_max_retries: int = Field(default=1, ge=0)

    llm_extract_model: str | None = None
    llm_retrieve_model: str | None = None
    llm_judge_model: str | None = None
    llm_verify_model: str | None = None
    openai_api_key: SecretStr | None = None

    # LLM 전환과 독립. 규정 적재와 검색에서 동일한 임베딩을 사용한다.
    embedding_provider: Literal['openai', 'ollama'] = 'ollama'
    embedding_model: str | None = None
    embedding_base_url: str | None = None
    embedding_timeout_seconds: float = Field(default=180, gt=0)
    embedding_max_retries: int = Field(default=1, ge=0)
    regulation_provider: Literal['rag', 'fixed', 'empty'] = 'rag'
    rag_index_report: Path = PROJECT_ROOT / 'data/regulations/processed/20261021T043743991211Z-whole-article-v1-chunks-1200-v1/index-report-bge-m3.json'
    rag_top_k: int = Field(default=4, ge=1, le=20)
    rag_max_chunks: int = Field(default=12, ge=1, le=40)
    pgvector_connection: SecretStr = SecretStr(
        'postgresql+psycopg://redpen:redpen@127.0.0.1:5433/redpen'
    )

    @model_validator(mode="after")
    def validate_openai_key(self) -> "Settings":
        if self.llm_provider == "openai" and self.openai_api_key is None:
            raise ValueError("LLM_PROVIDER=openai 사용 시 OPENAI_API_KEY가 필요합니다")
        return self

    @model_validator(mode='after')
    def resolve_embedding_profile(self) -> 'Settings':
        model, url = {
            'openai': ('text-embedding-3-small', 'https://api.openai.com/v1'),
            'ollama': ('bge-m3', 'http://localhost:11434'),
        }[self.embedding_provider]
        if self.embedding_model is None:
            self.embedding_model = model
        if self.embedding_model != model:
            raise ValueError(f'{self.embedding_provider} 임베딩은 현재 {model} 프로필만 지원합니다')
        if self.embedding_base_url is None:
            self.embedding_base_url = url
        return self

    @property
    def embedding_dimensions(self) -> int:
        return 1024 if self.embedding_provider == 'ollama' else 1536

    def model_for(self, role: ModelRole | None = None) -> str:
        if role is None:
            return self.llm_model
        if role not in ("extract", "retrieve", "judge", "verify"):
            raise ValueError(f"지원하지 않는 모델 역할: {role}")
        return getattr(self, f"llm_{role}_model") or self.llm_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
