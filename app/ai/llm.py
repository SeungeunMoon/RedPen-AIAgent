"""각 단계에서 공통으로 사용하는 LangChain 채팅 모델 팩토리."""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app.core.config import ModelRole, Settings, get_settings


def get_chat_model(
    role: ModelRole | None = None, *, settings: Settings | None = None,
) -> BaseChatModel:

    config = settings if settings is not None else get_settings()
    model_name = config.model_for(role)
    temperature = (
        {"temperature": config.llm_temperature}
        if config.llm_temperature is not None else {}
    )
    
    if config.llm_provider == "openai":
        return ChatOpenAI(
            model=model_name,
            api_key=config.openai_api_key,
            base_url=config.llm_base_url or "https://api.openai.com/v1",
            timeout=config.llm_timeout_seconds,
            max_retries=config.llm_max_retries,
            **temperature,
        )
    
    return ChatOllama(
        model=model_name,
        base_url=config.llm_base_url or "http://localhost:11434",
        client_kwargs={"timeout": config.llm_timeout_seconds},
        **temperature,
    )
