"""Langfuse tracing is optional and off by default (design Q6)."""

from app import observability
from app.config import get_settings


def test_tracing_is_off_without_keys():
    assert observability.tracing_enabled() is False
    assert observability.tracing_config("session", ["api"]) == {}


def test_tracing_config_groups_runs_by_session(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "langfuse_public_key", "pk-lf-test")
    monkeypatch.setattr(settings, "langfuse_secret_key", "sk-lf-test")
    monkeypatch.setattr(observability, "_handler", lambda: "handler")  # no network
    config = observability.tracing_config("abc", ["eval", "lookup-basic"])
    assert config["callbacks"] == ["handler"]
    assert config["metadata"] == {
        "langfuse_session_id": "abc",
        "langfuse_tags": ["eval", "lookup-basic"],
    }


def test_a_tracing_failure_never_breaks_a_turn(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "langfuse_public_key", "pk-lf-test")
    monkeypatch.setattr(settings, "langfuse_secret_key", "sk-lf-test")

    def broken():
        raise RuntimeError("no network")

    monkeypatch.setattr(observability, "_handler", broken)
    assert observability.tracing_config("abc", ["api"]) == {}
