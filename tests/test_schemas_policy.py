import pytest
from pydantic import ValidationError

from src.schemas.policy import REQUEST_FIELDS, Condition, FactQuestion, Policy, Rule


def make_policy(rules, facts=()):
    return Policy(version=1, changelog="test", created_at="2026-10-30", facts=list(facts), rules=rules)


def test_request_fields_cover_normalized_columns():
    assert {"amount_usd", "stated_reason", "fraud_flag", "tenure_months", "prior_refunds_12m",
            "days_since_delivery", "category", "payment_method", "source", "has_note", "duplicate_conflict"} <= REQUEST_FIELDS


def test_condition_field_must_be_known():
    rule = Rule(id="r", name="r", description="", when=[Condition(field="mood", op="==", value="angry")], then="route")
    with pytest.raises(ValidationError, match="mood"):
        make_policy([rule])


def test_fact_field_allowed_when_declared():
    rule = Rule(id="r", name="r", description="", when=[Condition(field="mood", op="is_true")], then="route")
    policy = make_policy([rule], facts=[FactQuestion(id="mood", question="Is the customer angry?")])
    assert policy.fact_ids() == ["mood"]


def test_rule_ids_unique():
    r1 = Rule(id="same", name="a", description="", when=[], then="route")
    r2 = Rule(id="same", name="b", description="", when=[], then="route")
    with pytest.raises(ValidationError, match="same"):
        make_policy([r1, r2])


def test_fact_id_cannot_shadow_request_field():
    with pytest.raises(ValidationError, match="amount_usd"):
        make_policy([], facts=[FactQuestion(id="amount_usd", question="?")])


def test_invalid_op_rejected():
    with pytest.raises(ValidationError):
        Condition(field="amount_usd", op="contains", value="x")


def test_describe_rule_plain_english():
    rule = Rule(id="small", name="Small and safe", description="", then="approve", when=[
        Condition(field="amount_usd", op="<=", value=60),
        Condition(field="prior_refunds_12m", op="==", value=0),
    ])
    policy = make_policy([rule])
    assert policy.describe_rule(rule) == \
        "IF amount (USD) is at most 60 AND prior refunds in last 12 months equals 0 THEN approve"


def test_describe_rule_route_with_queue_and_fact():
    rule = Rule(id="f", name="f", description="", then="route", queue="fraud", when=[
        Condition(field="fraud_flag", op="is_true"),
        Condition(field="stated_reason", op="in", value=["never_arrived", "arrived_damaged"]),
    ])
    policy = make_policy([rule])
    assert policy.describe_rule(rule) == \
        "IF fraud flag is yes AND stated reason is one of never_arrived, arrived_damaged THEN route to fraud queue"


def test_describe_rule_with_no_conditions():
    rule = Rule(id="all", name="all", description="", when=[], then="route")
    assert make_policy([rule]).describe_rule(rule) == "ALWAYS route to reviewer queue"
