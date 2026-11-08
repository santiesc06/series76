"""The structured final answer the agent must return every turn (design B3).

The agent refers to products only by part number; the backend turns those references into product
cards from the database, so no spec value in a card can come from the LLM.
"""

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator

Status = Literal[
    "answered", "clarification_needed", "not_found", "no_data", "no_match", "out_of_scope"
]
View = Literal["none", "cards", "comparison"]

# Start of an XML-style tool argument, e.g. `</parameter>` or `<parameter name="view">`.
LEAKED_MARKUP = re.compile(r"</?parameter\b", re.I)
# One leaked argument: <parameter name="view">comparison</parameter>
LEAKED_FIELD = re.compile(r'<parameter name="(\w+)">(.*?)(?:</parameter>|$)', re.S)


class QuickReply(BaseModel):
    label: str = Field(description="Short text shown on the button, e.g. '110V single phase'.")
    message: str = Field(description="Message sent on the user's behalf when tapped.")


class FinalAnswer(BaseModel):
    """Your answer to the user for this turn. Always finish by calling this."""

    # answer_text stays first (design B3a): writing the answer before choosing the status works as
    # a short reasoning step. Putting it last was tried and misclassified out-of-scope questions.
    answer_text: str = Field(
        description="Short answer for the user (1-4 sentences) in the user's language. Only "
        "numbers returned by a tool in this turn."
    )
    status: Status
    view: View = Field("none", description="cards, comparison (2+ products) or none.")
    product_refs: list[str] = Field(
        default_factory=list, description="Part numbers to show as cards (max 5)."
    )
    alternative_refs: list[str] = Field(
        default_factory=list, description="For no_match: alternative part numbers (max 3)."
    )
    quick_replies: list[QuickReply] = Field(default_factory=list, description="Max 5.")

    # True when `status` was missing and filled in by `_infer_missing_status` (design B3b).
    _status_inferred: bool = PrivateAttr(default=False)

    @model_validator(mode="wrap")
    @classmethod
    def _infer_missing_status(cls, data, handler):
        """`status` stays required in the schema the model sees, but a call without it is
        completed from the other fields instead of being rejected (design B3b). Seen with Haiku:
        the status is left out and the omission repeats on every retry until the step limit."""
        if isinstance(data, dict):
            data = _recover_leaked_fields(data)
        missing = isinstance(data, dict) and not data.get("status")
        if missing:
            data = {**data, "status": infer_status(data)}
        answer = handler(data)
        answer._status_inferred = missing
        return answer

    @field_validator("answer_text")
    @classmethod
    def _drop_leaked_markup(cls, text: str) -> str:
        """Cuts tool-call markup the model sometimes leaks into the text (`</parameter>`)."""
        match = LEAKED_MARKUP.search(text)
        return text[: match.start()].rstrip() if match else text


def infer_status(fields: dict) -> str:
    """Deterministic status for a FinalAnswer that left it out (design B3b)."""
    if fields.get("alternative_refs"):
        return "no_match"
    if fields.get("product_refs"):
        return "answered"
    if fields.get("quick_replies"):
        return "clarification_needed"
    return "answered"


def _recover_leaked_fields(data: dict) -> dict:
    """Fields the model wrote as XML inside answer_text become real fields again (design B3b),
    unless it also sent them properly. The text itself is cut by `_drop_leaked_markup`."""
    text = data.get("answer_text")
    if not isinstance(text, str) or "<parameter" not in text:
        return data
    recovered = {}
    for name, raw in LEAKED_FIELD.findall(text):
        if name in FinalAnswer.model_fields and name != "answer_text" and name not in data:
            value = raw.strip()
            try:
                recovered[name] = json.loads(value) if value[:1] in "[{" else value
            except json.JSONDecodeError:
                continue
    return {**data, **recovered}
