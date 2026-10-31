"""The policy file format: fact questions plus an ordered list of rules.

A rule is a list of conditions on request columns or on facts extracted from the notes.
The engine (engine.py) reads rules top to bottom; the first rule whose conditions all
hold decides the request. If none holds, the request goes to a person.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Op = Literal["==", "!=", "<", "<=", ">", ">=", "in", "not_in", "is_true", "is_false", "is_unknown"]
Outcome = Literal["approve", "route"]
Queue = Literal["reviewer", "fraud"]

REQUEST_FIELDS: frozenset[str] = frozenset({
    "request_id", "source", "tenure_months", "prior_refunds_12m", "amount_usd", "category",
    "payment_method", "stated_reason", "days_since_delivery", "fraud_flag", "has_note", "duplicate_conflict",
})

FIELD_LABELS: dict[str, str] = {
    "request_id": "request id",
    "source": "request source",
    "tenure_months": "customer tenure (months)",
    "prior_refunds_12m": "prior refunds in last 12 months",
    "amount_usd": "amount (USD)",
    "category": "product category",
    "payment_method": "payment method",
    "stated_reason": "stated reason",
    "days_since_delivery": "days since delivery",
    "fraud_flag": "fraud flag",
    "has_note": "has a note",
    "duplicate_conflict": "duplicate id with different details",
}

_OP_WORDS: dict[str, str] = {
    "==": "equals", "!=": "is not", "<": "is below", "<=": "is at most", ">": "is above", ">=": "is at least",
    "in": "is one of", "not_in": "is none of", "is_true": "is yes", "is_false": "is no", "is_unknown": "is unknown",
}


ConditionValue = int | float | str | bool | list[int | float | str] | None


class Condition(BaseModel):
    field: str
    op: Op
    value: ConditionValue = Field(default=None, description="Omit for is_true / is_false / is_unknown; a list for in / not_in.")

    @model_validator(mode="after")
    def _check_shape(self) -> "Condition":
        if self.op in ("is_true", "is_false", "is_unknown"):
            if self.value is not None:
                raise ValueError(f"'{self.op}' takes no value")
        elif self.op in ("in", "not_in"):
            if not isinstance(self.value, list) or not self.value:
                raise ValueError(f"'{self.op}' needs a non-empty list of values")
        else:
            if self.value is None or isinstance(self.value, list):
                raise ValueError(f"'{self.op}' needs a single value")
        return self


class Rule(BaseModel):
    id: str
    name: str
    description: str = ""
    when: list[Condition] = Field(default_factory=list)
    then: Outcome
    queue: Queue = "reviewer"
    enabled: bool = True


class FactQuestion(BaseModel):
    id: str
    question: str


class Policy(BaseModel):
    version: int
    changelog: str = ""
    created_at: str = ""
    facts: list[FactQuestion] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_consistency(self) -> "Policy":
        fact_ids = [f.id for f in self.facts]
        dupes = {x for x in fact_ids if fact_ids.count(x) > 1}
        if dupes:
            raise ValueError(f"duplicate fact ids: {sorted(dupes)}")
        shadow = set(fact_ids) & REQUEST_FIELDS
        if shadow:
            raise ValueError(f"fact ids clash with request fields: {sorted(shadow)}")
        rule_ids = [r.id for r in self.rules]
        dupes = {x for x in rule_ids if rule_ids.count(x) > 1}
        if dupes:
            raise ValueError(f"duplicate rule ids: {sorted(dupes)}")
        known = REQUEST_FIELDS | set(fact_ids)
        for rule in self.rules:
            for cond in rule.when:
                if cond.field not in known:
                    raise ValueError(f"rule '{rule.id}' uses unknown field '{cond.field}'")
        return self

    def fact_ids(self) -> list[str]:
        return [f.id for f in self.facts]

    def fact_label(self, fact_id: str) -> str:
        for f in self.facts:
            if f.id == fact_id:
                return f'"{f.question}"'
        return fact_id

    def describe_condition(self, cond: Condition) -> str:
        label = FIELD_LABELS.get(cond.field) or self.fact_label(cond.field)
        words = _OP_WORDS[cond.op]
        if cond.op in ("is_true", "is_false", "is_unknown"):
            return f"{label} {words}"
        if cond.op in ("in", "not_in"):
            return f"{label} {words} {', '.join(str(v) for v in cond.value)}"
        return f"{label} {words} {cond.value}"

    def describe_rule(self, rule: Rule) -> str:
        then = "approve" if rule.then == "approve" else f"route to {rule.queue} queue"
        if not rule.when:
            return f"ALWAYS {then}"
        return "IF " + " AND ".join(self.describe_condition(c) for c in rule.when) + f" THEN {then}"
