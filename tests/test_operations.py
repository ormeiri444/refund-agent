import pytest
from pydantic import ValidationError

from src.llm.schemas.operation import RuleOperation
from src.policy.operations import apply_operation, resolve_position
from src.schemas import Condition, FactQuestion, Policy, Rule


def P(rules, facts=(), version=1):
    return Policy(version=version, changelog="base", created_at="2026-10-31", facts=list(facts), rules=rules)


def R(id, then, *conds, queue="reviewer"):
    return Rule(id=id, name=id, description=id, when=list(conds), then=then, queue=queue)


GUARD = R("fraud_guard", "route", Condition(field="fraud_flag", op="is_true"), queue="fraud")
APPROVE = R("simple", "approve", Condition(field="amount_usd", op="<=", value=50))
BASE = P([GUARD, APPROVE])


def test_resolve_position_defaults_by_outcome():
    assert resolve_position(R("x", "route"), None) == "top"
    assert resolve_position(R("x", "approve"), None) == "bottom"
    assert resolve_position(R("x", "approve"), "top") == "top"


def test_add_route_rule_lands_on_top_and_bumps_version():
    op = RuleOperation(op="add_rule", rule=R("over_300", "route", Condition(field="amount_usd", op=">", value=300)), explanation="e")
    new = apply_operation(BASE, op, changelog="over 300 to people")
    assert new.version == 2 and new.changelog == "over 300 to people" and new.created_at
    assert [r.id for r in new.rules] == ["over_300", "fraud_guard", "simple"]
    assert [r.id for r in BASE.rules] == ["fraud_guard", "simple"]   # original untouched


def test_add_approve_rule_lands_at_bottom():
    op = RuleOperation(op="add_rule", rule=R("tiny", "approve", Condition(field="amount_usd", op="<=", value=10)), explanation="e")
    assert [r.id for r in apply_operation(BASE, op, "x").rules] == ["fraud_guard", "simple", "tiny"]


def test_add_rule_explicit_top_overrides_default():
    op = RuleOperation(op="add_rule", rule=R("stolen", "approve", Condition(field="fraud_flag", op="is_true")), position="top", explanation="e")
    assert apply_operation(BASE, op, "x").rules[0].id == "stolen"


def test_replace_rule_swaps_in_place():
    changed = R("simple", "approve", Condition(field="amount_usd", op="<=", value=25))
    op = RuleOperation(op="replace_rule", target_rule_id="simple", rule=changed, explanation="e")
    new = apply_operation(BASE, op, "x")
    assert [r.id for r in new.rules] == ["fraud_guard", "simple"] and new.rules[1].when[0].value == 25


def test_disable_rule():
    new = apply_operation(BASE, RuleOperation(op="disable_rule", target_rule_id="simple", explanation="e"), "x")
    assert new.rules[1].enabled is False and BASE.rules[1].enabled is True


def test_add_fact_appends_question():
    op = RuleOperation(op="add_fact", fact=FactQuestion(id="police_report", question="Does the note mention a police report?"), explanation="e")
    new = apply_operation(BASE, op, "x")
    assert new.fact_ids() == ["police_report"]


def test_cannot_express_raises():
    with pytest.raises(ValueError, match="cannot"):
        apply_operation(BASE, RuleOperation(op="cannot_express", explanation="no fact covers mood"), "x")


def test_rule_with_unknown_field_rejected():
    op = RuleOperation(op="add_rule", rule=R("mood", "route", Condition(field="mood", op="==", value="angry")), explanation="e")
    with pytest.raises(ValidationError, match="mood"):
        apply_operation(BASE, op, "x")


def test_duplicate_rule_id_rejected():
    op = RuleOperation(op="add_rule", rule=R("simple", "route"), explanation="e")
    with pytest.raises(ValidationError, match="simple"):
        apply_operation(BASE, op, "x")


def test_unknown_target_rule_rejected():
    with pytest.raises(ValueError, match="nope"):
        apply_operation(BASE, RuleOperation(op="disable_rule", target_rule_id="nope", explanation="e"), "x")


def test_approve_rule_at_bottom_never_outranks_fraud_guard():
    from src.policy.engine import decide
    op = RuleOperation(op="add_rule", rule=R("small_size", "approve", Condition(field="stated_reason", op="==", value="wrong_size"),
                                             Condition(field="amount_usd", op="<=", value=30)), explanation="e")
    new = apply_operation(BASE, op, "x")
    row = {"request_id": "RF-X", "stated_reason": "wrong_size", "amount_usd": 25.0, "fraud_flag": True}
    assert decide(row, new).queue == "fraud"


def test_proposal_notes_reflect_net_difference_not_history():
    from src.policy.operations import proposal_notes
    live = P([GUARD, APPROVE, R("other", "route", Condition(field="amount_usd", op=">", value=300))])
    # disable 'simple', re-enable it, then disable 'other': only 'other' differs from live
    p1 = apply_operation(live, RuleOperation(op="disable_rule", target_rule_id="simple", explanation=""), "")
    p2 = apply_operation(p1, RuleOperation(op="replace_rule", target_rule_id="simple", rule=APPROVE.model_copy(update={"enabled": True}), explanation=""), "")
    p3 = apply_operation(p2, RuleOperation(op="disable_rule", target_rule_id="other", explanation=""), "")
    notes = proposal_notes(live, p3)
    assert notes == ["disabled rule other"]
    assert proposal_notes(live, p2) == []                         # back to the live state: nothing to report


def test_proposal_notes_cover_added_replaced_and_facts():
    from src.policy.operations import proposal_notes
    added = R("over_300", "route", Condition(field="amount_usd", op=">", value=300))
    p1 = apply_operation(BASE, RuleOperation(op="add_rule", rule=added, explanation=""), "")
    p2 = apply_operation(p1, RuleOperation(op="replace_rule", target_rule_id="simple",
                                           rule=APPROVE.model_copy(update={"when": [Condition(field="amount_usd", op="<=", value=25)]}), explanation=""), "")
    p3 = apply_operation(p2, RuleOperation(op="add_fact", fact=FactQuestion(id="police_report", question="Police report?"), explanation=""), "")
    notes = proposal_notes(BASE, p3)
    assert any(n.startswith("added rule over_300") for n in notes)
    assert any(n.startswith("changed rule simple") for n in notes)
    assert any(n.startswith("added question police_report") for n in notes)
