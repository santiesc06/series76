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


def match_key(part_number: str) -> str:
    """Key used to match user input to part numbers: no spaces, dashes, slashes or '/A' suffix."""
    text = re.sub(r"[\s*]", "", part_number).upper()
    text = re.sub(r"/A$", "", text)
    return re.sub(r"[-/]", "", text)


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
