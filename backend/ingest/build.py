"""Step 3: apply human resolutions to the merged extraction and write the canonical dataset.

Fails if any conflict is unresolved or any validation rule breaks.
Output: data/processed/actuators.json (committed)
"""

import json
from datetime import UTC, datetime

import yaml

from ingest import paths
from ingest.compare import ASTERISK_FIELD
from ingest.normalize import parse_value
from ingest.validate import validate


def _load_resolutions() -> dict[tuple[str, str, str], object]:
    if not paths.RESOLUTIONS.exists():
        return {}
    data = yaml.safe_load(paths.RESOLUTIONS.read_text(encoding="utf-8")) or {}
    return {
        (r["table"], r["part_number"], r["field"]): r["value"]
        for r in data.get("resolutions") or []
    }


def _rating(service: str, **values) -> dict:
    return {
        "service": service,
        "torque_inlb": values.get("torque_inlb"),
        "torque_nm": values.get("torque_nm"),
        "duty_cycle_pct": values.get("duty_cycle_pct"),
        "cycles_per_hour": values.get("cycles_per_hour"),
        "starts_per_hour": values.get("starts_per_hour"),
    }


def to_part(table: dict, enclosure: dict, part_number: str, marked: bool, v: dict) -> dict:
    """Map one table row (layout-specific keys) to the canonical part structure."""
    # An N/A row has no numbers at all (cells are "N/A" or empty); validation flags partial rows.
    available = any(isinstance(value, int | float) for value in v.values())
    part = {
        "part_number": part_number,
        "model_code": part_number[:4],
        "size": int(part_number[2]),
        "table_code": table["code"],
        "data_available": available,
        "csa_certified": "CSA" in enclosure["certifications"] and not marked,
        "motor_power_w": None,
        "speed_s_60hz": None,
        "speed_s_50hz": None,
        "fla_a_60hz": None,
        "fla_a_50hz": None,
        "lra_a_60hz": None,
        "lra_a_50hz": None,
        "ratings": [],
    }
    if not available:
        return part

    layout = table["layout"]
    part["motor_power_w"] = v["motor_power_w"]
    if layout in ("single_phase", "three_phase"):
        for key in ("speed_s", "fla_a", "lra_a"):
            part[f"{key}_60hz"], part[f"{key}_50hz"] = v[f"{key}_60hz"], v[f"{key}_50hz"]
    else:  # 24V tables: one value, not frequency dependent; stored in both columns (design §2)
        for key in ("speed_s", "fla_a", "lra_a"):
            part[f"{key}_60hz"] = part[f"{key}_50hz"] = v[key]

    if layout == "single_phase":
        part["ratings"] = [
            _rating(
                "on_off",
                torque_inlb=v["onoff_torque_inlb"],
                torque_nm=v["onoff_torque_nm"],
                duty_cycle_pct=v["onoff_duty_cycle_pct"],
                cycles_per_hour=v["onoff_cycles_per_hour"],
            ),
            _rating(
                "modulating",
                torque_inlb=v["mod_torque_inlb"],
                torque_nm=v["mod_torque_nm"],
                duty_cycle_pct=v["mod_duty_cycle_pct"],
                starts_per_hour=v["mod_starts_per_hour"],
            ),
        ]
    elif layout == "three_phase":
        part["ratings"] = [_rating("both", **v)]  # decision D-1
    elif layout == "onoff_only":
        part["ratings"] = [_rating("on_off", **v)]
    else:
        part["ratings"] = [_rating("modulating", **v)]
    return part


def to_table(table: dict, enclosure: dict, common_notes: list[str]) -> dict:
    return {
        "code": table["code"],
        "title": table["title"],
        "page": table["page"],
        "enclosure": table["enclosure"],
        "voltage": table["voltage"],
        "phase": table["phase"],
        "current_type": table["current_type"],
        "frequency_dependent": table["frequency_dependent"],
        "service_split": table["layout"] != "three_phase",
        "layout": table["layout"],
        "expected_rows": table["expected_rows"],
        "certifications": enclosure["certifications"],
        "markings": enclosure["markings"],
        "hazardous": enclosure["hazardous"],
        "summary_claim": enclosure.get("summary_claim"),
        "notes": common_notes,
        "footnotes": [f["text"] for f in table.get("footnotes", [])],
    }


def run() -> None:
    metadata = paths.load_metadata()
    merged = json.loads(paths.MERGED.read_text(encoding="utf-8"))
    resolutions = _load_resolutions()
    unresolved, used = [], set()

    def resolve(code: str, part: str, field: str, current: object) -> object:
        key = (code, part, field)
        if key in resolutions:
            used.add(key)
            value = resolutions[key]
            return value if field == ASTERISK_FIELD else parse_value(value)
        return current

    dataset = {
        "source": paths.PDF.name,
        "built_at": datetime.now(UTC).isoformat(),
        "extraction_models": merged["models"],
        "tables": [],
        "parts": [],
    }
    conflicts = {(c["table"], c["part_number"], c["field"]) for c in merged["conflicts"]}
    for table in metadata["tables"]:
        enclosure = metadata["enclosures"][table["enclosure"]]
        dataset["tables"].append(to_table(table, enclosure, metadata["common_notes"]))
        for row in merged["tables"][table["code"]]:
            part = row["part_number"]
            values = {}
            for field, value in row["values"].items():
                values[field] = resolve(table["code"], part, field, value)
                if (table["code"], part, field) in conflicts and (
                    table["code"],
                    part,
                    field,
                ) not in used:
                    unresolved.append(f"{table['code']} {part} {field}")
            marked = resolve(table["code"], part, ASTERISK_FIELD, row["marked"])
            if marked is None:
                unresolved.append(f"{table['code']} {part} {ASTERISK_FIELD}")
            dataset["parts"].append(to_part(table, enclosure, part, bool(marked), values))

    if unresolved:
        raise SystemExit(
            f"{len(unresolved)} unresolved conflicts. Add them to {paths.RESOLUTIONS}:\n  "
            + "\n  ".join(unresolved)
        )
    stale = set(resolutions) - used
    if stale:
        raise SystemExit(f"Resolutions that match no conflict (typo?): {sorted(stale)}")
    errors = validate(dataset)
    if errors:
        raise SystemExit("Validation failed:\n  " + "\n  ".join(errors))

    paths.PROCESSED.parent.mkdir(parents=True, exist_ok=True)
    paths.PROCESSED.write_text(
        json.dumps(dataset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {len(dataset['parts'])} parts in {len(dataset['tables'])} tables "
        f"to {paths.PROCESSED}"
    )
