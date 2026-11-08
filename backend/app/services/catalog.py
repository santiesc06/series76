"""Catalog queries behind the agent's tools (design §3.1). Plain functions, no LLM.

- lookup_part:        a full or partial Base Part Number -> found / ambiguous / no_data / not_found
- search_actuators:   requirements -> ranked matches, or the failing constraints + alternatives
- catalog_overview:   what exists (power supplies, enclosures, torque ranges) for clarifications

The catalog is small (68 parts, 111 ratings), so it is loaded from PostgreSQL in one query and
requirements are evaluated as named predicates in Python. That makes "which requirement failed"
exact and testable (US-10). For a catalog of many thousands of rows the same predicates would
move into SQL WHERE clauses.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import CatalogTable, Part, Rating
from app.services import hazardous
from ingest.normalize import match_key

MAX_RESULTS = 5
MAX_ALTERNATIVES = 3
MAX_SUGGESTIONS = 5
PARTIAL_MAX_LENGTH = 6  # model code + enclosure digits, e.g. 761A00 / 763X30
VOLTAGE_TOLERANCE = 0.10  # PDF notes: "Allowable motor voltage tolerance: +/- 10%" (D-4)

THREE_PHASE_NOTE = (
    "The 3-phase table gives one rating for both On/Off and Modulating service "
    "(it does not split by service)."
)
CSA_FOOTNOTE = "Sizes 6 and 7 are not CSA Certified (table footnote)."
DC_NOTE = "24V values do not depend on supply frequency (the 24V tables have one value)."


# --------------------------------------------------------------------------- loading & shaping


def _all_parts(db: Session) -> list[Part]:
    stmt = (
        select(Part)
        .join(Part.table)
        .options(selectinload(Part.ratings), selectinload(Part.table))
        .order_by(CatalogTable.page, CatalogTable.code, Part.position)
    )
    return list(db.scalars(stmt))


def power_supply_label(table: CatalogTable) -> str:
    if table.voltage == 24:
        return "24V AC/DC" if table.current_type == "ac_dc" else "24V DC"
    return f"{table.voltage}V {'three' if table.phase == 'three' else 'single'} phase"


def certifications_of(part: Part) -> list[str]:
    return [c for c in part.table.certifications if c != "CSA" or part.csa_certified]


def part_identity(part: Part) -> dict:
    return {
        "part_number": part.part_number,
        "enclosure": part.table.enclosure,
        "power_supply": power_supply_label(part.table),
        "data_available": part.data_available,
    }


def _rating_dict(r: Rating) -> dict:
    return {
        "service": r.service,
        "torque_inlb": r.torque_inlb,
        "torque_nm": r.torque_nm,
        "duty_cycle_pct": r.duty_cycle_pct,
        "cycles_per_hour": r.cycles_per_hour,
        "starts_per_hour": r.starts_per_hour,
    }


def _electrical(part: Part) -> dict:
    if part.table.frequency_dependent:
        return {
            "speed_s": {"60_hz": part.speed_s_60hz, "50_hz": part.speed_s_50hz},
            "fla_a": {"60_hz": part.fla_a_60hz, "50_hz": part.fla_a_50hz},
            "lra_a": {"60_hz": part.lra_a_60hz, "50_hz": part.lra_a_50hz},
            "motor_power_w": part.motor_power_w,
        }
    return {
        "speed_s": part.speed_s_60hz,
        "fla_a": part.fla_a_60hz,
        "lra_a": part.lra_a_60hz,
        "motor_power_w": part.motor_power_w,
    }


def part_notes(part: Part) -> list[str]:
    notes = []
    if not part.table.service_split:
        notes.append(THREE_PHASE_NOTE)
    if not part.csa_certified and "CSA" in part.table.certifications:
        notes.append(CSA_FOOTNOTE)
    if not part.table.frequency_dependent:
        notes.append(DC_NOTE)
    return notes


def part_detail(part: Part) -> dict:
    """Everything the catalog knows about one part (also used to build product cards)."""
    table = part.table
    detail = {
        **part_identity(part),
        "model_code": part.model_code,
        "size": part.size,
        "power_supply_detail": {
            "voltage": table.voltage,
            "phase": table.phase,
            "current_type": table.current_type,
        },
        "certifications": certifications_of(part),
        "csa_certified": part.csa_certified,
        "hazardous_markings": table.markings,
        "frequency_dependent": table.frequency_dependent,
        "source": {"page": table.page, "table": f"{table.enclosure} {table.title}"},
    }
    if table.summary_claim:
        detail["certification_note"] = table.summary_claim
    if part.data_available:
        detail["electrical"] = _electrical(part)
        detail["ratings"] = [_rating_dict(r) for r in part.ratings]
        detail["notes"] = part_notes(part)
    else:
        detail["notes"] = ["Listed in the catalog as N/A: no electrical data is published."]
    return detail


# --------------------------------------------------------------------------- lookup


def _levenshtein(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _found(part: Part, parts: list[Part], matched_from: str | None = None) -> dict:
    result: dict = {"status": "found" if part.data_available else "no_data"}
    if matched_from:
        result["matched_from_partial_input"] = matched_from
    result["part"] = part_detail(part)
    # "The same model at 220V / three phase" is then one exact lookup, not a truncated search.
    siblings = [p for p in parts if p.model_code == part.model_code and p is not part]
    if siblings:
        result["same_model_other_power_supplies"] = [part_identity(p) for p in siblings]
    return result


def lookup_part(db: Session, query: str) -> dict:
    """Find one actuator by its Base Part Number (full or partial, any case or spacing)."""
    key = match_key(query or "")
    # Series 76 part numbers start with "7" + a digit and are mostly digits (763B00-11300000/A).
    if not re.match(r"^7\d", key) or len(re.sub(r"[^0-9]", "", key)) < 3:
        return {
            "status": "invalid_input",
            "message": "Not a recognizable part number. Series 76 part numbers look like "
            "763B00-11300000/A.",
        }
    parts = _all_parts(db)
    for part in parts:
        if part.match_key == key:
            return _found(part, parts)

    # Prefix matching only for genuinely short input (a model code like "761A" or "761A00").
    # A full-length number with a typo must not be silently resolved to a "close" part (US-03).
    prefixed = (
        [p for p in parts if p.match_key.startswith(key)] if len(key) <= PARTIAL_MAX_LENGTH else []
    )
    if len(prefixed) == 1:
        return _found(prefixed[0], parts, matched_from=query)
    if prefixed:
        return {
            "status": "ambiguous",
            "message": f"'{query}' matches {len(prefixed)} part numbers; ask which one.",
            "candidates": [part_identity(p) for p in prefixed],
        }

    def score(part: Part) -> tuple:
        # Closest by edit distance; ties prefer the same power/service code, then the same model.
        return (
            _levenshtein(key, part.match_key),
            part.match_key[6:] != key[6:],
            part.match_key[:4] != key[:4],
        )

    ranked = sorted(parts, key=score)[:MAX_SUGGESTIONS]
    return {
        "status": "not_found",
        "message": f"'{query}' is not a Series 76 part number in the catalog.",
        "suggestions": [part_identity(p) for p in ranked],
    }


# --------------------------------------------------------------------------- search


class SearchFilters(BaseModel):
    """Requirements for recommending actuators. Every field is optional; leave unknowns empty."""

    enclosure: Literal["weatherproof", "explosionproof"] | None = Field(
        None, description="Weatherproof (general use) or explosionproof (hazardous locations)."
    )
    voltage: float | None = Field(
        None, gt=0, description="Nominal supply voltage, e.g. 24, 110, 120, 220, 230."
    )
    phase: Literal["single", "three"] | None = Field(None, description="AC supply phases.")
    current_type: Literal["ac", "dc"] | None = Field(None, description="AC or DC supply.")
    service: Literal["on_off", "modulating"] | None = Field(
        None, description="On/Off (open/close) or Modulating (positioning) service."
    )
    min_torque: float | None = Field(None, gt=0, description="Minimum output torque.")
    torque_unit: Literal["Nm", "in-lbs"] = Field("Nm", description="Unit of min_torque.")
    max_speed_s: float | None = Field(
        None, gt=0, description="Maximum time in seconds for a 90° turn (lower is faster)."
    )
    frequency_hz: Literal[50, 60] | None = Field(
        None, description="Supply frequency for speed and current. If empty, 60 Hz is used."
    )
    min_duty_cycle_pct: float | None = Field(None, gt=0, le=100)
    min_cycles_per_hour: float | None = Field(None, gt=0, description="On/Off cycles per hour.")
    min_starts_per_hour: float | None = Field(None, gt=0, description="Modulating starts/hour.")
    max_fla_a: float | None = Field(None, gt=0, description="Maximum full load current (A).")
    max_motor_power_w: float | None = Field(None, gt=0, description="Maximum motor power (W).")
    csa_required: bool = Field(False, description="Only CSA certified models.")
    hazardous_zone: Literal[0, 1, 2] | None = Field(None, description="IEC/NEC zone (gas).")
    hazardous_division: Literal[1, 2] | None = Field(None, description="NEC Class I division.")
    gas_group: hazardous.GasGroup | None = Field(
        None, description="IEC group IIA/IIB/IIC or NEC group A/B/C/D of the gas present."
    )
    dust_hazard: bool = Field(False, description="Combustible dust is present.")
    sort_by: Literal["torque", "speed", "current", "power"] = Field(
        "torque",
        description="torque: smallest model that meets the torque first (right-sizing); "
        "speed: fastest first; current: lowest FLA first; power: lowest motor power first.",
    )
    limit: int = Field(MAX_RESULTS, ge=1, le=MAX_RESULTS)


@dataclass(frozen=True)
class Constraint:
    key: str
    label: str  # human-readable, e.g. "torque ≥ 2000 Nm"
    test: Callable[[Part, Rating], bool]
    metric: Callable[[Part, Rating], float | None] | None = None
    direction: Literal["min", "max"] | None = None


def _freq(f: SearchFilters) -> int:
    return f.frequency_hz or 60


def _speed(part: Part, hz: int) -> float | None:
    return part.speed_s_60hz if hz == 60 else part.speed_s_50hz


def _fla(part: Part, hz: int) -> float | None:
    return part.fla_a_60hz if hz == 60 else part.fla_a_50hz


def _voltage_ok(requested: float, table_voltage: int) -> bool:
    return abs(requested - table_voltage) <= VOLTAGE_TOLERANCE * table_voltage


def _constraints(f: SearchFilters) -> list[Constraint]:
    hz = _freq(f)
    c: list[Constraint] = []
    if f.enclosure:
        c.append(Constraint("enclosure", f"{f.enclosure} enclosure",
                            lambda p, r: p.table.enclosure == f.enclosure))  # fmt: skip
    if f.voltage is not None:
        c.append(Constraint("voltage", f"{f.voltage:g}V supply (±10%)",
                            lambda p, r: _voltage_ok(f.voltage, p.table.voltage)))  # fmt: skip
    if f.phase:
        c.append(Constraint("phase", f"{f.phase} phase", lambda p, r: p.table.phase == f.phase))
    if f.current_type:
        allowed = {f.current_type, "ac_dc"}
        c.append(Constraint("current_type", f"{f.current_type.upper()} supply",
                            lambda p, r: p.table.current_type in allowed))  # fmt: skip
    if f.service:
        c.append(Constraint("service", f"{f.service.replace('_', '/')} service",
                            lambda p, r: r.service in (f.service, "both")))  # fmt: skip
    if f.min_torque is not None:

        def torque(p: Part, r: Rating) -> float:
            return r.torque_nm if f.torque_unit == "Nm" else r.torque_inlb

        c.append(Constraint("min_torque", f"torque ≥ {f.min_torque:g} {f.torque_unit}",
                            lambda p, r: torque(p, r) >= f.min_torque, torque, "min"))  # fmt: skip
    if f.max_speed_s is not None:
        c.append(Constraint("max_speed_s", f"operating speed ≤ {f.max_speed_s:g} s at {hz} Hz",
                            lambda p, r: (_speed(p, hz) or 1e9) <= f.max_speed_s,
                            lambda p, r: _speed(p, hz), "max"))  # fmt: skip
    if f.min_duty_cycle_pct is not None:
        c.append(Constraint("min_duty_cycle_pct", f"duty cycle ≥ {f.min_duty_cycle_pct:g}%",
                            lambda p, r: r.duty_cycle_pct >= f.min_duty_cycle_pct,
                            lambda p, r: r.duty_cycle_pct, "min"))  # fmt: skip
    if f.min_cycles_per_hour is not None:
        c.append(Constraint("min_cycles_per_hour", f"≥ {f.min_cycles_per_hour:g} cycles/hour",
                            lambda p, r: (r.cycles_per_hour or 0) >= f.min_cycles_per_hour,
                            lambda p, r: r.cycles_per_hour, "min"))  # fmt: skip
    if f.min_starts_per_hour is not None:
        c.append(Constraint("min_starts_per_hour", f"≥ {f.min_starts_per_hour:g} starts/hour",
                            lambda p, r: (r.starts_per_hour or 0) >= f.min_starts_per_hour,
                            lambda p, r: r.starts_per_hour, "min"))  # fmt: skip
    if f.max_fla_a is not None:
        c.append(Constraint("max_fla_a", f"full load current ≤ {f.max_fla_a:g} A at {hz} Hz",
                            lambda p, r: (_fla(p, hz) or 1e9) <= f.max_fla_a,
                            lambda p, r: _fla(p, hz), "max"))  # fmt: skip
    if f.max_motor_power_w is not None:
        c.append(Constraint("max_motor_power_w", f"motor power ≤ {f.max_motor_power_w:g} W",
                            lambda p, r: (p.motor_power_w or 1e9) <= f.max_motor_power_w,
                            lambda p, r: p.motor_power_w, "max"))  # fmt: skip
    if f.csa_required:
        c.append(Constraint("csa_required", "CSA certified", lambda p, r: p.csa_certified))
    if (
        f.hazardous_zone is not None
        or f.hazardous_division is not None
        or f.gas_group
        or f.dust_hazard
    ):
        parts = [
            f"Zone {f.hazardous_zone}" if f.hazardous_zone is not None else "",
            f"Division {f.hazardous_division}" if f.hazardous_division is not None else "",
            f"gas group {f.gas_group}" if f.gas_group else "",
            "combustible dust" if f.dust_hazard else "",
        ]
        label = "hazardous area: " + ", ".join(x for x in parts if x)
        c.append(Constraint("hazardous_area", label, lambda p, r: not hazardous.check(
            p.table.hazardous, zone=f.hazardous_zone, division=f.hazardous_division,
            gas_group=f.gas_group, dust=f.dust_hazard)))  # fmt: skip
    return c


def _sort_value(f: SearchFilters, part: Part, ratings: list[Rating]) -> float:
    hz = _freq(f)
    if f.sort_by == "speed":
        return _speed(part, hz) or 1e9
    if f.sort_by == "current":
        return _fla(part, hz) or 1e9
    if f.sort_by == "power":
        return part.motor_power_w or 1e9
    unit = "torque_nm" if f.torque_unit == "Nm" else "torque_inlb"
    return min(getattr(r, unit) for r in ratings)


def _result(part: Part, ratings: list[Rating], hz: int) -> dict:
    return {
        **part_identity(part),
        "certifications": certifications_of(part),
        "matched_ratings": [_rating_dict(r) for r in ratings],
        "frequency_hz": hz if part.table.frequency_dependent else None,
        "speed_s": _speed(part, hz),
        "fla_a": _fla(part, hz),
        "motor_power_w": part.motor_power_w,
    }


def _matching(
    candidates: list[tuple[Part, Rating]], constraints: list[Constraint]
) -> dict[str, tuple[Part, list[Rating]]]:
    grouped: dict[str, tuple[Part, list[Rating]]] = {}
    for part, rating in candidates:
        if all(c.test(part, rating) for c in constraints):
            grouped.setdefault(part.part_number, (part, []))[1].append(rating)
    return grouped


def _assumptions(f: SearchFilters, results: list[tuple[Part, list[Rating]]]) -> list[str]:
    notes = []
    if f.voltage is not None:
        mapped = sorted({p.table.voltage for p, _ in results if p.table.voltage != f.voltage})
        if mapped:
            listed = ", ".join(f"{v}V" for v in mapped)
            notes.append(
                f"{f.voltage:g}V was matched to the {listed} models, within the ±10% motor "
                "voltage tolerance stated in the datasheet."
            )
    if f.frequency_hz is None and (f.max_speed_s is not None or f.max_fla_a is not None):
        notes.append("No supply frequency was given; speed and current were compared at 60 Hz.")
    if any(r.service == "both" for _, rs in results for r in rs):
        notes.append(THREE_PHASE_NOTE)
    if any(c.key == "hazardous_area" for c in _constraints(f)):
        notes.append(
            "Hazardous-area suitability is read from the markings listed in the datasheet "
            "(interpreted per NEC/IEC marking conventions). Confirm with the manufacturer."
        )
    return notes


def search_actuators(
    db: Session, filters: SearchFilters, require_power_supply: bool = False
) -> dict:
    """Recommend actuators meeting every requirement, or explain what fails and what is closest.

    With `require_power_supply` (the agent's tool, design B2a), a search without a voltage whose
    matches span several power supplies returns `power_supply_needed` and the supplies that have
    matches, instead of mixing models the user cannot use (US-08 AC1).
    """
    hz = _freq(filters)
    candidates = [(p, r) for p in _all_parts(db) if p.data_available for r in p.ratings]
    constraints = _constraints(filters)
    matches = list(_matching(candidates, constraints).values())

    if matches and require_power_supply and filters.voltage is None:
        supplies: dict[str, int] = {}
        for part, _ in matches:
            label = power_supply_label(part.table)
            supplies[label] = supplies.get(label, 0) + 1
        if len(supplies) > 1:
            return {
                "status": "power_supply_needed",
                "total_matches": len(matches),
                "supplies_with_matches": [
                    {"power_supply": label, "matches": n} for label, n in supplies.items()
                ],
                "requirements": [c.label for c in constraints],
                "message": "Models meet these requirements on several power supplies. Ask which "
                "supply the user has, offering these supplies as quick replies.",
            }

    if matches:
        matches.sort(key=lambda m: _sort_value(filters, m[0], m[1]))
        shown = matches[: filters.limit]
        response = {
            "status": "matches",
            "total_matches": len(matches),
            "results": [_result(p, rs, hz) for p, rs in shown],
            "requirements": [c.label for c in constraints],
            "assumptions": _assumptions(filters, shown),
        }
        if len(matches) > len(shown):
            response["note"] = (
                f"Showing the first {len(shown)} of {len(matches)} matches. Other models also "
                "match: never say a model does not exist because it is not in this list; look it "
                "up by part number instead."
            )
        return response

    response = _explain_no_match(filters, candidates, constraints, hz)
    if any(c.key == "hazardous_area" for c in constraints):
        response["hazardous_note"] = (
            "Explosionproof models are marked: "
            + "; ".join(_explosionproof_markings(db))
            + ". Areas not covered by these markings are not listed as suitable."
        )
    return response


def _safety_constraints(filters: SearchFilters) -> set[str]:
    """Requirements that are never relaxed to produce an alternative."""
    keys = {"hazardous_area"}
    if filters.enclosure == "explosionproof":
        keys.add("enclosure")
    return keys


def _without(constraints: list[Constraint], dropped: Constraint) -> list[Constraint]:
    return [c for c in constraints if c is not dropped]


def _explain_no_match(
    filters: SearchFilters,
    candidates: list[tuple[Part, Rating]],
    constraints: list[Constraint],
    hz: int,
) -> dict:
    """Say which requirement cannot be met and what comes closest (US-10).

    Requirements that define the application (enclosure, supply, service, certification,
    hazardous area) are kept; performance limits (torque, speed, duty cycle, current, power) are
    the ones relaxed to find alternatives. If the application itself does not exist (e.g. a 24V AC
    modulating model), each setting requirement whose removal gives results is reported, with one
    example each.
    """
    setting = [c for c in constraints if c.metric is None]
    performance = [c for c in constraints if c.metric is not None]
    response: dict = {
        "status": "no_match",
        "requirements": [c.label for c in constraints],
        "failing_requirements": [],
        "alternatives": [],
    }

    if _matching(candidates, setting):
        failing = [c for c in performance if _matching(candidates, _without(constraints, c))]
        response["failing_requirements"] = [c.label for c in failing] or [
            c.label for c in performance
        ]
        if len(failing) != 1:
            response["message"] = (
                "No model meets all the performance requirements at once: "
                + "; ".join(response["failing_requirements"])
                + ". Relaxing a single one is not enough."
                if not failing
                else "No model meets all requirements; relaxing any one of these gives results: "
                + "; ".join(response["failing_requirements"])
            )
            return response
        culprit = failing[0]
        options = list(_matching(candidates, _without(constraints, culprit)).values())

        def closeness(m: tuple[Part, list[Rating]]) -> float:
            values = [culprit.metric(m[0], r) or 0 for r in m[1]]
            return -max(values) if culprit.direction == "min" else min(values)

        options.sort(key=closeness)
        response["alternatives"] = [
            _result(p, rs, hz) | {"fails": culprit.label} for p, rs in options[:MAX_ALTERNATIVES]
        ]
        response["message"] = (
            f"No model meets: {culprit.label}. The alternatives are the closest models that meet "
            "every other requirement; they are NOT matches."
        )
        return response

    # The combination of setting requirements does not exist in the catalog.
    failing = [c for c in setting if _matching(candidates, _without(constraints, c))]
    response["failing_requirements"] = [c.label for c in failing] or [c.label for c in setting]
    # Safety: never suggest a model by dropping a hazardous-area or explosionproof requirement.
    relaxable = [c for c in failing if c.key not in _safety_constraints(filters)]
    if not relaxable:
        response["message"] = (
            "No model meets: "
            + "; ".join(response["failing_requirements"])
            + ". This is a safety requirement, so no alternative is suggested."
        )
        return response
    for culprit in relaxable[:MAX_ALTERNATIVES]:
        options = list(_matching(candidates, _without(constraints, culprit)).values())
        options.sort(key=lambda m: _sort_value(filters, m[0], m[1]))
        response["alternatives"].append(_result(*options[0], hz) | {"if_relaxed": culprit.label})
    response["message"] = (
        "The catalog has no model with this combination: "
        + ", ".join(c.label for c in setting)
        + ". Each alternative shows one model available if a single requirement is relaxed; "
        "they are NOT matches."
    )
    return response


def _explosionproof_markings(db: Session) -> list[str]:
    stmt = select(CatalogTable.markings).where(CatalogTable.enclosure == "explosionproof")
    return list(next(iter(db.scalars(stmt)), []))


# --------------------------------------------------------------------------- overview


def catalog_overview(db: Session) -> dict:
    """What the catalog contains, per power supply table, for asking good clarifying questions."""
    tables: dict[str, dict] = {}
    for part in _all_parts(db):
        t = part.table
        entry = tables.setdefault(
            t.code,
            {
                "enclosure": t.enclosure,
                "power_supply": power_supply_label(t),
                "certifications": t.certifications,
                "hazardous_markings": t.markings,
                "parts_with_data": 0,
                "parts_without_data": 0,
                "services": {},
            },
        )
        if not part.data_available:
            entry["parts_without_data"] += 1
            continue
        entry["parts_with_data"] += 1
        for r in part.ratings:
            s = entry["services"].setdefault(
                r.service,
                {
                    "torque_nm": [r.torque_nm, r.torque_nm],
                    "torque_inlb": [r.torque_inlb, r.torque_inlb],
                },
            )
            for unit in ("torque_nm", "torque_inlb"):
                value = getattr(r, unit)
                s[unit] = [min(s[unit][0], value), max(s[unit][1], value)]
    for entry in tables.values():
        for s in entry["services"].values():
            for unit in ("torque_nm", "torque_inlb"):
                s[f"{unit}_range"] = {"min": s[unit][0], "max": s[unit][1]}
                del s[unit]
    return {
        "series": "Series 76 electric actuators",
        "tables": list(tables.values()),
        "notes": [THREE_PHASE_NOTE, CSA_FOOTNOTE],
    }
