"""Unit tests for the ingestion pipeline logic (no LLM, no files)."""

import pytest

from ingest.build import to_part
from ingest.compare import compare_table
from ingest.normalize import NA, clean_part_number, match_key, parse_value
from ingest.validate import validate

WP = {"certifications": ["CSA", "CE", "UKCA"]}
SINGLE = {
    "code": "t",
    "layout": "single_phase",
    "expected_rows": 1,
    "frequency_dependent": True,
    "part_number_suffix": "00-11300000/A",
}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,330", 1330),
        ("0.7", 0.7),
        ("17.0", 17.0),
        ("N/A", NA),
        ("", None),
        (None, None),
        ("x", "x"),
    ],
)
def test_parse_value(raw, expected):
    assert parse_value(raw) == expected


def test_clean_part_number_detects_footnote_marker():
    assert clean_part_number(" 766a00-11320000/A* ") == ("766A00-11320000/A", True)
    assert clean_part_number("761A00-11300000/A") == ("761A00-11300000/A", False)


def test_match_key_ignores_case_separators_and_suffix():
    keys = {match_key(q) for q in ["763b00-11300000", "763B00-11300000/A", "763B00 11300000 A"]}
    assert keys == {"763B0011300000"}
    assert match_key("761A") == "761A"  # partial input keeps its letters


def _row(part, **overrides):
    row = {
        "part_number": part,
        "onoff_torque_inlb": "700", "onoff_torque_nm": "80", "onoff_duty_cycle_pct": "40",
        "onoff_cycles_per_hour": "36", "mod_torque_inlb": "580", "mod_torque_nm": "65",
        "mod_duty_cycle_pct": "40", "mod_starts_per_hour": "960", "speed_s_60hz": "17",
        "speed_s_50hz": "20", "fla_a_60hz": "1.2", "fla_a_50hz": "1.1", "lra_a_60hz": "1.4",
        "lra_a_50hz": "1.3", "motor_power_w": "15",
    }  # fmt: skip
    return row | overrides


def test_compare_accepts_agreement_and_flags_disagreement():
    rows, conflicts, stats, misread = compare_table(
        SINGLE, [_row("761A00-11300000/A")], [_row("761A00-11300000/A", fla_a_60hz="1.7")]
    )
    assert stats["cells"] == 15 and stats["agree"] == 14
    assert conflicts == [
        {
            "table": "t",
            "part_number": "761A00-11300000/A",
            "field": "fla_a_60hz",
            "a": 1.2,
            "b": 1.7,
        }
    ]
    assert rows[0]["values"]["fla_a_60hz"] is None
    assert rows[0]["values"]["onoff_torque_inlb"] == 700
    assert misread == {"a": [], "b": []}


def test_compare_matches_rows_by_model_code_when_a_part_number_is_misread():
    # The real case: one model dropped a zero in every part number of a table.
    rows, conflicts, stats, misread = compare_table(
        SINGLE, [_row("761A00-1130000/A")], [_row("761A00-11300000/A")]
    )
    assert conflicts == [] and stats["agree"] == 15
    assert rows[0]["part_number"] == "761A00-11300000/A"  # model code + table suffix
    assert misread == {"a": ["761A00-1130000/A"], "b": []}


def test_compare_flags_every_cell_of_a_row_only_one_model_saw():
    _, conflicts, _, _ = compare_table(SINGLE, [_row("761A00-11300000/A")], [])
    assert len(conflicts) == 15 + 1  # every value + the footnote marker
    assert {c["b"] for c in conflicts if c["field"] != "footnote_marker"} == {"(row missing)"}


def test_single_phase_row_becomes_two_ratings():
    values = {k: parse_value(v) for k, v in _row("x").items() if k != "part_number"}
    part = to_part(SINGLE | {"code": "t"}, WP, "761A00-11300000/A", False, values)
    assert [r["service"] for r in part["ratings"]] == ["on_off", "modulating"]
    assert part["ratings"][0]["cycles_per_hour"] == 36
    assert part["ratings"][1]["starts_per_hour"] == 960
    assert part["model_code"] == "761A" and part["size"] == 1 and part["csa_certified"]


def test_footnote_marker_removes_csa():
    values = {k: parse_value(v) for k, v in _row("x").items() if k != "part_number"}
    assert not to_part(SINGLE, WP, "766A00-11320000/A", True, values)["csa_certified"]


def test_na_row_has_no_data():
    values = dict.fromkeys(["torque_inlb", "torque_nm", "motor_power_w"], NA)
    table = {"code": "t", "layout": "three_phase"}
    part = to_part(table, WP, "761A00-11330C00/A", False, values)
    assert part["data_available"] is False and part["ratings"] == []


def test_na_row_with_an_empty_cell_still_has_no_data():
    values = {"torque_inlb": NA, "torque_nm": NA, "motor_power_w": None}
    part = to_part({"code": "t", "layout": "three_phase"}, WP, "761A00-11330C00/A", False, values)
    assert part["data_available"] is False


def _dataset(**rating_overrides):
    values = {k: parse_value(v) for k, v in _row("x").items() if k != "part_number"}
    part = to_part(SINGLE, WP, "761A00-11300000/A", False, values)
    part["ratings"][0] |= rating_overrides
    return {"tables": [SINGLE], "parts": [part]}


def test_validate_passes_consistent_data():
    assert validate(_dataset()) == []


def test_validate_catches_misread_torque_digit():
    errors = validate(_dataset(torque_nm=30))  # 700 in-lbs is about 79 Nm, not 30
    assert any("in-lbs vs 30 Nm" in e for e in errors)
