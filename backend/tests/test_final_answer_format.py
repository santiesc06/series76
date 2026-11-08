"""Invalid FinalAnswer calls from the model (design B3a). Scripted LLM, no cost.

Seen in production with Haiku via OpenRouter (2026-11-08): the model wrote the other fields as XML
inside `answer_text` (`...</parameter><parameter name="view">comparison...`), so `status` was
missing, and it repeated the mistake until the step limit (504).
"""

import logging

import pytest
from fastapi.testclient import TestClient

from app.agent.llm import get_chat_model
from app.agent.runner import RETRY_MESSAGE
from app.agent.schemas import FinalAnswer
from app.db.session import get_db
from app.main import app
from tests.fakes import ScriptedModel, tool_call

A, B = "762A00-11300000/A", "762B00-11300000/A"
LEAKED = (
    'Both are weatherproof 110V single-phase actuators.</parameter>\n<parameter name="view">'
    'comparison</parameter>\n<parameter name="product_refs">["762A00-11300000/A"]'
)


@pytest.fixture
def post(db, make_user):
    app.dependency_overrides[get_db] = lambda: db
    _, token = make_user()
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

    def send(script):
        model = ScriptedModel(script=script)
        app.dependency_overrides[get_chat_model] = lambda: model
        send.model = model
        return client.post("/api/conversation", json={"query": f"Compare {A} and {B}"})

    yield send
    app.dependency_overrides.clear()


def broken_answer():
    """What the model sent: everything inside answer_text, no status."""
    return tool_call("FinalAnswer", answer_text=LEAKED)


def lookups():
    return [tool_call("lookup_part", part_number=A), tool_call("lookup_part", part_number=B)]


def test_answer_text_is_the_last_field_the_model_writes():  # B3a
    fields = list(FinalAnswer.model_json_schema()["properties"])
    assert fields[0] == "status" and fields[-1] == "answer_text"


def test_leaked_markup_is_cut_from_the_answer_text():  # B3a
    answer = FinalAnswer(status="answered", answer_text=LEAKED)
    assert answer.answer_text == "Both are weatherproof 110V single-phase actuators."
    assert FinalAnswer(status="answered", answer_text="A <b>plain</b> text").answer_text == (
        "A <b>plain</b> text"
    )


def test_invalid_final_answer_gets_a_clear_retry_message(post):  # B3a
    good = tool_call(
        "FinalAnswer",
        status="answered",
        view="comparison",
        product_refs=[A, B],
        answer_text="Here they are side by side.",
    )
    r = post([*lookups(), broken_answer(), good])
    assert r.status_code == 200
    body = r.json()
    assert body["view"] == "comparison"
    assert [p["part_number"] for p in body["products"]] == [A, B]

    retry = post.model.seen[-1][-1].content  # what the model read before its second try
    assert retry == RETRY_MESSAGE.format(problem="status: missing")
    assert "pydantic" not in retry


def test_repeated_invalid_answers_are_logged_without_user_text(post, caplog):  # B3a
    caplog.set_level(logging.WARNING, logger="api")
    r = post([*lookups(), *[broken_answer() for _ in range(20)]])
    assert r.status_code == 504
    assert r.json()["error"]["code"] == "agent_step_limit"

    record = next(rec for rec in caplog.records if rec.getMessage() == "agent error")
    assert record.code == "agent_step_limit"
    assert "invalid FinalAnswer call(s); last: status: missing" in record.detail
    assert "weatherproof" not in record.detail  # the answer text never reaches the log
