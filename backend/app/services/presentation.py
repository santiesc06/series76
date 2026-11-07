"""Product cards for the app, built from database rows only (design §4.1, NFR-01).

Server-driven specs: labels, units, grouping and order come from here, so the app renders any
product generically and builds comparison tables from the same structure.
"""

from app.db.models import Part, Rating
from app.services.catalog import certifications_of, part_notes, power_supply_label

SERVICE_TITLES = {
    "on_off": "On/Off service",
    "modulating": "Modulating service",
    "both": "On/Off and Modulating service",
}
# search filter -> spec key highlighted on the cards
FILTER_HIGHLIGHTS = {
    "min_torque": "torque",
    "max_speed_s": "speed",
    "min_duty_cycle_pct": "duty_cycle",
    "min_cycles_per_hour": "cycles_per_hour",
    "min_starts_per_hour": "starts_per_hour",
    "max_fla_a": "fla",
    "max_motor_power_w": "motor_power",
}


def _value(value: float | None, unit: str, condition: str | None = None) -> dict:
    item: dict = {"value": value, "unit": unit}
    if condition:
        item["condition"] = condition
    return item


def _spec(key: str, label: str, values: list[dict]) -> dict:
    return {"key": key, "label": label, "values": values}


def _rating_group(r: Rating) -> dict:
    specs = [
        _spec("torque", "Output torque",
              [_value(r.torque_inlb, "in-lbs"), _value(r.torque_nm, "Nm")]),
        _spec("duty_cycle", "Duty cycle (S4)", [_value(r.duty_cycle_pct, "%")]),
    ]  # fmt: skip
    if r.cycles_per_hour is not None:
        specs.append(_spec("cycles_per_hour", "Cycles per hour",
                           [_value(r.cycles_per_hour, "cycles/h")]))  # fmt: skip
    if r.starts_per_hour is not None:
        specs.append(_spec("starts_per_hour", "Starts per hour",
                           [_value(r.starts_per_hour, "starts/h")]))  # fmt: skip
    return {"key": r.service, "title": SERVICE_TITLES[r.service], "specs": specs}


def _per_frequency(part: Part, attr: str, unit: str) -> list[dict]:
    if not part.table.frequency_dependent:
        return [_value(getattr(part, f"{attr}_60hz"), unit)]
    return [
        _value(getattr(part, f"{attr}_60hz"), unit, "60 Hz"),
        _value(getattr(part, f"{attr}_50hz"), unit, "50 Hz"),
    ]


def _electrical_group(part: Part) -> dict:
    return {
        "key": "electrical",
        "title": "Electrical",
        "specs": [
            _spec("speed", "Operating speed (90°)", _per_frequency(part, "speed_s", "s")),
            _spec("fla", "Full load current", _per_frequency(part, "fla_a", "A")),
            _spec("lra", "Locked rotor current", _per_frequency(part, "lra_a", "A")),
            _spec("motor_power", "Motor power", [_value(part.motor_power_w, "W")]),
        ],
    }


def product_card(
    part: Part, highlight: list[str] | None = None, match_note: str | None = None
) -> dict:
    table = part.table
    card = {
        "part_number": part.part_number,
        "model_code": part.model_code,
        "enclosure": table.enclosure,
        "power_supply": {
            "label": power_supply_label(table),
            "voltage": table.voltage,
            "phase": table.phase,
            "current_type": table.current_type,
        },
        "certifications": certifications_of(part),
        "hazardous_markings": table.markings,
        "data_available": part.data_available,
        "notes": part_notes(part) if part.data_available else [
            "Listed in the catalog as N/A: no electrical data is published."
        ],
        "highlight": highlight or [],
        "spec_groups": [],
    }  # fmt: skip
    if match_note:
        card["match_note"] = match_note
    if part.data_available:
        card["spec_groups"] = [_rating_group(r) for r in part.ratings] + [_electrical_group(part)]
    return card


def highlights_for(filters: dict | None) -> list[str]:
    return [FILTER_HIGHLIGHTS[k] for k in (filters or {}) if k in FILTER_HIGHLIGHTS]
