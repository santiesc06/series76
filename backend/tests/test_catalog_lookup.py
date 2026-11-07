"""lookup_part against the real catalog in PostgreSQL (US-01, US-03, US-04, US-05)."""

import pytest

from app.services.catalog import lookup_part


@pytest.mark.parametrize(
    "query", ["763B00-11300000/A", "763b00-11300000", " 763B00-11300000/A ", "763B00 11300000 A"]
)
def test_exact_lookup_ignores_case_spacing_and_suffix(db, query):  # US-01 AC2
    result = lookup_part(db, query)
    assert result["status"] == "found"
    assert result["part"]["part_number"] == "763B00-11300000/A"


def test_found_part_has_every_spec_from_the_table(db):  # US-01 AC1
    part = lookup_part(db, "763B00-11300000/A")["part"]
    assert part["enclosure"] == "weatherproof"
    assert part["power_supply"] == "110V single phase"
    ratings = {r["service"]: r for r in part["ratings"]}
    assert (ratings["on_off"]["torque_inlb"], ratings["on_off"]["torque_nm"]) == (4400, 500)
    assert (ratings["modulating"]["torque_inlb"], ratings["modulating"]["torque_nm"]) == (3350, 380)
    assert part["electrical"]["speed_s"] == {"60_hz": 26, "50_hz": 32}
    assert part["electrical"]["fla_a"] == {"60_hz": 4.8, "50_hz": 4.6}
    assert part["electrical"]["lra_a"] == {"60_hz": 5.0, "50_hz": 4.9}
    assert part["electrical"]["motor_power_w"] == 90


def test_summary_example_part_number_is_not_found_with_real_suggestions(db):  # US-03 AC1-2
    result = lookup_part(db, "761A00-11380000/A")
    assert result["status"] == "not_found"
    assert "part" not in result
    suggested = [s["part_number"] for s in result["suggestions"]]
    assert len(suggested) <= 5
    assert {"761A00-11300000/A", "761A00-11320000/A", "761X30-11380000/A"} <= set(suggested)


def test_typo_suggests_both_one_edit_away_parts(db):  # US-03 AC3
    suggested = [s["part_number"] for s in lookup_part(db, "763B00-1130000/A")["suggestions"]]
    assert {"763B00-11300000/A", "763B00-11320000/A"} <= set(suggested[:3])


@pytest.mark.parametrize("query", ["hello123", "", "   ", "abc"])
def test_malformed_input_is_rejected_politely(db, query):  # US-03 AC4
    assert lookup_part(db, query)["status"] == "invalid_input"


def test_partial_part_number_lists_variants(db):  # US-04
    result = lookup_part(db, "761A00")
    assert result["status"] == "ambiguous"
    candidates = {c["part_number"]: c for c in result["candidates"]}
    assert set(candidates) == {"761A00-11300000/A", "761A00-11320000/A", "761A00-11330C00/A"}
    assert candidates["761A00-11330C00/A"]["data_available"] is False


def test_unique_prefix_resolves_to_the_part(db):
    result = lookup_part(db, "763X30-11370000")
    assert result["status"] == "found"
    assert result["part"]["part_number"] == "763X30-11370000/A"


def test_na_part_exists_but_has_no_numbers(db):  # US-05 AC1
    result = lookup_part(db, "761A00-11330C00/A")
    assert result["status"] == "no_data"
    assert "ratings" not in result["part"] and "electrical" not in result["part"]


def test_not_csa_part_keeps_ce_and_ukca(db):  # US-13 AC2
    part = lookup_part(db, "767C00-11320000/A")["part"]
    assert part["csa_certified"] is False
    assert part["certifications"] == ["CE", "UKCA"]
    assert any("not CSA" in n for n in part["notes"])


def test_explosionproof_part_reports_markings_and_the_summary_claim(db):  # US-13 AC1, AC4
    part = lookup_part(db, "761X30-11380000/A")["part"]
    assert part["certifications"] == ["CSA"]
    assert "Ex d IIB T4 Gb" in part["hazardous_markings"]
    assert "IECEx/ATEX" in part["certification_note"]


def test_dc_part_has_single_frequency_independent_values(db):  # US-11 AC4
    part = lookup_part(db, "763X30-11370000/A")["part"]
    assert part["electrical"]["speed_s"] == 32
    assert part["frequency_dependent"] is False
