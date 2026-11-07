"""Value and part number normalization shared by compare, build and the API."""

import re

NA = "N/A"
FOOTNOTE_MARKER = "*"

PART_NUMBER_RE = re.compile(r"^76[1-7][A-Z](00|30)-113\d{2}[0-9A-Z]00/A$")


def clean_part_number(raw: str) -> tuple[str, bool]:
    """Return (display part number, has footnote marker). Removes spaces, upper-cases."""
    text = re.sub(r"\s+", "", str(raw)).upper()
    marked = text.endswith(FOOTNOTE_MARKER)
    return text.rstrip(FOOTNOTE_MARKER), marked


FULL_KEY_LENGTH = 14  # 763B00-11300000/A -> 763B0011300000


def match_key(part_number: str) -> str:
    """Key used to match user input to part numbers: letters and digits only, upper case, without
    the trailing revision letter ('/A', ' A' or 'A' after a full 14-character number)."""
    text = re.sub(r"[^0-9A-Za-z]", "", part_number).upper()
    if len(text) == FULL_KEY_LENGTH + 1 and text.endswith("A"):
        text = text[:-1]
    return text


def parse_value(raw: object) -> float | int | str | None:
    """'1,330' -> 1330, '0.7' -> 0.7, 'N/A' -> 'N/A', '' / None -> None."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.upper() in {"N/A", "NA"}:
        return NA
    number = text.replace(",", "").replace(" ", "")
    try:
        value = float(number)
    except ValueError:
        return text  # unexpected text; validation will flag it
    return int(value) if value.is_integer() and "." not in number else value
