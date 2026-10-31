from types import SimpleNamespace

import pytest

from src.llm.schemas.operation import RuleOperation
from src.llm.translator import translate_instruction
from src.policy.operations import apply_operation
from src.policy.store import list_versions, load_policy
from src.schemas import Condition, Rule
from tests.test_policy_v1 import POLICY_DIR

USAGE = SimpleNamespace(model="m", input_tokens=10, output_tokens=5, latency_ms=1, cost_usd=0.0001)


class FakeClient:
    model = "fake"

    def __init__(self, scripted=None, available=True, error=None):
        self.scripted, self.available, self.error, self.calls = scripted, available, error, []

    def complete_json(self, system, user, schema, max_tokens=1024):
        from src.llm.client import LLMUnavailable
        if not self.available:
            raise LLMUnavailable()
        self.calls.append((system, user))
        if self.error:
            raise self.error
        return self.scripted, USAGE


def R(id, then, *conds, queue="reviewer"):
    return Rule(id=id, name=id, description=id, when=list(conds), then=then, queue=queue)


def test_translator_over_300_routes():
    policy = load_policy(1, policy_dir=POLICY_DIR)
    scripted = RuleOperation(op="add_rule", rule=R("over_300", "route", Condition(field="amount_usd", op=">", value=300)),
                             explanation="Requests above $300 go to a reviewer.")
    client = FakeClient(scripted)
    op = translate_instruction("From now on, anything over $300 comes to us.", policy, client)
    assert op.op == "add_rule" and op.rule.then == "route" and op.rule.when[0].value == 300 and op.position is None
    system, user = client.calls[0]
    assert "amount_usd" in system and "damage_photo_confirmed" in system and "fraud_flag_to_fraud_team" in system
    assert "anything over $300" in user


def test_translator_stolen_card_approves():
    policy = load_policy(1, policy_dir=POLICY_DIR)
    scripted = RuleOperation(op="add_rule", rule=R("stolen_card_through", "approve", Condition(field="card_confirmed_stolen", op="is_true")),
                             explanation="Confirmed stolen-card cases are approved in full.")
    op = translate_instruction("From now on, stolen-card cases go straight through.", policy, FakeClient(scripted))
    assert op.op == "add_rule" and op.rule.then == "approve" and op.rule.when[0].field == "card_confirmed_stolen"


def test_translator_cannot_express_leaves_policy_unchanged(tmp_path):
    policy = load_policy(1, policy_dir=POLICY_DIR)
    scripted = RuleOperation(op="add_rule", rule=R("angry", "route", Condition(field="mood", op="==", value="angry")), explanation="x")
    op = translate_instruction("Angry customers get a human.", policy, FakeClient(scripted))
    assert op.op == "cannot_express" and "mood" in op.explanation
    with pytest.raises(ValueError):
        apply_operation(policy, op, "x")
    assert list_versions(POLICY_DIR) == [1]


def test_translator_offline_returns_cannot_express():
    policy = load_policy(1, policy_dir=POLICY_DIR)
    op = translate_instruction("anything", policy, FakeClient(available=False))
    assert op.op == "cannot_express" and "unavailable" in op.explanation.lower()


def test_translator_model_error_returns_cannot_express():
    policy = load_policy(1, policy_dir=POLICY_DIR)
    op = translate_instruction("anything", policy, FakeClient(error=ValueError("bad json")))
    assert op.op == "cannot_express"


def test_translator_rejects_duplicate_rule_id_as_cannot_express():
    policy = load_policy(1, policy_dir=POLICY_DIR)
    scripted = RuleOperation(op="add_rule", rule=R("over_cap", "route", Condition(field="amount_usd", op=">", value=300)), explanation="x")
    op = translate_instruction("over 300", policy, FakeClient(scripted))
    assert op.op == "add_rule" and op.rule.id != "over_cap"   # id made unique instead of failing
