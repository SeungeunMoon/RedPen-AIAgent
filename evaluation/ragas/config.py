"""서비스 모델과 독립적인 OpenAI 평가 모델 설정."""

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import PROJECT_ROOT


class EvaluatorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix='RAGAS_',env_file=PROJECT_ROOT/'.env',extra='ignore',env_ignore_empty=True,
    )
    model: str = Field(default='gpt-4o-mini',min_length=1)
    base_url: str = 'https://api.openai.com/v1'
    api_key: SecretStr | None = Field(default=None,
        validation_alias=AliasChoices('RAGAS_OPENAI_API_KEY','OPENAI_API_KEY'))
    timeout_seconds: float = Field(default=60,gt=0)
    metric_timeout_seconds: float = Field(default=180,gt=0)
    max_retries: int = Field(default=1,ge=0)
