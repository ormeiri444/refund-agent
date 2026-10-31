import math

import pandas as pd

from src.policy.engine import (
    decide,
    decide_frame,
    decisions_to_frame,
    evaluate_condition,
    rule_fact_ids,
    unknown_fact_provider,
)
from src.schemas import Condition, Decision, FactQuestion, FactValue, Policy, Rule


def P(rules, facts=(), version=9):
    return Policy(version=version, changelog="t", created_at="2026-10-30", facts=list(facts), rules=rules)


def R(id, then, *conds, queue="reviewer", enabled=True):
    return Rule(id=id, name=id, description=f"desc of {id}", when=list(conds), then=then, queue=queue, enabled=enabled)


def C(field, op, value=None):
    return Condition(field=field, op=op, value=value)


BASE_ROW = {
    "request_id": "RF-1", "source": "web_form", "tenure_months": 12, "prior_refunds_12m": 0, "amount_usd": 30.0,
    "category": "apparel", "payment_method": "card", "stated_reason": "wrong_size", "days_since_delivery": 3,
    "fraud_flag": False, "has_note": False,
}


class RecordingProvider:
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls: list[list[str]] = []

    def __call__(self, row, questions):
        ids = [q.id for q in questions]
        self.calls.append(ids)
        return {i: self.answers.get(i, FactValue(value=None)) for i in ids}


# ---------------------------------------------------------------- conditions

def test_evaluate_numeric_ops():
    row = {"amount_usd": 50.0}
    assert evaluate_condition(C("amount_usd", "<=", 50), row, {}) is True
    assert evaluate_condition(C("amount_usd", "<", 50), row, {}) is False
    assert evaluate_condition(C("amount_usd", ">", 10), row, {}) is True
    assert evaluate_condition(C("amount_usd", "==", 50), row, {}) is True
    assert evaluate_condition(C("amount_usd", "!=", 50), row, {}) is False


def test_evaluate_unknown_value_is_unknown_except_is_unknown():
    for missing in (None, float("nan"), pd.NA):
        row = {"amount_usd": missing}
        assert evaluate_condition(C("amount_usd", "<=", 50), row, {}) is None
        assert evaluate_condition(C("amount_usd", "==", 50), row, {}) is None
        assert evaluate_condition(C("amount_usd", "is_unknown"), row, {}) is True
    assert evaluate_condition(C("amount_usd", "is_unknown"), {"amount_usd": 5.0}, {}) is False


def test_evaluate_in_and_not_in():
    row = {"stated_reason": "wrong_size"}
    assert evaluate_condition(C("stated_reason", "in", ["wrong_size", "changed_mind"]), row, {}) is True
    assert evaluate_condition(C("stated_reason", "not_in", ["wrong_size"]), row, {}) is False


def test_evaluate_bool_ops_on_fraud_flag():
    assert evaluate_condition(C("fraud_flag", "is_true"), {"fraud_flag": True}, {}) is True
    assert evaluate_condition(C("fraud_flag", "is_false"), {"fraud_flag": False}, {}) is True
    assert evaluate_condition(C("fraud_flag", "is_true"), {"fraud_flag": None}, {}) is None
    assert evaluate_condition(C("fraud_flag", "is_unknown"), {"fraud_flag": None}, {}) is True


def test_evaluate_fact_conditions():
    facts = {"photo": FactValue(value=True, quote="photo attached")}
    assert evaluate_condition(C("photo", "is_true"), {}, facts) is True
    assert evaluate_condition(C("photo", "is_false"), {}, facts) is False
    assert evaluate_condition(C("photo", "is_true"), {}, {"photo": FactValue(value=None)}) is None
    assert evaluate_condition(C("photo", "is_true"), {}, {}) is None  # not provided at all


def test_numeric_op_on_non_numeric_is_unknown():
    assert evaluate_condition(C("amount_usd", "<=", 50), {"amount_usd": "abc"}, {}) is None


# ---------------------------------------------------------------- rules

def test_first_matching_rule_wins():
    policy = P([R("a", "route", C("amount_usd", ">", 100)), R("b", "approve", C("amount_usd", "<=", 100)),
                R("c", "route", C("amount_usd", "<=", 100))])
    d = decide(BASE_ROW, policy)
    assert d.outcome == "approve" and d.rule_id == "b" and d.reason == "desc of b"
    assert d.policy_version == 9 and d.queue is None and d.amount_usd == 30.0


def test_default_route_when_nothing_matches():
    d = decide(BASE_ROW, P([R("a", "approve", C("amount_usd", ">", 1000))]))
    assert d.outcome == "route" and d.queue == "reviewer" and d.rule_id == "default_route"
    assert d.reason == "No rule matched; needs a person."


def test_route_decision_carries_queue():
    d = decide({**BASE_ROW, "fraud_flag": True}, P([R("f", "route", C("fraud_flag", "is_true"), queue="fraud")]))
    assert d.outcome == "route" and d.queue == "fraud"


def test_unknown_fraud_flag_routes():
    policy = P([R("fraud", "route", C("fraud_flag", "is_true"), queue="fraud"),
                R("fraud_unknown", "route", C("fraud_flag", "is_unknown")),
                R("ok", "approve", C("amount_usd", "<=", 100))])
    assert decide({**BASE_ROW, "fraud_flag": None}, policy).rule_id == "fraud_unknown"


def test_unknown_amount_routes():
    policy = P([R("amt_unknown", "route", C("amount_usd", "is_unknown")), R("ok", "approve", C("amount_usd", "<=", 100))])
    assert decide({**BASE_ROW, "amount_usd": float("nan")}, policy).rule_id == "amt_unknown"


def test_unknown_condition_never_matches_an_approve_rule():
    policy = P([R("ok", "approve", C("amount_usd", "<=", 100))])
    d = decide({**BASE_ROW, "amount_usd": None}, policy)
    assert d.outcome == "route" and d.rule_id == "default_route"


def test_disabled_rule_skipped():
    policy = P([R("off", "approve", C("amount_usd", "<=", 100), enabled=False)])
    assert decide(BASE_ROW, policy).rule_id == "default_route"


def test_rule_fact_ids():
    rule = R("x", "approve", C("amount_usd", "<=", 50), C("photo", "is_true"), C("stolen", "is_false"))
    assert rule_fact_ids(rule, {"photo", "stolen"}) == ["photo", "stolen"]


# ---------------------------------------------------------------- facts, lazily

FACTS = [FactQuestion(id="photo", question="Photo attached?"), FactQuestion(id="stolen", question="Card stolen?")]


def test_fact_provider_called_lazily_only_when_column_conditions_pass():
    policy = P([R("big_photo", "approve", C("amount_usd", ">", 100), C("photo", "is_true"))], facts=FACTS)
    prov = RecordingProvider({"photo": FactValue(value=True, quote="photo ok")})
    decide(BASE_ROW, policy, prov)                       # amount 30: column cond False
    assert prov.calls == []
    d = decide({**BASE_ROW, "amount_usd": 150.0}, policy, prov)
    assert prov.calls == [["photo"]]                     # asked exactly for the fact the rule needs
    assert d.outcome == "approve" and d.facts_used == {"photo": FactValue(value=True, quote="photo ok")}


def test_facts_asked_once_per_request_across_rules():
    policy = P([R("a", "approve", C("photo", "is_true"), C("amount_usd", ">", 1000)),
                R("b", "approve", C("photo", "is_true"))], facts=FACTS)
    prov = RecordingProvider({"photo": FactValue(value=True)})
    d = decide(BASE_ROW, policy, prov)
    assert prov.calls == [["photo"]] and d.rule_id == "b"


def test_unknown_fact_never_approves():
    policy = P([R("photo_ok", "approve", C("photo", "is_true"))], facts=FACTS)
    d = decide(BASE_ROW, policy, RecordingProvider())    # provider answers unknown
    assert d.outcome == "route" and d.rule_id == "default_route"
    assert d.facts_used["photo"].value is None


def test_unknown_fact_provider_returns_none_for_every_question():
    out = unknown_fact_provider(BASE_ROW, FACTS)
    assert set(out) == {"photo", "stolen"} and all(v.value is None for v in out.values())


# ---------------------------------------------------------------- frames

def test_decide_frame_and_to_frame(pending_df):
    policy = P([R("small", "approve", C("amount_usd", "<=", 50), C("fraud_flag", "is_false"))])
    decisions = decide_frame(pending_df, policy)
    assert len(decisions) == len(pending_df) and all(isinstance(d, Decision) for d in decisions)
    frame = decisions_to_frame(decisions)
    assert list(frame.columns)[:6] == ["request_id", "outcome", "queue", "rule_id", "rule_name", "reason"]
    assert set(frame.outcome) <= {"approve", "route"}
    assert frame.request_id.tolist() == pending_df.request_id.tolist()
    approved = frame[frame.outcome == "approve"]
    assert (pending_df.set_index("request_id").loc[approved.request_id, "amount_usd"] <= 50).all()


def test_decide_handles_pandas_missing_types(pending_df):
    row = pending_df.iloc[0].to_dict()
    row["tenure_months"] = pd.NA
    d = decide(row, P([R("t", "approve", C("tenure_months", ">=", 1))]))
    assert d.rule_id == "default_route"
    assert d.amount_usd is None or not math.isnan(d.amount_usd)
