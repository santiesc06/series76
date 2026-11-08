"""Application settings, read from environment variables (and `.env` for local runs)."""

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> repo root is two levels up from backend/
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM (OpenRouter, OpenAI-compatible API)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "anthropic/claude-haiku-5.5"  # design §3.2; must support tool calling
    llm_temperature: float = 0.0
    llm_max_tokens: int = 1024
    llm_timeout_s: float = 30.0
    max_tool_iterations: int = 6  # per user turn (design B1)
    # USD per 1M tokens, only used to log an estimated cost per request (design Q4)
    llm_price_input_per_m: float = 0.10
    llm_price_output_per_m: float = 0.50

    # Ingestion: two vision models (OpenAI-compatible APIs) whose extractions are diffed
    extraction_a_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    extraction_a_api_key: str = ""
    extraction_a_model: str = ""
    extraction_b_base_url: str = "https://openrouter.ai/api/v1"
    extraction_b_api_key: str = ""  # falls back to openrouter_api_key when empty
    extraction_b_model: str = "anthropic/claude-haiku-5.5"

    # Voice (US-22): faster-whisper model name (design V2); the Docker image ships this model (V3)
    whisper_model: str = "small"

    # Database
    database_url: str = "postgresql+psycopg://series76:series76@localhost:5433/series76"

    # API
    log_level: str = "INFO"
    history_window: int = 12  # previous messages sent to the LLM as context (design B5)
    # Developer-only endpoint with tool calls and token usage (design C2). On by default so the
    # app's debug screen works out of the box; turn off in production.
    debug_endpoints: bool = True
    auth_token_ttl_hours: int = 168  # login tokens expire after 7 days (design U1)

    # Optional Langfuse tracing (design Q6): off unless both keys are set.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


@lru_cache
def get_settings() -> Settings:
    # APP_DISABLE_DOTENV=1 ignores .env entirely (tests, CI, tooling that must not see secrets):
    # only real environment variables and the defaults above are used.
    if os.environ.get("APP_DISABLE_DOTENV") == "1":
        return Settings(_env_file=None)
    return Settings()
