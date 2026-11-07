"""Checks on the committed, verified dataset (data/processed/actuators.json).

The spot values below were read directly from the PDF, independently of the extraction models,
and cover every table and every layout.
"""

import json

import pytest

from ingest import paths
from ingest.validate import validate


@pytest.fixture(scope="module")
def dataset() -> dict:
    if not paths.PROCESSED.exists():
        pytest.skip("data/processed/actuators.json not built yet (run python -m ingest build)")
    return json.loads(paths.PROCESSED.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def parts(dataset) -> dict[str, dict]:
    return {p["part_number"]: p for p in dataset["parts"]}


def _rating(part: dict, service: str) -> dict:
    return next(r for r in part["ratings"] if r["service"] == service)


def test_dataset_passes_all_validation_rules(dataset):
    assert validate(dataset) == []


def test_part_counts(dataset):
    assert len(dataset["parts"]) == 68
    assert sum(not p["data_available"] for p in dataset["parts"]) == 4


# (part number, service, torque in-lbs, torque Nm, duty cycle %, cycles/h, starts/h)
RATINGS = [
    ("763B00-11300000/A", "on_off", 4400, 500, 30, 16, None),
    ("763B00-11300000/A", "modulating", 3350, 380, 40, None, 960),
    ("765B00-11300000/A", "on_off", 26500, 3000, 25, 3, None),
    ("761A00-11320000/A", "on_off", 700, 80, 40, 36, None),
    ("767C00-11320000/A", "on_off", 79700, 9000, 40, 6, None),
    ("767C00-11320000/A", "modulating", 79650, 9000, 40, None, 960),
    ("763A00-11330C00/A", "both", 2650, 300, 70, 39, 1200),
    ("765A00-11330C00/A", "both", 17700, 2000, 50, 8, 1200),
    ("761X30-11380000/A", "on_off", 620, 70, 30, 350, None),
    ("763X30-11370000/A", "modulating", 1900, 220, 35, None, 840),
    ("762Y30-11300000/A", "on_off", 1770, 200, 70, 100, None),
    ("762Y30-11300000/A", "modulating", 1360, 160, 40, None, 960),
    ("765X30-11320000/A", "modulating", 14000, 1600, 30, None, 720),
    ("765Y30-11320000/A", "on_off", 25900, 3000, 30, 50, None),
    ("765Y30-11320000/A", "modulating", 20720, 2400, 30, None, 720),
    ("764Y30-11320000/A", "on_off", 8300, 940, 30, 140, None),
]


@pytest.mark.parametrize(("pn", "service", "inlb", "nm", "duty", "cycles", "starts"), RATINGS)
def test_rating_spot_values(parts, pn, service, inlb, nm, duty, cycles, starts):
    r = _rating(parts[pn], service)
    assert (r["torque_inlb"], r["torque_nm"], r["duty_cycle_pct"]) == (inlb, nm, duty)
    assert (r["cycles_per_hour"], r["starts_per_hour"]) == (cycles, starts)


# (part number, speed 60/50 Hz, FLA 60/50 Hz, LRA 60/50 Hz, motor power W)
ELECTRICAL = [
    ("763B00-11300000/A", (26, 32), (4.8, 4.6), (5.0, 4.9), 90),
    ("765B00-11300000/A", (108, 130), (7.0, 7.0), (7.3, 7.4), 180),
    ("761A00-11320000/A", (17, 20), (0.7, 0.7), (0.7, 0.7), 15),
    ("767C00-11320000/A", (99, 117), (9.0, 9.0), (17.0, 17.0), 700),
    ("765A00-11330C00/A", (88, 105), (3.4, 3.4), (4.0, 4.0), 180),
    ("761X30-11380000/A", (17, 17), (5.0, 5.0), (12.8, 12.8), 40),
    ("763X30-11370000/A", (32, 32), (8.9, 8.9), (30.8, 30.8), 40),
]


@pytest.mark.parametrize(("pn", "speed", "fla", "lra", "power"), ELECTRICAL)
def test_electrical_spot_values(parts, pn, speed, fla, lra, power):
    p = parts[pn]
    assert (p["speed_s_60hz"], p["speed_s_50hz"]) == speed
    assert (p["fla_a_60hz"], p["fla_a_50hz"]) == fla
    assert (p["lra_a_60hz"], p["lra_a_50hz"]) == lra
    assert p["motor_power_w"] == power


@pytest.mark.parametrize(
    "pn", ["761A00-11330C00/A", "761B00-11330C00/A", "762A00-11330C00/A", "762B00-11330C00/A"]
)
def test_na_parts_exist_without_data(parts, pn):
    assert parts[pn]["data_available"] is False
    assert parts[pn]["ratings"] == []


def test_csa_footnote_applies_only_to_sizes_6_and_7(parts):
    not_csa = sorted(pn for pn, p in parts.items() if not p["csa_certified"])
    assert not_csa == [
        "766A00-11320000/A", "766B00-11320000/A", "767A00-11320000/A",
        "767B00-11320000/A", "767C00-11320000/A",
    ]  # fmt: skip


def test_summary_example_part_number_is_not_in_the_data(parts):
    assert "761A00-11380000/A" not in parts  # used as the "invalid part number" case (US-03)
