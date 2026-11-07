"""Optional Langfuse tracing (design Q6).

Off unless LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set. When on, each agent run gets a
LangChain callback that sends the trace (LLM calls, tool calls, tokens, latency) to Langfuse,
grouped by conversation (session_id). The app's debug screen does not depend on it: its data comes
from PostgreSQL (US-19).
"""

import logging
from functools import lru_cache
from typing import Any

from app.config import get_settings

log = logging.getLogger("observability")


def tracing_enabled() -> bool:
    s = get_settings()
    return bool(s.langfuse_public_key and s.langfuse_secret_key)


@lru_cache
def _client() -> Any:
    from langfuse import Langfuse  # imported only when tracing is on

    s = get_settings()
    log.info("Langfuse tracing enabled", extra={"host": s.langfuse_host})
    return Langfuse(
        public_key=s.langfuse_public_key, secret_key=s.langfuse_secret_key, host=s.langfuse_host
    )


def _handler() -> Any:
    from langfuse.langchain import CallbackHandler

    _client()  # registers the configured client before the handler looks it up
    return CallbackHandler(public_key=get_settings().langfuse_public_key)


def tracing_config(session_id: str, tags: list[str]) -> dict:
    """LangChain run config for one agent run: Langfuse callback and grouping, or {} when off."""
    if not tracing_enabled():
        return {}
    try:
        handler = _handler()
    except Exception:  # tracing must never break a user's turn
        log.exception("Langfuse tracing could not start; continuing without it")
        return {}
    return {
        "callbacks": [handler],
        "metadata": {"langfuse_session_id": session_id, "langfuse_tags": tags},
    }


def flush() -> None:
    """Send pending traces (short-lived processes such as the eval runner call this at the end)."""
    if tracing_enabled():
        _client().flush()
