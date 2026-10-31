"""What the model must return when asked the policy's fact questions about a note."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FactAnswer(BaseModel):
    fact_id: str = Field(description="The id of the question being answered, exactly as given.")
    value: Literal["true", "false", "unknown"] = Field(description="unknown unless the text clearly says.")
    quote: str = Field(default="", description="The exact words from the note that justify the answer, or empty.")


class FactExtraction(BaseModel):
    answers: list[FactAnswer]
