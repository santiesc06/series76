"""Answer-text number check (design B4, NFR-01). Pure functions, no database."""

from app.agent.number_check import allowed_numbers, unsupported_numbers

RESULT = {
    "part": {"part_number": "763B00-11300000/A",
             "ratings": [{"torque_nm": 500, "torque_inlb": 4400}],
             "electrical": {"fla_a": {"60_hz": 4.8, "50_hz": 4.6}, "motor_power_w": 90}},
    "assumptions": ["230V was matched to the 220V models, within the ±10% tolerance."],
    "total_matches": 21,
}  # fmt: skip


def check(text: str, *sources) -> list[str]:
    return unsupported_numbers(text, allowed_numbers(RESULT, *sources))


def test_numbers_from_tool_results_pass():
    assert check("It delivers 500 Nm (4,400 in-lbs) and draws 4.8 A at 60 Hz, 90 W.") == []


def test_invented_number_is_flagged():
    assert check("It delivers 520 Nm.") == ["520"]


def test_spanish_decimal_comma_and_thousands_dot():
    assert check("Entrega 4.400 in-lbs y consume 4,8 A a 50 Hz.") == []


def test_part_numbers_and_markings_are_not_numbers():
    text = "763B00-11300000/A and the 761A00 family are rated S4, Ex d IIB T4 Gb."
    assert check(text) == []


def test_numbers_inside_tool_strings_count():
    assert check("230V maps to 220V models within ±10%.", "230V") == []


def test_numbers_the_user_wrote_are_allowed():
    assert check("No model reaches 5000 Nm.") == ["5000"]
    assert check("No model reaches 5000 Nm.", "I need 5000 Nm") == []


def test_small_counts_are_not_flagged():
    assert check("I found 2 options; Zone 1 is covered.") == []
    assert check("Encontré 3 modelos, del 2 a 60 Hz.") == []  # Spanish "a" is not amperes


def test_small_numbers_with_a_unit_are_checked():  # B4b
    assert check("It draws 5 A and makes 8 starts per hour.") == ["5", "8"]
    assert check("Runs in 7 s, 3 Nm, 9 W, 2 in-lbs.") == ["7", "3", "9", "2"]
    assert check("Hace 6 arranques por hora.") == ["6"]


def test_total_count_from_the_tool_passes():
    assert check("There are 21 matching models.") == []


def test_series_name_and_size_codes_are_identifiers():  # B4a, eval run 2026-11-07
    assert check("No Series 76 model reaches that; sizes 765, 766 and 767 are the largest.") == []
    assert check("It delivers 766 Nm.") == ["766"]  # with a unit it is a value again


def test_unicode_hyphens_and_spaces_in_part_numbers():  # B4a″, eval comparison 2026-11-08
    # gpt-oss-120b wrote part numbers with a non-breaking hyphen (U+2011) and narrow no-break
    # spaces (U+202F); "11300000" was read as an invented value and the answer was replaced.
    text = "The 763B00\u201111300000/A delivers 500\u202fNm (4,400\u202fin\u2011lb)."
    assert check(text) == []
    assert check("763B00\u201311300000/A draws 4.6\u20134.8\u00a0A.") == []  # en dash


def test_unicode_characters_do_not_hide_invented_numbers():  # B4a″
    assert check("The 763B00\u201111300000/A delivers 520\u202fNm.") == ["520"]
    assert check("It draws 5\u202fA.") == ["5"]  # small number with a unit is still checked
