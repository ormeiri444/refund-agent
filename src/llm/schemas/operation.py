"""What the model must return when translating the manager's instruction into a policy change."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.schemas.policy import FactQuestion, Rule

OpKind = Literal["add_rule", "replace_rule", "disable_rule", "add_fact", "cannot_express"]


class RuleOperation(BaseModel):
    op: OpKind
    rule: Rule | None = Field(default=None, description="For add_rule / replace_rule: the full rule.")
    fact: FactQuestion | None = Field(default=None, description="For add_fact: the new yes/no question about the notes.")
    target_rule_id: str | None = Field(default=None, description="For replace_rule / disable_rule: the existing rule's id.")
    position: Literal["top", "bottom"] | None = Field(
        default=None, description="Only when the instruction states an order; otherwise null and the system decides by outcome.")
    explanation: str = Field(description="One plain sentence for the manager: what this does, or why it cannot be expressed.")
