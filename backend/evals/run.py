"""Eval runner: the real agent, the real catalog, deterministic checks (design Q2, Q5).

    uv run python -m evals.run                                  # LLM_MODEL from settings
    uv run python -m evals.run --model openai/gpt-oss-120b      # another OpenRouter model
    uv run python -m evals.run --case lookup-basic --case no-match-xp-torque

Calls the LLM (costs money, reads OPENROUTER_API_KEY from .env), so it is run by hand, never in
CI. Each case runs in a transaction that is rolled back, so eval conversations never stay in the
database. Results are written to evals/results/<timestamp>_<model>.json.
"""

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import observability
from app.agent.llm import get_chat_model
from app.agent.runner import AgentError
from app.config import get_settings
from app.services.conversation import handle_turn, message_debug
from evals.checks import check_turn

HERE = Path(__file__).parent
CASES = HERE / "questions.yaml"
MODELS = HERE / "models.yaml"
RESULTS = HERE / "results"


def _configure(model: str | None) -> None:
    """Point the settings at the model under test, with its price for the cost estimate."""
    settings = get_settings()
    if model:
        settings.llm_model = model
    prices = yaml.safe_load(MODELS.read_text(encoding="utf-8")) or {}
    if settings.llm_model in prices:
        settings.llm_price_input_per_m = prices[settings.llm_model]["input"]
        settings.llm_price_output_per_m = prices[settings.llm_model]["output"]
    else:
        print(f"! {settings.llm_model} has no price in models.yaml; using LLM_PRICE_* settings")


def run_case(engine, model, case: dict) -> dict:
    connection = engine.connect()
    transaction = connection.begin()
    db = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")()
    turns, session_id = [], None
    try:
        for turn in case["turns"]:
            record = {"query": turn["query"]}
            try:
                response = handle_turn(
                    db, model, turn["query"], session_id, trace_tags=["eval", case["id"]]
                )
            except AgentError as exc:
                record["error"] = exc.code
                record["error_detail"] = exc.detail  # e.g. which FinalAnswer fields failed (B3a)
                reason = f"agent error: {exc.code}" + (f" ({exc.detail})" if exc.detail else "")
                record["checks"] = [("completed", False, reason)]
                turns.append(record)
                break
            session_id = response["session_id"]
            debug = message_debug(db, response["message_id"], None)
            record.update(
                answer=response["answer"],
                status=response["status"],
                view=response["view"],
                products=[p["part_number"] for p in response["products"]],
                alternatives=[p["part_number"] for p in response["alternatives"]],
                quick_replies=[q["label"] for q in response["quick_replies"]],
                tools=[{"tool": s["tool"], "args": s["args"]} for s in debug["steps"]],
                number_check=debug["number_check"],
                tokens=debug["tokens"],
                cost_usd=debug["estimated_cost_usd"],
                latency_ms=debug["latency_ms"],
                checks=check_turn(turn["query"], response, debug, turn.get("expect", {})),
            )
            turns.append(record)
    finally:
        db.close()
        transaction.rollback()
        connection.close()
    checks = [c for t in turns for c in t["checks"]]
    return {
        "id": case["id"],
        "covers": case.get("covers", []),
        "passed": all(ok for _, ok, _ in checks),
        "checks_passed": sum(ok for _, ok, _ in checks),
        "checks_total": len(checks),
        "cost_usd": round(sum(t.get("cost_usd", 0) for t in turns), 6),
        "turns": turns,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.run")
    parser.add_argument("--model", help="OpenRouter model id (default: LLM_MODEL)")
    parser.add_argument("--case", action="append", help="run only this case id (repeatable)")
    parser.add_argument(
        "--max-cost", type=float, default=1.0, help="stop when the run's cost reaches this (USD)"
    )
    args = parser.parse_args()

    _configure(args.model)
    settings = get_settings()
    print(f"model: {settings.llm_model}")
    print(f"OPENROUTER_API_KEY: {'set' if settings.openrouter_api_key else 'not set'}")
    if not settings.openrouter_api_key:
        sys.exit("Set OPENROUTER_API_KEY in .env to run the evals.")

    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]
    engine = create_engine(settings.database_url)
    model = get_chat_model()

    results, spent, started = [], 0.0, time.perf_counter()
    for case in cases:
        if spent >= args.max_cost:
            print(f"! stopped: estimated cost reached USD {spent:.4f} (--max-cost)")
            break
        result = run_case(engine, model, case)
        results.append(result)
        spent += result["cost_usd"]
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"{mark}  {case['id']:<34} {result['checks_passed']}/{result['checks_total']}"
              f"  USD {result['cost_usd']:.4f}")  # fmt: skip
        for turn in result["turns"]:
            for name, ok, detail in turn["checks"]:
                if not ok:
                    print(f"      - {name}: {detail}")
    observability.flush()

    latencies = [t["latency_ms"] for r in results for t in r["turns"] if "latency_ms" in t]
    summary = {
        "model": settings.llm_model,
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "cases_passed": sum(r["passed"] for r in results),
        "cases_total": len(results),
        "checks_passed": sum(r["checks_passed"] for r in results),
        "checks_total": sum(r["checks_total"] for r in results),
        "cost_usd": round(spent, 4),
        "median_latency_ms": sorted(latencies)[len(latencies) // 2] if latencies else None,
        "wall_time_s": round(time.perf_counter() - started, 1),
    }
    print(
        f"\n{summary['cases_passed']}/{summary['cases_total']} cases, "
        f"{summary['checks_passed']}/{summary['checks_total']} checks, "
        f"USD {summary['cost_usd']}, median latency {summary['median_latency_ms']} ms"
    )
    RESULTS.mkdir(exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9.-]+", "-", settings.llm_model)
    out = RESULTS / f"{datetime.now(UTC):%Y%m%d-%H%M%S}_{slug}.json"
    out.write_text(
        json.dumps(
            {"summary": summary, "cases": results}, indent=2, ensure_ascii=False, default=str
        ),
        encoding="utf-8",
    )
    print(f"results: {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
