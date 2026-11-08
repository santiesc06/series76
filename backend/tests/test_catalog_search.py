"""search_actuators and catalog_overview against PostgreSQL (US-07, US-10, US-11, US-13, US-14)."""

import pytest
from pydantic import ValidationError

from app.services.catalog import SearchFilters, catalog_overview, search_actuators


def _numbers(result: dict, key: str = "results") -> list[str]:
    return [r["part_number"] for r in result[key]]


def test_requirement_example_returns_only_the_right_model(db):  # US-07 AC1
    result = search_actuators(
        db,
        SearchFilters(
            enclosure="explosionproof", voltage=220, phase="single", service="modulating",
            min_torque=2000,
        ),
    )  # fmt: skip
    assert result["status"] == "matches"
    assert _numbers(result) == ["765Y30-11320000/A"]
    assert result["results"][0]["matched_ratings"][0]["torque_nm"] == 2400


def test_results_are_right_sized_smallest_first(db):  # US-07 AC2
    result = search_actuators(db, SearchFilters(voltage=110, min_torque=500, service="on_off"))
    torques = [min(m["torque_nm"] for m in r["matched_ratings"]) for r in result["results"]]
    assert torques == sorted(torques) and torques[0] >= 500


def test_on_off_and_modulating_ratings_are_not_mixed(db):  # US-07 AC3
    # 763B00-11300000/A: 500 Nm On/Off but only 380 Nm Modulating.
    on_off = search_actuators(db, SearchFilters(voltage=110, service="on_off", min_torque=450))
    modulating = search_actuators(
        db, SearchFilters(voltage=110, phase="single", service="modulating", min_torque=450)
    )
    assert "763B00-11300000/A" in _numbers(on_off)
    assert "763B00-11300000/A" not in _numbers(modulating)


def test_at_most_five_results_with_total_count(db):  # US-07 AC4
    result = search_actuators(db, SearchFilters())
    assert len(result["results"]) == 5 and result["total_matches"] == 64


def test_superlative_fastest_explosionproof(db):  # US-07 AC5
    result = search_actuators(db, SearchFilters(enclosure="explosionproof", sort_by="speed"))
    speeds = [r["speed_s"] for r in result["results"]]
    assert speeds == sorted(speeds) and speeds[0] == 17


def test_24v_ac_modulating_does_not_exist(db):  # US-07 AC6
    result = search_actuators(
        db, SearchFilters(voltage=24, current_type="ac", service="modulating")
    )
    assert result["status"] == "no_match"
    relaxed = {a["if_relaxed"]: a["part_number"] for a in result["alternatives"]}
    assert relaxed["AC supply"].endswith("-11370000/A")  # the 24V DC modulating table


def test_no_match_names_the_failing_requirement_and_closest_models(db):  # US-10 AC1-2
    result = search_actuators(db, SearchFilters(enclosure="explosionproof", min_torque=5000))
    assert result["status"] == "no_match"
    assert result["failing_requirements"] == ["torque ≥ 5000 Nm"]
    assert _numbers(result, "alternatives")[:2] == ["765Y30-11300000/A", "765Y30-11320000/A"]
    assert all(a["fails"] == "torque ≥ 5000 Nm" for a in result["alternatives"])
    assert all(a["enclosure"] == "explosionproof" for a in result["alternatives"])


def test_more_torque_than_any_model(db):  # US-10 AC3
    result = search_actuators(db, SearchFilters(min_torque=10000))
    assert result["status"] == "no_match"
    assert _numbers(result, "alternatives")[0] == "767C00-11320000/A"  # 9,000 Nm, the largest


@pytest.mark.parametrize(("value", "unit"), [(2000, "Nm"), (17700, "in-lbs")])
def test_torque_in_both_units_uses_the_table_column(db, value, unit):  # US-11 AC1, D-3
    result = search_actuators(
        db, SearchFilters(voltage=110, service="on_off", min_torque=value, torque_unit=unit)
    )
    assert _numbers(result)[0] == "765A00-11300000/A"  # 17,700 in-lbs / 2,000 Nm


def test_nearby_voltages_map_within_tolerance(db):  # US-11 AC2, D-4
    result = search_actuators(db, SearchFilters(voltage=230, phase="single", limit=1))
    assert result["results"][0]["power_supply"] == "220V single phase"
    assert any("±10%" in a for a in result["assumptions"])
    assert search_actuators(db, SearchFilters(voltage=480))["status"] == "no_match"


def test_frequency_changes_speed_comparison(db):  # US-11 AC3, D-5
    # 763B00-11300000/A: 26 s at 60 Hz, 32 s at 50 Hz.
    base = {"voltage": 110, "service": "on_off", "min_torque": 500, "max_speed_s": 30}
    at_60 = search_actuators(db, SearchFilters(**base))
    at_50 = search_actuators(db, SearchFilters(**base, frequency_hz=50))
    assert "763B00-11300000/A" in _numbers(at_60)
    assert "763B00-11300000/A" not in [r["part_number"] for r in at_50.get("results", [])]
    assert any("60 Hz" in a for a in at_60["assumptions"])


def test_three_phase_rating_counts_for_modulating_with_a_note(db):  # D-1
    result = search_actuators(
        db, SearchFilters(voltage=220, phase="three", service="modulating", min_torque=500)
    )
    assert _numbers(result)[0] == "763B00-11330C00/A"
    assert any("does not split by service" in a for a in result["assumptions"])


def test_csa_requirement_excludes_sizes_6_and_7(db):  # US-13 AC3
    result = search_actuators(db, SearchFilters(csa_required=True, min_torque=3500))
    assert result["status"] == "no_match"
    assert not any(n.startswith(("766", "767")) for n in _numbers(result, "alternatives"))


def test_na_models_are_never_recommended(db):  # US-05 AC2
    result = search_actuators(db, SearchFilters(voltage=220, phase="three", min_torque=1))
    assert result["total_matches"] == 7


@pytest.mark.parametrize(
    "filters",
    [
        {"hazardous_zone": 1, "gas_group": "IIB"},
        {"hazardous_zone": 2},
        {"hazardous_division": 1, "gas_group": "D"},
        {"gas_group": "IIA"},
    ],
)
def test_covered_hazardous_areas_return_explosionproof_models(db, filters):  # US-14 AC1
    result = search_actuators(db, SearchFilters(**filters))
    assert result["status"] == "matches"
    assert {r["enclosure"] for r in result["results"]} == {"explosionproof"}


@pytest.mark.parametrize(
    "filters",
    [{"gas_group": "IIC"}, {"gas_group": "A"}, {"hazardous_zone": 0}, {"dust_hazard": True}],
)
def test_uncovered_hazardous_areas_get_no_model_and_no_alternative(db, filters):  # US-14 AC2-3
    result = search_actuators(db, SearchFilters(**filters))
    assert result["status"] == "no_match"
    assert result["alternatives"] == []
    assert "safety requirement" in result["message"]
    assert "Ex d IIB T4 Gb" in result["hazardous_note"]


def test_limit_cannot_exceed_five():
    with pytest.raises(ValidationError):
        SearchFilters(limit=10)


def test_overview_describes_every_table(db):
    overview = catalog_overview(db)
    supplies = {(t["enclosure"], t["power_supply"]) for t in overview["tables"]}
    assert ("explosionproof", "24V DC") in supplies and (
        "weatherproof",
        "220V three phase",
    ) in supplies
    three_phase = next(t for t in overview["tables"] if t["power_supply"] == "220V three phase")
    assert three_phase["parts_without_data"] == 4
    assert three_phase["services"]["both"]["torque_nm_range"] == {"min": 300, "max": 3000}


def _guarded(db, **filters):
    return search_actuators(db, SearchFilters(**filters), require_power_supply=True)


def test_missing_voltage_asks_for_the_supply_with_real_options(db):  # US-08 AC1, B2a
    result = _guarded(db, min_torque=500)
    assert result["status"] == "power_supply_needed" and "results" not in result
    supplies = [s["power_supply"] for s in result["supplies_with_matches"]]
    assert supplies == ["110V single phase", "220V single phase", "220V three phase"]


def test_missing_voltage_with_one_possible_supply_answers_directly(db):  # B2a
    result = _guarded(db, min_torque=8000)
    assert result["status"] == "matches"
    assert {r["power_supply"] for r in result["results"]} == {"220V single phase"}


def test_missing_voltage_with_no_match_still_says_no_model(db):  # US-10 AC3, B2a
    assert _guarded(db, min_torque=10000)["status"] == "no_match"


def test_guard_does_not_change_searches_with_a_voltage(db):  # B2a
    filters = {"voltage": 110, "min_torque": 500}
    assert _guarded(db, **filters) == search_actuators(db, SearchFilters(**filters))


def test_partial_result_list_says_so(db):  # US-07 AC4: a short list is not the whole catalog
    result = search_actuators(
        db, SearchFilters(voltage=220, phase="single", enclosure="weatherproof")
    )
    assert result["total_matches"] > len(result["results"])
    assert f"of {result['total_matches']} matches" in result["note"]
    complete = search_actuators(db, SearchFilters(enclosure="explosionproof", min_torque=4000))
    assert "note" not in complete or complete["total_matches"] == len(complete["results"])
