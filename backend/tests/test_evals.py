"""The eval set and its checks (design Q2), without calling any LLM."""

import yaml

from evals.checks import EXPECTATIONS, check_turn
from evals.run import CASES, MODELS

PN = "763B00-11300000/A"


def _response(**overrides) -> dict:
    card = {
        "part_number": PN,
        "enclosure": "weatherproof",
        "power_supply": {"voltage": 110, "phase": "single", "current_type": "ac"},
        "data_available": True,
    }
    base = {
        "answer": "The 763B00-11300000/A delivers 500 Nm.",
        "status": "answered",
        "view": "cards",
        "products": [card],
        "alternatives": [],
        "quick_replies": [],
    }
    return base | overrides


DEBUG = {
    "number_check": {"status": "pass"},
    "rejected_refs": [],
    "steps": [{"tool": "lookup_part"}],
}


def _failed(results) -> list[str]:
    return [name for name, ok, _ in results if not ok]


def test_every_case_is_well_formed():
    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    assert len(cases) >= 30
    assert len({c["id"] for c in cases}) == len(cases)
    for case in cases:
        assert case["covers"] and case["turns"], case["id"]
        for turn in case["turns"]:
            unknown = set(turn.get("expect", {})) - EXPECTATIONS
            assert not unknown, f"{case['id']}: unknown expectations {unknown}"


def test_models_have_prices():
    prices = yaml.safe_load(MODELS.read_text(encoding="utf-8"))
    assert all({"input", "output"} <= set(p) for p in prices.values())


def test_passing_turn():
    expect = {"status": "answered", "products_exactly": [PN], "answer_any": ["500"],
              "products_where": {"voltage": 110, "enclosure": "weatherproof"}}  # fmt: skip
    assert _failed(check_turn("What is the torque?", _response(), DEBUG, expect)) == []


def test_wrong_status_and_products_fail():
    expect = {"status": "no_match", "products_max": 0, "products_where": {"voltage": 220}}
    failed = _failed(check_turn("x", _response(), DEBUG, expect))
    assert failed == ["status", "products_max", "products_where"]


def test_always_on_checks_catch_internals_fallback_and_invented_parts():
    response = _response(answer="I called lookup_part for you.")
    debug = {"number_check": {"status": "fallback"}, "rejected_refs": ["761Z99-00000000/A"]}
    failed = _failed(check_turn("What is it?", response, debug, {}))
    assert failed == ["no_internals", "numbers_supported", "no_invented_parts"]


def test_language_follows_the_question():  # NFR-04
    spanish = "¿Cuál es el torque del 763B00-11300000/A?"
    assert _failed(check_turn(spanish, _response(), DEBUG, {})) == ["language"]
    answer = "El 763B00-11300000/A entrega 500 Nm en servicio On/Off."
    assert _failed(check_turn(spanish, _response(answer=answer), DEBUG, {})) == []


def test_runner_runs_a_case_and_leaves_no_conversation(db_engine):
    from sqlalchemy import func, select

    from app.db.models import ChatSession
    from evals.run import run_case
    from tests.fakes import ScriptedModel, final, tool_call

    case = {
        "id": "lookup-basic",
        "covers": ["US-01 AC1"],
        "turns": [{"query": f"What is the torque of {PN}?",
                   "expect": {"status": "answered", "products_exactly": [PN]}}],
    }  # fmt: skip
    model = ScriptedModel(
        script=[
            tool_call("lookup_part", part_number=PN),
            final("It gives 500 Nm.", product_refs=[PN]),
        ]
    )
    result = run_case(db_engine, model, case)
    assert result["passed"], result
    assert result["turns"][0]["tools"] == [{"tool": "lookup_part", "args": {"part_number": PN}}]
    with db_engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(ChatSession)).scalar() == 0
