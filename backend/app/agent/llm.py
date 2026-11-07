"""The chat model, reached through OpenRouter's OpenAI-compatible API (design B7).

`get_chat_model` is a FastAPI dependency, so tests replace it with a scripted fake model and never
call a real LLM.
"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.config import get_settings


class LLMNotConfiguredError(RuntimeError):
    pass


def get_chat_model() -> BaseChatModel:
    s = get_settings()
    if not s.openrouter_api_key or not s.llm_model:
        raise LLMNotConfiguredError("OPENROUTER_API_KEY and LLM_MODEL must be set")
    return ChatOpenAI(
        model=s.llm_model,
        base_url=s.openrouter_base_url,
        api_key=s.openrouter_api_key,
        temperature=s.llm_temperature,
        max_tokens=s.llm_max_tokens,
        timeout=s.llm_timeout_s,
        max_retries=2,
    )
