"""LangChain tools: thin wrappers over app/services/catalog.py (design B2).

Tools are built per request, bound to that request's DB session and to a ToolRecorder that keeps
every call (name, arguments, result, duration) for the debug screen and the number check.
"""

import time
from dataclasses import dataclass, field

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services import catalog


@dataclass
class ToolCall:
    tool: str
    args: dict
    result: dict
    duration_ms: int
    error: str | None = None


@dataclass
class ToolRecorder:
    calls: list[ToolCall] = field(default_factory=list)

    def run(self, name: str, args: dict, fn) -> dict:
        started = time.perf_counter()
        error = None
        try:
            result = fn()
        except Exception as exc:  # a tool failure must not crash the turn; the agent is told
            error = f"{type(exc).__name__}: {exc}"
            result = {"status": "error", "message": "The catalog could not be queried."}
        duration = int((time.perf_counter() - started) * 1000)
        self.calls.append(ToolCall(name, args, result, duration, error))
        return result


class LookupArgs(BaseModel):
    part_number: str = Field(description="Full or partial Base Part Number, as the user wrote it.")


def build_tools(db: Session, recorder: ToolRecorder) -> list[StructuredTool]:
    def lookup_part(part_number: str) -> dict:
        args = {"part_number": part_number}
        return recorder.run("lookup_part", args, lambda: catalog.lookup_part(db, part_number))

    def search_actuators(**filters) -> dict:
        parsed = catalog.SearchFilters(**filters)
        args = parsed.model_dump(exclude_defaults=True)
        return recorder.run(
            "search_actuators",
            args,
            lambda: catalog.search_actuators(db, parsed, require_power_supply=True),
        )

    def catalog_overview() -> dict:
        return recorder.run("catalog_overview", {}, lambda: catalog.catalog_overview(db))

    return [
        StructuredTool.from_function(
            lookup_part,
            name="lookup_part",
            description="Get the technical data of one Series 76 actuator by its Base Part "
            "Number (full or partial). Returns found / ambiguous / no_data / not_found.",
            args_schema=LookupArgs,
        ),
        StructuredTool.from_function(
            search_actuators,
            name="search_actuators",
            description="Find actuators that meet requirements (enclosure, supply, service, "
            "torque, speed, duty cycle, current, certification, hazardous area). Returns ranked "
            "matches, the failing requirement and the closest alternatives, or "
            "power_supply_needed when the voltage is missing.",
            args_schema=catalog.SearchFilters,
        ),
        StructuredTool.from_function(
            catalog_overview,
            name="catalog_overview",
            description="Summary of what the catalog contains: enclosures, power supplies, "
            "services and torque ranges. Use it to ask good clarifying questions.",
        ),
    ]
