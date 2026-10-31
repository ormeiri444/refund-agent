"""Apply a manager's change to a policy and get a new, validated version. Pure, no LLM."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from src.llm.schemas.operation import RuleOperation
from src.logging_setup import get_logger
from src.schemas import Policy, Rule

log = get_logger("policy.operations")


def resolve_position(rule: Rule, position: Literal["top", "bottom"] | None) -> Literal["top", "bottom"]:
    """A restriction must outrank every approval; an approval must sit below every guard."""
    if position is not None:
        return position
    return "top" if rule.then == "route" else "bottom"


def apply_operation(policy: Policy, op: RuleOperation, changelog: str) -> Policy:
    """Return a new Policy (version + 1). Raises ValueError for cannot_express / unknown targets; ValidationError for bad rules."""
    if op.op == "cannot_express":
        raise ValueError(f"cannot express this instruction: {op.explanation}")
    rules = [r.model_copy(deep=True) for r in policy.rules]
    facts = [f.model_copy(deep=True) for f in policy.facts]
    ids = [r.id for r in rules]

    if op.op == "add_rule":
        if op.rule is None:
            raise ValueError("add_rule needs a rule")
        if resolve_position(op.rule, op.position) == "top":
            rules.insert(0, op.rule)
        else:
            rules.append(op.rule)
    elif op.op == "replace_rule":
        if op.rule is None or op.target_rule_id not in ids:
            raise ValueError(f"replace_rule: unknown rule id {op.target_rule_id!r}")
        rules[ids.index(op.target_rule_id)] = op.rule
    elif op.op == "disable_rule":
        if op.target_rule_id not in ids:
            raise ValueError(f"disable_rule: unknown rule id {op.target_rule_id!r}")
        rules[ids.index(op.target_rule_id)].enabled = False
    elif op.op == "add_fact":
        if op.fact is None:
            raise ValueError("add_fact needs a fact question")
        facts.append(op.fact)

    new = Policy(version=policy.version + 1, changelog=changelog,
                 created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), facts=facts, rules=rules)
    log.info("policy v%d -> v%d: %s (%s)", policy.version, new.version, op.op, changelog)
    return new


def proposal_notes(live: Policy, proposal: Policy) -> list[str]:
    """What the proposal changes compared with the live policy, as the *net* difference (not the click history)."""
    notes: list[str] = []
    live_rules = {r.id: r for r in live.rules}
    prop_rules = {r.id: r for r in proposal.rules}
    for rid, rule in prop_rules.items():
        old = live_rules.get(rid)
        if old is None:
            notes.append(f"added rule {rid}: {proposal.describe_rule(rule)}")
        elif old.enabled and not rule.enabled:
            notes.append(f"disabled rule {rid}")
        elif not old.enabled and rule.enabled and old.model_copy(update={"enabled": True}) == rule:
            notes.append(f"re-enabled rule {rid}")
        elif old.model_copy(update={"enabled": rule.enabled}) != rule:
            notes.append(f"changed rule {rid}: {proposal.describe_rule(rule)}")
    for rid in live_rules:
        if rid not in prop_rules:
            notes.append(f"removed rule {rid}")
    live_facts = {f.id: f for f in live.facts}
    for fact in proposal.facts:
        if fact.id not in live_facts:
            notes.append(f"added question {fact.id}: {fact.question}")
        elif live_facts[fact.id].question != fact.question:
            notes.append(f"reworded question {fact.id}: {fact.question}")
    return notes
