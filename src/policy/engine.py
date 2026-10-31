"""The rules engine: deterministic, testable, and the only thing that decides money.

For each request: walk the enabled rules top to bottom. A rule matches when every
condition is True. Column conditions are checked first; facts from the notes are
requested from the fact provider only if the column conditions already hold and the
rule actually references a fact. An unknown value (missing column, fact the model
could not answer) never makes a condition True, so it can never approve.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from src.logging_setup import get_logger
from src.schemas.decision import Decision, FactProvider, FactValue
from src.schemas.policy import Condition, FactQuestion, Policy, Rule

log = get_logger("engine")

DEFAULT_RULE_ID = "default_route"
DEFAULT_REASON = "No rule matched; needs a person."


def unknown_fact_provider(row: dict, questions: list[FactQuestion]) -> dict[str, FactValue]:
    """Offline provider: every fact is unknown, so nothing fact-based can approve."""
    return {q.id: FactValue(value=None) for q in questions}


# ---------------------------------------------------------------- conditions

def _is_missing(value: Any) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    try:
        return isinstance(value, float) and math.isnan(value)
    except TypeError:
        return False


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_condition(cond: Condition, row: dict, facts: dict[str, FactValue]) -> bool | None:
    """True / False / None (unknown)."""
    if cond.field in facts:
        value = facts[cond.field].value
    elif cond.field in row:
        value = row[cond.field]
    else:
        value = None  # a fact that was never provided, or a column the file lacks

    if cond.op == "is_unknown":
        return _is_missing(value)
    if _is_missing(value):
        return None
    if cond.op == "is_true":
        return value is True
    if cond.op == "is_false":
        return value is False
    if cond.op in ("in", "not_in"):
        members = [str(v) for v in (cond.value or [])]
        hit = str(value) in members
        return hit if cond.op == "in" else not hit
    if cond.op in ("==", "!="):
        a, b = _as_number(value), _as_number(cond.value)
        equal = (a == b) if (a is not None and b is not None) else (str(value) == str(cond.value))
        return equal if cond.op == "==" else not equal
    a, b = _as_number(value), _as_number(cond.value)
    if a is None or b is None:
        return None
    return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[cond.op]


def rule_fact_ids(rule: Rule, fact_ids: set[str]) -> list[str]:
    return [c.field for c in rule.when if c.field in fact_ids]


# ---------------------------------------------------------------- decisions

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def decide(row: dict, policy: Policy, fact_provider: FactProvider = unknown_fact_provider) -> Decision:
    fact_ids = set(policy.fact_ids())
    questions = {q.id: q for q in policy.facts}
    facts: dict[str, FactValue] = {}
    request_id = str(row.get("request_id", ""))
    amount = _as_number(row.get("amount_usd")) if not _is_missing(row.get("amount_usd")) else None

    for rule in policy.rules:
        if not rule.enabled:
            continue
        needed = rule_fact_ids(rule, fact_ids)
        column_conds = [c for c in rule.when if c.field not in fact_ids]
        if not all(evaluate_condition(c, row, facts) is True for c in column_conds):
            continue
        missing = [f for f in needed if f not in facts]
        if missing:
            facts.update(fact_provider(row, [questions[f] for f in missing]))
        fact_conds = [c for c in rule.when if c.field in fact_ids]
        if not all(evaluate_condition(c, row, facts) is True for c in fact_conds):
            continue
        used = {f: facts[f] for f in needed if f in facts}
        log.info("decision request=%s outcome=%s rule=%s policy=v%d", request_id, rule.then, rule.id, policy.version)
        return Decision(
            request_id=request_id, outcome=rule.then, queue=rule.queue if rule.then == "route" else None,
            rule_id=rule.id, rule_name=rule.name, reason=rule.description or policy.describe_rule(rule),
            facts_used=used, policy_version=policy.version, amount_usd=amount, decided_at=_now(),
        )

    log.info("decision request=%s outcome=route rule=%s policy=v%d", request_id, DEFAULT_RULE_ID, policy.version)
    return Decision(
        request_id=request_id, outcome="route", queue="reviewer", rule_id=DEFAULT_RULE_ID, rule_name="Default",
        reason=DEFAULT_REASON, facts_used=facts, policy_version=policy.version, amount_usd=amount, decided_at=_now(),
    )


def decide_frame(df: pd.DataFrame, policy: Policy, fact_provider: FactProvider = unknown_fact_provider) -> list[Decision]:
    return [decide(row, policy, fact_provider) for row in df.to_dict(orient="records")]


def decisions_to_frame(decisions: list[Decision]) -> pd.DataFrame:
    rows = []
    for d in decisions:
        rec = d.model_dump()
        rec["facts_used"] = {k: v["value"] for k, v in rec["facts_used"].items()}
        rows.append(rec)
    cols = ["request_id", "outcome", "queue", "rule_id", "rule_name", "reason", "amount_usd", "facts_used",
            "policy_version", "decided_at"]
    return pd.DataFrame(rows, columns=cols)
