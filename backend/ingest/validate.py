"""Consistency rules for the canonical dataset. Used by `ingest build` and by tests/test_data.py.

Each rule catches a typical transcription error (a misread or swapped digit) without needing to
know the right value.
"""

from ingest.normalize import PART_NUMBER_RE

INLB_TO_NM = 0.112985
TORQUE_TOLERANCE = 0.05  # the PDF rounds Nm, e.g. 700 in-lbs is printed as 80 Nm
ELECTRICAL = [
    "speed_s_60hz",
    "speed_s_50hz",
    "fla_a_60hz",
    "fla_a_50hz",
    "lra_a_60hz",
    "lra_a_50hz",
]
RATING_REQUIRED = ["torque_inlb", "torque_nm", "duty_cycle_pct"]


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def validate(dataset: dict) -> list[str]:
    errors: list[str] = []
    tables = {t["code"]: t for t in dataset["tables"]}
    seen: set[str] = set()

    for code, table in tables.items():
        rows = [p for p in dataset["parts"] if p["table_code"] == code]
        if len(rows) != table["expected_rows"]:
            errors.append(f"{code}: {len(rows)} rows, expected {table['expected_rows']}")
        previous_power = previous_torque = None
        for part in rows:
            pn = part["part_number"]
            where = f"{code} {pn}"
            if not PART_NUMBER_RE.match(pn):
                errors.append(f"{where}: part number does not match the expected pattern")
            if pn in seen:
                errors.append(f"{where}: duplicate part number")
            seen.add(pn)
            if not part["data_available"]:
                if part["ratings"] or any(
                    part[k] is not None for k in [*ELECTRICAL, "motor_power_w"]
                ):
                    errors.append(f"{where}: marked N/A but has values")
                continue

            for key in [*ELECTRICAL, "motor_power_w"]:
                if not _is_number(part[key]) or part[key] <= 0:
                    errors.append(f"{where}: {key} must be a positive number, got {part[key]!r}")
            if not part["ratings"]:
                errors.append(f"{where}: no ratings")
            for rating in part["ratings"]:
                r_where = f"{where} [{rating['service']}]"
                for key in RATING_REQUIRED:
                    if not _is_number(rating[key]) or rating[key] <= 0:
                        errors.append(f"{r_where}: {key} must be a positive number")
                if _is_number(rating["torque_inlb"]) and _is_number(rating["torque_nm"]):
                    expected = rating["torque_inlb"] * INLB_TO_NM
                    if abs(rating["torque_nm"] - expected) > TORQUE_TOLERANCE * expected:
                        errors.append(
                            f"{r_where}: {rating['torque_inlb']} in-lbs vs "
                            f"{rating['torque_nm']} Nm "
                            f"(expected about {expected:.0f} Nm)"
                        )
                if _is_number(rating["duty_cycle_pct"]) and not 0 < rating["duty_cycle_pct"] <= 100:
                    errors.append(f"{r_where}: duty cycle out of range")
                if rating["cycles_per_hour"] is None and rating["starts_per_hour"] is None:
                    errors.append(f"{r_where}: needs cycles per hour or starts per hour")

            if all(_is_number(part[k]) for k in ELECTRICAL):
                for hz in ("60hz", "50hz"):
                    if part[f"lra_a_{hz}"] < part[f"fla_a_{hz}"]:
                        errors.append(f"{where}: LRA < FLA at {hz}")
                if table["frequency_dependent"] and part["speed_s_50hz"] < part["speed_s_60hz"]:
                    errors.append(f"{where}: 50 Hz speed faster than 60 Hz speed")

            # Rows are printed in size order, so power and torque never decrease down a table.
            power = part["motor_power_w"]
            if _is_number(power) and previous_power is not None and power < previous_power:
                errors.append(f"{where}: motor power {power} W lower than the row above")
            previous_power = power if _is_number(power) else previous_power
            torque = max(
                (r["torque_inlb"] for r in part["ratings"] if _is_number(r["torque_inlb"])),
                default=None,
            )
            if torque is not None and previous_torque is not None and torque < previous_torque:
                errors.append(f"{where}: torque {torque} in-lbs lower than the row above")
            previous_torque = torque if torque is not None else previous_torque

    return errors
