"""The structured final answer the agent must return every turn (design B3).

The agent refers to products only by part number; the backend turns those references into product
cards from the database, so no spec value in a card can come from the LLM.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Status = Literal[
    "answered", "clarification_needed", "not_found", "no_data", "no_match", "out_of_scope"
]
View = Literal["none", "cards", "comparison"]

# Start of an XML-style tool argument, e.g. `</parameter>` or `<parameter name="view">`.
LEAKED_MARKUP = re.compile(r"</?parameter\b", re.I)


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

    @field_validator("answer_text")
    @classmethod
    def _drop_leaked_markup(cls, text: str) -> str:
        """Cuts tool-call markup the model sometimes leaks into the text (`</parameter>`)."""
        match = LEAKED_MARKUP.search(text)
        return text[: match.start()].rstrip() if match else text
