"""The conversation API end to end, with a scripted LLM (no cost) and the real PostgreSQL catalog.

Covers: product cards from the database (B3, NFR-01), follow-up context (US-02, B5), number check
repair and fallback (B4), rejected invented part numbers (B3), history and resume (US-15, US-16),
debug endpoint (US-19), error format (C4) and no internals in user responses (US-18 AC2).
"""

import json
import uuid

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from app.agent.llm import get_chat_model
from app.config import get_settings
from app.db.session import get_db
from app.main import app
from app.services.conversation import FALLBACK_TEXT, language_of
from tests.fakes import ScriptedModel, final, tool_call

PN = "763B00-11300000/A"


@pytest.fixture
def chat(db, make_user):
    """Returns a function that posts one turn with a given script, signed in as a test user."""
    app.dependency_overrides[get_db] = lambda: db
    user, token = make_user()
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

    def post(script, query="What is the torque of 763B00-11300000/A?", session_id=None):
        model = ScriptedModel(script=script)
        app.dependency_overrides[get_chat_model] = lambda: model
        body = {"query": query} | ({"session_id": str(session_id)} if session_id else {})
        response = client.post("/api/conversation", json=body)
        post.model = model
        return response

    post.client = client
    post.user = user
    yield post
    app.dependency_overrides.clear()


def _spec(product, group_key, spec_key):
    group = next(g for g in product["spec_groups"] if g["key"] == group_key)
    return [v["value"] for v in next(s for s in group["specs"] if s["key"] == spec_key)["values"]]


def lookup_turn():
    return [
        tool_call("lookup_part", part_number=PN),
        final(f"The {PN} delivers 500 Nm in On/Off service.", view="cards", product_refs=[PN]),
    ]


def test_answer_with_product_card_built_from_the_database(chat):  # US-01, B3
    r = chat(lookup_turn())
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "answered" and body["view"] == "cards"
    product = body["products"][0]
    assert product["part_number"] == PN
    assert _spec(product, "on_off", "torque") == [4400, 500]
    assert _spec(product, "electrical", "motor_power") == [90]
    assert "lookup_part" not in json.dumps(body)  # US-18 AC2: no internals for end users


def test_follow_up_gets_the_previous_product_in_context(chat):  # US-02, B5
    first = chat(lookup_turn()).json()
    second = chat(
        [tool_call("lookup_part", part_number=PN), final("It draws 90 W.", product_refs=[PN])],
        query="and how much power does it draw?",
        session_id=first["session_id"],
    )
    assert second.status_code == 200
    system_prompt = chat.model.seen[0][0].content
    assert f"Products shown recently (most recent first): {PN}" in system_prompt
    history = [m.content for m in chat.model.seen[0][1:]]
    assert history[-1] == "and how much power does it draw?"
    assert any("What is the torque" in h for h in history)


def test_invented_number_is_repaired(chat):  # B4
    r = chat(
        [
            final("It delivers 999 Nm.", product_refs=[PN]),  # no tool call, invented number
            tool_call("lookup_part", part_number=PN),
            final("It delivers 500 Nm.", product_refs=[PN]),
        ]
    )
    body = r.json()
    assert body["answer"] == "It delivers 500 Nm."
    debug = chat.client.get(f"/api/messages/{body['message_id']}/debug").json()
    assert debug["number_check"] == {"status": "repaired", "unsupported": ["999"]}


def test_number_still_invented_after_repair_falls_back(chat):  # B4
    r = chat([final("It delivers 999 Nm."), final("Still 999 Nm.")])
    body = r.json()
    assert body["answer"] == FALLBACK_TEXT["en"]
    debug = chat.client.get(f"/api/messages/{body['message_id']}/debug").json()
    assert debug["number_check"]["status"] == "fallback"


def test_fallback_is_in_the_users_language(chat):  # B4c, NFR-04
    r = chat(
        [final("Entrega 999 Nm."), final("Siguen siendo 999 Nm.")], query="¿Cuál es el torque?"
    )
    assert r.json()["answer"] == FALLBACK_TEXT["es"]


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("What is the torque of 763B00-11300000/A?", "en"),
        ("cual es el torque del 763B00", "es"),
        ("Necesito un actuador para zona 1", "es"),
        ("763B00-11300000/A", "en"),  # nothing to go on: English default
    ],
)
def test_language_detection(text, lang):  # B4c
    assert language_of(text) == lang


def test_part_number_no_tool_returned_is_rejected(chat):  # B3
    r = chat([final("Here it is.", view="cards", product_refs=[PN])])
    body = r.json()
    assert body["products"] == [] and body["view"] == "none"
    debug = chat.client.get(f"/api/messages/{body['message_id']}/debug").json()
    assert debug["rejected_refs"] == [PN]


def test_no_match_shows_labelled_alternatives(chat):  # US-10
    r = chat(
        [
            tool_call("search_actuators", enclosure="explosionproof", min_torque=5000),
            final(
                "No explosionproof model reaches 5000 Nm; the closest give 3000 Nm.",
                status="no_match",
                alternative_refs=["765Y30-11300000/A"],
            ),
        ],
        query="explosionproof, at least 5000 Nm",
    )
    body = r.json()
    assert body["status"] == "no_match" and body["view"] == "cards"
    alternative = body["alternatives"][0]
    assert "torque" in alternative["match_note"] and alternative["highlight"] == ["torque"]


def test_history_and_sessions_list_allow_resuming(chat):  # US-15, US-16
    first = chat(lookup_turn()).json()
    sessions = chat.client.get("/api/sessions").json()
    assert sessions[0]["id"] == first["session_id"]
    assert sessions[0]["title"] == "What is the torque of 763B00-11300000/A?"
    assert sessions[0]["message_count"] == 2
    history = chat.client.get(f"/api/sessions/{first['session_id']}/messages").json()
    assert [m["role"] for m in history["messages"]] == ["user", "assistant"]
    assert history["messages"][1]["products"][0]["part_number"] == PN  # snapshot (C7)


def test_debug_shows_tool_calls_parameters_results_and_tokens(chat):  # US-19 AC1
    body = chat(lookup_turn()).json()
    debug = chat.client.get(f"/api/messages/{body['message_id']}/debug").json()
    step = debug["steps"][0]
    assert step["tool"] == "lookup_part" and step["args"] == {"part_number": PN}
    assert step["result"]["status"] == "found"
    assert debug["tokens"] == {"input": 2000, "output": 200}
    assert debug["estimated_cost_usd"] > 0


def test_debug_endpoint_can_be_disabled(chat, monkeypatch):  # C2
    body = chat(lookup_turn()).json()
    monkeypatch.setattr(get_settings(), "debug_endpoints", False)
    r = chat.client.get(f"/api/messages/{body['message_id']}/debug")
    assert r.status_code == 404


def test_unknown_session_is_404_in_the_error_format(chat):  # US-16 AC4, C4
    r = chat(lookup_turn(), session_id=uuid.uuid4())
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "Conversation not found."}}


def test_blank_query_is_rejected(chat):  # C4
    r = chat(lookup_turn(), query="   ")
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"


def test_llm_failure_returns_502_and_leaves_no_conversation(chat):  # NFR-08
    down = openai.APIConnectionError(request=httpx.Request("POST", "https://openrouter.ai"))
    r = chat([down])
    assert r.status_code == 502 and r.json()["error"]["code"] == "llm_unavailable"
    assert chat.client.get("/api/sessions").json() == []


def test_no_match_never_shows_products_as_matches(chat):  # B10a, US-10 AC2
    r = chat(
        [
            tool_call("search_actuators", enclosure="explosionproof", min_torque=5000),
            final("No model reaches 5000 Nm.", status="no_match",
                  product_refs=["765Y30-11300000/A"]),
        ],
        query="explosionproof, at least 5000 Nm",
    )  # fmt: skip
    body = r.json()
    assert body["products"] == []
    assert [a["part_number"] for a in body["alternatives"]] == ["765Y30-11300000/A"]
    assert "torque" in body["alternatives"][0]["match_note"]
    debug = chat.client.get(f"/api/messages/{body['message_id']}/debug").json()
    assert debug["slot_fix"] == "products moved to alternatives (no_match)"


def test_clarifying_question_shows_no_cards(chat):  # B10a, US-04 AC2, US-08 AC1
    quick = [{"label": "110V", "message": "761A00-11300000/A"}]
    r = chat(
        [
            tool_call("lookup_part", part_number="761A00"),
            final("Which variant do you mean?", status="clarification_needed",
                  product_refs=["761A00-11300000/A"], quick_replies=quick),
        ],
        query="specs of 761A00",
    )  # fmt: skip
    body = r.json()
    assert body["products"] == [] and body["alternatives"] == [] and body["view"] == "none"
    assert body["quick_replies"] == quick
