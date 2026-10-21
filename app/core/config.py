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
    embedding_model: Literal["text-embedding-3-small"] = "text-embedding-3-small"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_timeout_seconds: float = Field(default=60, gt=0)
    embedding_max_retries: int = Field(default=1, ge=0)
    pgvector_connection: SecretStr = SecretStr(
        'postgresql+psycopg://redpen:redpen@127.0.0.1:5433/redpen'
    )

    @model_validator(mode="after")
    def validate_openai_key(self) -> "Settings":
        if self.llm_provider == "openai" and self.openai_api_key is None:
            raise ValueError("LLM_PROVIDER=openai 사용 시 OPENAI_API_KEY가 필요합니다")
        return self

    def model_for(self, role: ModelRole | None = None) -> str:
        if role is None:
            return self.llm_model
        if role not in ("extract", "retrieve", "judge", "verify"):
            raise ValueError(f"지원하지 않는 모델 역할: {role}")
        return getattr(self, f"llm_{role}_model") or self.llm_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
