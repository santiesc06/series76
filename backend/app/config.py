"""Application settings, read from environment variables (and `.env` for local runs)."""

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
    llm_model: str = ""
    llm_temperature: float = 0.0
    llm_max_tokens: int = 1024

    # Ingestion
    extraction_model: str = ""

    # Database
    database_url: str = "postgresql+psycopg://series76:series76@localhost:5433/series76"

    # API
    log_level: str = "INFO"
    history_window: int = 12


@lru_cache
def get_settings() -> Settings:
    return Settings()
