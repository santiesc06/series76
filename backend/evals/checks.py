"""Deterministic checks for one eval turn (design Q2). No LLM-as-judge.

A turn's `expect` block (from questions.yaml) lists checks by name. Three checks always run:
the answer mentions no internals, the number check did not end in the fallback sentence, and no
invented part number was rejected. Each check returns (name, passed, detail).
"""

from typing import Any

from app.services.conversation import language_of

INTERNAL_NAMES = ("lookup_part", "search_actuators", "catalog_overview", "FinalAnswer")

Result = tuple[str, bool, str]
EXPECTATIONS = {
    "status", "view", "language", "products_exactly", "products_include", "products_exclude",
    "products_min", "products_max", "products_where", "alternatives_include", "alternatives_max",
    "quick_replies_min", "answer_any", "answer_none", "tools_called",
}  # fmt: skip


def _parts(cards: list[dict]) -> list[str]:
    return [c["part_number"] for c in cards]


def _card_value(card: dict, field: str) -> Any:
    if field in ("voltage", "phase", "current_type"):
        return (card.get("power_supply") or {}).get(field)
    return card.get(field)


def check_turn(query: str, response: dict, debug: dict, expect: dict) -> list[Result]:
    products = _parts(response["products"])
    alternatives = _parts(response["alternatives"])
    answer = response["answer"]
    lowered = answer.lower()
    results: list[Result] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        results.append((name, passed, "" if passed else detail))

    # Always on.
    leaked = [n for n in INTERNAL_NAMES if n.lower() in lowered]
    add("no_internals", not leaked, f"answer mentions {leaked}")
    number_check = (debug.get("number_check") or {}).get("status")
    add("numbers_supported", number_check != "fallback", f"number check: {number_check}")
    rejected = debug.get("rejected_refs") or []
    add("no_invented_parts", not rejected, f"rejected part numbers: {rejected}")

    language = expect.get("language", language_of(query))
    if language != "any":
        add("language", language_of(answer) == language, f"expected {language}: {answer[:80]}")

    if "status" in expect:
        allowed = expect["status"] if isinstance(expect["status"], list) else [expect["status"]]
        add("status", response["status"] in allowed, f"got {response['status']}, want {allowed}")
    if "view" in expect:
        add("view", response["view"] == expect["view"], f"got {response['view']}")
    if "products_exactly" in expect:
        want = expect["products_exactly"]
        add("products_exactly", products == want, f"got {products}, want {want}")
    if "products_include" in expect:
        missing = [p for p in expect["products_include"] if p not in products]
        add("products_include", not missing, f"missing {missing}; got {products}")
    if "products_exclude" in expect:
        present = [p for p in expect["products_exclude"] if p in products]
        add("products_exclude", not present, f"should not show {present}")
    if "products_min" in expect:
        n = expect["products_min"]
        add("products_min", len(products) >= n, f"{len(products)} products, want >= {n}")
    if "products_max" in expect:
        n = expect["products_max"]
        add("products_max", len(products) <= n, f"{len(products)} products, want <= {n}")
    if "products_where" in expect:
        wrong = [
            f"{c['part_number']}.{field}={_card_value(c, field)}"
            for c in response["products"]
            for field, value in expect["products_where"].items()
            if _card_value(c, field) != value
        ]
        add("products_where", not wrong, f"products not matching: {wrong}")
    if "alternatives_include" in expect:
        missing = [p for p in expect["alternatives_include"] if p not in alternatives]
        add("alternatives_include", not missing, f"missing {missing}; got {alternatives}")
    if "alternatives_max" in expect:
        n = expect["alternatives_max"]
        add("alternatives_max", len(alternatives) <= n, f"{len(alternatives)} alternatives")
    if "quick_replies_min" in expect:
        n = expect["quick_replies_min"]
        got = len(response["quick_replies"])
        add("quick_replies_min", got >= n, f"{got} quick replies, want >= {n}")
    if "answer_any" in expect:
        options = expect["answer_any"]
        hit = any(o.lower() in lowered for o in options)
        add("answer_any", hit, f"none of {options} in: {answer[:120]}")
    if "answer_none" in expect:
        found = [o for o in expect["answer_none"] if o.lower() in lowered]
        add("answer_none", not found, f"answer contains {found}")
    if "tools_called" in expect:
        called = [s["tool"] for s in debug.get("steps", [])]
        missing = [t for t in expect["tools_called"] if t not in called]
        add("tools_called", not missing, f"missing {missing}; called {called}")
    return results
