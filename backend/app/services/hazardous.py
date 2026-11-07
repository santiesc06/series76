"""Hazardous-area suitability (decisions D-2b, D-2c).

The marking VALUES come from the data PDF (stored per table in `catalog_tables.hazardous`).
The RULES below are INTERPRETATION following NEC 500/505 and IEC 60079 marking conventions; the
datasheet does not state them. They are deliberately conservative: anything the markings do not
explicitly cover is reported as "not covered", never as suitable.
"""

from typing import Literal

IecGasGroup = Literal["IIA", "IIB", "IIC"]
NecGasGroup = Literal["A", "B", "C", "D"]
GasGroup = Literal["IIA", "IIB", "IIC", "A", "B", "C", "D"]

# INTERPRETATION: an IEC gas group marking covers itself and the less demanding groups.
_IEC_ORDER = ["IIA", "IIB", "IIC"]


def check(
    hazardous: dict | None,
    *,
    zone: int | None = None,
    division: int | None = None,
    gas_group: str | None = None,
    dust: bool = False,
) -> list[str]:
    """Return why a table's markings do NOT cover the requested area (empty list = covered)."""
    if hazardous is None:
        return ["not rated for hazardous locations (weatherproof enclosure)"]
    problems: list[str] = []
    marked_zone = hazardous.get("zone")
    if zone is not None and (marked_zone is None or zone < marked_zone):
        # INTERPRETATION: Zone 1 equipment (EPL Gb) is acceptable in Zone 1 and Zone 2, not Zone 0.
        problems.append(f"marked for Zone {marked_zone}; Zone {zone} is not covered")
    marked_division = hazardous.get("division")
    if division is not None and (marked_division is None or division < marked_division):
        problems.append(f"marked for Division {marked_division}; Division {division} not covered")
    if gas_group is not None:
        group = gas_group.strip().upper()
        if group in _IEC_ORDER:
            marked = hazardous.get("iec_gas_group")
            if marked not in _IEC_ORDER or _IEC_ORDER.index(group) > _IEC_ORDER.index(marked):
                problems.append(f"marked for gas group {marked}; group {group} is not covered")
        elif group not in (hazardous.get("nec_gas_groups") or []):
            marked = ", ".join(hazardous.get("nec_gas_groups") or [])
            problems.append(f"marked for NEC Groups {marked}; Group {group} is not covered")
    if dust and not hazardous.get("dust_rated"):
        problems.append("no combustible dust marking is listed (gas only)")
    return problems
