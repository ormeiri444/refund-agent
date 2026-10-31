"""Turn the manager's English into one structured policy operation. The model proposes; it never publishes.

Every returned rule is checked against the closed vocabulary (request fields + the policy's fact ids). Anything
outside it becomes `cannot_express` with a reason, so a rule the system cannot evaluate can never be created.
"""
from __future__ import annotations

import re

import anthropic

from src.llm.client import LLMClient, LLMUnavailable, render_prompt
from src.llm.schemas.operation import RuleOperation
from src.logging_setup import get_logger
from src.schemas import FIELD_LABELS, REQUEST_FIELDS, Policy

log = get_logger("llm.translator")

FIELD_VALUES = {
    "stated_reason": "wrong_size, changed_mind, arrived_damaged, wrong_item, never_arrived, late_delivery",
    "category": "apparel, home, electronics",
    "payment_method": "card, paypal",
    "source": "web_form, support_desk",
    "fraud_flag": "yes/no/unknown (use is_true / is_false / is_unknown)",
    "has_note": "use is_true / is_false",
    "duplicate_conflict": "use is_true / is_false",
}


def _fields_text() -> str:
    lines = []
    for f in sorted(REQUEST_FIELDS - {"request_id"}):
        extra = f" (values: {FIELD_VALUES[f]})" if f in FIELD_VALUES else " (number)"
        lines.append(f"- {f}: {FIELD_LABELS.get(f, f)}{extra}")
    return "\n".join(lines)


def _unique_id(base: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9_]", "_", base.lower()).strip("_") or "rule"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}_{n}", n + 1
    return candidate


def translate_instruction(instruction: str, policy: Policy, client: LLMClient) -> RuleOperation:
    system = render_prompt(
        "translate_rule",
        fields=_fields_text(),
        facts="\n".join(f"- {q.id}: {q.question}" for q in policy.facts) or "- (none yet)",
        rules="\n".join(f"- {r.id}: {policy.describe_rule(r)}" + ("" if r.enabled else " [disabled]") for r in policy.rules),
    )
    user = render_prompt("translate_rule_user", instruction=instruction.strip())
    try:
        op, usage = client.complete_json(system, user, RuleOperation, max_tokens=2048)
    except LLMUnavailable:
        return RuleOperation(op="cannot_express", explanation="The language model is unavailable (no API key). Use the form below to write the rule by hand.")
    except (ValueError, anthropic.APIError) as exc:
        log.warning("translate failed: %s: %s", type(exc).__name__, exc)
        return RuleOperation(op="cannot_express", explanation=f"The model did not return a usable change ({type(exc).__name__}). Try rewording, or use the form.")

    known = REQUEST_FIELDS | set(policy.fact_ids())
    if op.rule is not None:
        unknown = sorted({c.field for c in op.rule.when if c.field not in known})
        if unknown:
            return RuleOperation(op="cannot_express", explanation=(
                f"I can't express this: the system has no field or fact question for {', '.join(unknown)}. "
                f"Add a fact question that the notes can answer, then write the rule on it. ({op.explanation})"))
        if op.op == "add_rule":
            op.rule.id = _unique_id(op.rule.id, {r.id for r in policy.rules})
        elif op.op == "replace_rule" and op.target_rule_id:
            op.rule.id = op.target_rule_id
    if op.op in ("replace_rule", "disable_rule") and op.target_rule_id not in {r.id for r in policy.rules}:
        return RuleOperation(op="cannot_express", explanation=f"I can't find a rule called {op.target_rule_id!r} to change.")
    if op.op == "add_fact" and op.fact is not None and (op.fact.id in known):
        return RuleOperation(op="cannot_express", explanation=f"A fact or field called {op.fact.id!r} already exists.")
    log.info("translate: %s -> %s (%s)", instruction[:60], op.op, op.explanation[:80])
    return op
