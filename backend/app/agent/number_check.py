"""Answer-text number check (design B4, NFR-01).

Every number in the agent's free text must also appear in what the tools returned this turn (or
in what the user wrote). Product cards are built from the database and need no check; this guards
the sentence around them.

Excluded from the check: part numbers and model codes (763B00-11300000/A, 761A), digits glued to
letters (S4, T4, IIB), and bare small integers up to 10, which are counts and ordinals ("2 models",
"Zone 1"). A small integer followed by a unit ("5 A", "8 starts") is a spec value and is checked
(design B4b).
"""

import json
import re

# Model code (763B, 761A00, 763X30) optionally followed by the rest (-11300000/A, -11330C00/A).
# The letter in 4th position keeps plain numbers such as 7680 from being taken for part numbers.
PART_RE = re.compile(r"\b76[1-7][A-Z](?:\d{2})?(?:[-\s]?113\d{2}[0-9A-Z]00(?:/A)?)?\b", re.I)
NUMBER_RE = re.compile(r"(?<![A-Za-z\d.,])\d+(?:[.,]\d+)*")
SMALL_INT_LIMIT = 10
# A unit right after a number marks it as a spec value. Symbols are case-sensitive so the Spanish
# preposition "a" ("2 a 60 Hz") is not read as amperes; words ignore case.
UNIT_RE = re.compile(
    r"\s?(?:%|°|(?:Nm|N·m|A|W|V|VAC|VDC|Hz|s|kg)(?![A-Za-z])"
    r"|(?i:in-?lbs?|lb-?in|lbs?|amps?|watts?|volts?|sec|seconds?|segundos?|starts?|arranques"
    r"|cycles?|ciclos)\b)"
)
# Numbers that appear in the field definitions of the system prompt (90-degree turn, 50/60 Hz).
PROMPT_NUMBERS = {90.0, 50.0, 60.0}


def _candidates(token: str) -> set[float]:
    """All plausible readings of a token: '2,400' -> 2400, '0,7' -> 0.7, '2.400' -> 2.4 or 2400."""
    values: set[float] = set()
    if re.fullmatch(r"\d{1,3}(,\d{3})+", token):
        values.add(float(token.replace(",", "")))
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", token):
        values.add(float(token.replace(".", "")))
    if re.fullmatch(r"\d+([.,]\d+)?", token):
        values.add(float(token.replace(",", ".")))
    return {round(v, 6) for v in values}


def numbers_in_text(text: str) -> list[tuple[str, set[float]]]:
    text = PART_RE.sub(" ", text)
    return [(m.group(0), _candidates(m.group(0))) for m in NUMBER_RE.finditer(text)]


def allowed_numbers(*sources: object) -> set[float]:
    """Every number in the given tool results / user messages (JSON keys and string values too)."""
    allowed = set(PROMPT_NUMBERS)

    def visit(value: object) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, int | float):
            allowed.add(round(float(value), 6))
        elif isinstance(value, str):
            for _, candidates in numbers_in_text(value):
                allowed.update(candidates)
        elif isinstance(value, dict):
            for key, item in value.items():
                visit(str(key).replace("_", " "))
                visit(item)
        elif isinstance(value, list | tuple):
            for item in value:
                visit(item)
        else:
            visit(json.dumps(value, default=str))

    for source in sources:
        visit(source)
    return allowed


def unsupported_numbers(text: str, allowed: set[float]) -> list[str]:
    """Numbers in `text` that no tool returned this turn."""
    text = PART_RE.sub(" ", text)
    problems = []
    for match in NUMBER_RE.finditer(text):
        token = match.group(0)
        candidates = _candidates(token)
        if not candidates or candidates & allowed:
            continue
        small = any(v.is_integer() and v <= SMALL_INT_LIMIT for v in candidates)
        if small and not UNIT_RE.match(text, match.end()):
            continue
        problems.append(token)
    return problems
