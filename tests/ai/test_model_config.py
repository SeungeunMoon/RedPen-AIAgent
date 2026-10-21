import os

import pytest
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from app.ai.llm import get_chat_model
from app.core.config import Settings


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in os.environ:
        if name.startswith(("LLM_", "OPENAI_", "EMBEDDING_")):
            monkeypatch.delenv(name)


def test_default_is_local_ollama():
    model = get_chat_model(settings=Settings(_env_file=None))
    assert isinstance(model, ChatOllama)
    assert model.base_url == "http://localhost:11434"
    assert model.temperature is None
    assert model.num_ctx == 16384


def test_openai_requires_key():
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings(_env_file=None, llm_provider="openai")


def test_openai_role_override_and_endpoint():
    settings = Settings(
        _env_file=None, llm_provider="openai", llm_model="default-model",
        llm_judge_model="judge-model", openai_api_key="test-only-key",
        llm_base_url="https://example.test/v1", llm_timeout_seconds=12,
        llm_max_retries=2,
    )
    model = get_chat_model("judge", settings=settings)
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "judge-model"
    assert model.openai_api_base == "https://example.test/v1"
    assert model.request_timeout == 12
    assert model.max_retries == 2
    assert settings.model_for("extract") == "default-model"
    assert "test-only-key" not in repr(settings)


def test_dotenv_and_environment_precedence(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("LLM_MODEL=file-model\nLLM_JUDGE_MODEL=\nLLM_TEMPERATURE=\n")
    monkeypatch.setenv("LLM_MODEL", "environment-model")
    settings = Settings(_env_file=env)
    assert settings.model_for("judge") == "environment-model"
    assert settings.llm_temperature is None


def test_llm_endpoint_does_not_change_embeddings():
    settings = Settings(_env_file=None, llm_base_url="http://localhost:9999")
    assert settings.embedding_base_url == "http://localhost:11434"
    assert settings.embedding_model == 'bge-m3'
    assert settings.embedding_dimensions == 1024
    with pytest.raises(ValidationError):
        Settings(_env_file=None, embedding_model="another-model")


@pytest.mark.parametrize("values", [
    {"llm_provider": "unknown"}, {"llm_timeout_seconds": 0},
    {"llm_max_retries": -1}, {"llm_model": ""},
    {'llm_num_ctx': 0},
])
def test_invalid_settings_fail_early(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_unknown_role_is_rejected():
    with pytest.raises(ValueError, match="역할"):
        Settings(_env_file=None).model_for("typo")
