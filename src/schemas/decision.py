"""What the engine produces: a fact value read from the notes, and a decision."""
from __future__ import annotations

from typing import Callable, Literal

from pydantic import BaseModel, Field

from src.schemas.policy import FactQuestion, Queue


class FactValue(BaseModel):
    """Answer to one fact question: True / False / None (unknown), with the words that justify it."""
    value: bool | None = None
    quote: str = ""


FactProvider = Callable[[dict, list[FactQuestion]], dict[str, FactValue]]
"""(request row, questions to answer) -> answers. The engine calls this lazily."""


class Decision(BaseModel):
    request_id: str
    outcome: Literal["approve", "route"]
    queue: Queue | None
    rule_id: str
    rule_name: str
    reason: str
    facts_used: dict[str, FactValue] = Field(default_factory=dict)
    policy_version: int
    amount_usd: float | None
    decided_at: str
