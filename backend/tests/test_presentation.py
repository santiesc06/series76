"""Product cards for the special table shapes (design §4.1)."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import Part
from app.main import app
from app.services.presentation import product_card


def _card(db, pn: str, **kw) -> dict:
    part = db.scalar(
        select(Part)
        .where(Part.part_number == pn)
        .options(selectinload(Part.ratings), selectinload(Part.table))
    )
    return product_card(part, **kw)


def _values(card, group_key, spec_key):
    group = next(g for g in card["spec_groups"] if g["key"] == group_key)
    return next(s for s in group["specs"] if s["key"] == spec_key)["values"]


def test_single_phase_card_has_both_services_and_frequency_conditions(db):
    card = _card(db, "763B00-11300000/A", highlight=["on_off.torque"])
    assert [g["key"] for g in card["spec_groups"]] == ["on_off", "modulating", "electrical"]
    assert _values(card, "electrical", "speed") == [
        {"value": 26, "unit": "s", "condition": "60 Hz"},
        {"value": 32, "unit": "s", "condition": "50 Hz"},
    ]
    assert card["highlight"] == ["on_off.torque"]


def test_highlight_only_the_requested_service():  # US-07 AC3: services are never mixed
    from app.services.presentation import highlights_for

    assert highlights_for({"min_torque": 500, "service": "modulating"}) == [
        "modulating.torque",
        "both.torque",
    ]
    assert highlights_for({"min_torque": 500}) == [
        "on_off.torque",
        "modulating.torque",
        "both.torque",
    ]
    assert highlights_for({"max_speed_s": 20, "voltage": 110}) == ["electrical.speed"]
    assert highlights_for(None) == []


def test_24v_card_shows_one_frequency_independent_value(db):  # US-11 AC4
    card = _card(db, "763X30-11370000/A")
    assert _values(card, "electrical", "speed") == [{"value": 32, "unit": "s"}]
    assert [g["key"] for g in card["spec_groups"]] == ["modulating", "electrical"]
    assert card["power_supply"]["label"] == "24V DC"


def test_three_phase_card_has_one_rating_for_both_services(db):  # D-1
    card = _card(db, "763A00-11330C00/A")
    assert card["spec_groups"][0]["title"] == "On/Off and Modulating service"
    keys = [s["key"] for s in card["spec_groups"][0]["specs"]]
    assert keys == ["torque", "duty_cycle", "cycles_per_hour", "starts_per_hour"]


def test_na_card_has_no_numbers(db):  # US-05
    card = _card(db, "761A00-11330C00/A")
    assert card["data_available"] is False and card["spec_groups"] == []


def test_openapi_documents_the_conversation_contract():
    schema = TestClient(app).get("/openapi.json").json()
    request = schema["components"]["schemas"]["ConversationRequest"]["properties"]
    assert {"session_id", "query"} <= set(request)
    assert "/api/messages/{message_id}/debug" in schema["paths"]
