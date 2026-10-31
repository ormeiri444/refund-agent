import pandas as pd
import pytest

from src.policy.backtest import (
    bad_reason,
    cap_table,
    diff_policies,
    format_backtest,
    ground_truth,
    overpaid_usd,
    run_backtest,
)
from src.policy.store import load_policy
from src.schemas import Condition, Policy, Rule
from src.schemas.backtest import BacktestResult, PolicyDiff
from tests.test_policy_v1 import POLICY_DIR


def P(rules, version=1, facts=()):
    return Policy(version=version, changelog="t", created_at="2026-10-31", facts=list(facts), rules=rules)


def R(id, then, *conds):
    return Rule(id=id, name=id, description=id, when=list(conds), then=then)


# ---------------------------------------------------------------- ground truth

def test_ground_truth_flags(history_df):
    gt = ground_truth(history_df).set_index("request_id")
    assert gt.loc["RF-2074", "chargeback"] == True and gt.loc["RF-2074", "bad"] == True
    assert gt.loc["RF-2074", "detectable"] == False          # no note, no flag
    assert gt.loc["RF-1006", "bad"] == True and gt.loc["RF-1006", "detectable"] == True  # rejected, has a note
    assert gt.loc["RF-1008", "final_decision"] == "approved"  # rejected then overturned
    assert gt.loc["RF-1008", "bad"] == False
    assert gt.loc["RF-2018", "final_decision"] == "partial" and gt.loc["RF-2018", "bad"] == True
    assert gt.loc["RF-2007", "bad"] == False                  # fraud flag, but the fraud team confirmed: correct per policy note 5
    assert gt.loc["RF-2007", "fraud_confirmed"] == True
    assert gt.loc["RF-1014", "bad"] == True                   # fraud flag approved with no fraud-team confirmation
    assert gt.loc["RF-2111", "bad"] == True                   # fraud flag + chargeback
    assert gt.loc["RF-1001", "bad"] == False


def test_bad_reason_words():
    assert bad_reason(chargeback=True, fraud=False, final="approved") == "chargeback"
    assert bad_reason(chargeback=False, fraud=True, final="approved") == "fraud flag, not confirmed by fraud team"
    assert bad_reason(chargeback=False, fraud=False, final="rejected") == "reviewer rejected"
    assert bad_reason(chargeback=False, fraud=False, final="partial") == "reviewer paid partial"
    assert bad_reason(chargeback=True, fraud=True, final="rejected") == "chargeback, fraud flag, not confirmed by fraud team, reviewer rejected"


@pytest.mark.parametrize("amount,note,expected", [
    (78.0, "30 percent issued", 54.6), (160.0, "50 percent issued", 80.0),
    (85.0, "shipping refunded only", 85.0), (100.0, "", 100.0),
])
def test_overpaid_usd(amount, note, expected):
    assert overpaid_usd(amount, note) == pytest.approx(expected)


# ---------------------------------------------------------------- backtest

def test_backtest_counts_consistent(history_df):
    r = run_backtest(history_df, load_policy(1, policy_dir=POLICY_DIR))
    assert isinstance(r, BacktestResult)
    assert r.n == len(history_df) == r.n_auto_approve + sum(r.routing_reasons.values())
    assert 0 < r.auto_approve_rate < 1 and r.dollars_auto_approved > 0
    assert r.reviewer_minutes_saved <= history_df.review_minutes.sum()
    assert r.weeks > 10 and r.weekly_auto_dollars == pytest.approx(r.dollars_auto_approved / r.weeks)
    assert {b.request_id for b in r.bad_detectable}.isdisjoint({b.request_id for b in r.bad_undetectable})


def test_backtest_v1_offline_has_no_detectable_bad(history_df):
    r = run_backtest(history_df, load_policy(1, policy_dir=POLICY_DIR))
    assert r.bad_detectable == [] and r.verdict == "PASS"
    assert [b.request_id for b in r.bad_undetectable] == ["RF-2074"]


def test_backtest_fails_on_detectable_bad(history_df):
    loose = P([R("all_wrong_item", "approve", Condition(field="stated_reason", op="==", value="wrong_item"))])
    r = run_backtest(history_df, loose)
    ids = [b.request_id for b in r.bad_detectable]
    assert {"RF-1006", "RF-2065", "RF-2054"} <= set(ids) and r.verdict == "FAIL"
    assert all(b.reason == "reviewer rejected" for b in r.bad_detectable if b.request_id == "RF-1006")


def test_backtest_agreement_and_overpaid(history_df):
    partial_only = P([R("late", "approve", Condition(field="stated_reason", op="==", value="late_delivery"))])
    r = run_backtest(history_df, partial_only)
    assert r.overpaid_partial_usd > 0 and r.agreement_rate < 1


def test_cap_table_rows(history_df):
    rows = cap_table(history_df, load_policy(1, policy_dir=POLICY_DIR), caps=[54, 100, 200])
    assert [row.cap for row in rows] == [54, 100, 200]
    assert rows[0].n_auto_approve <= rows[1].n_auto_approve <= rows[2].n_auto_approve


def test_format_backtest_mentions_verdict_and_ids(history_df):
    r = run_backtest(history_df, load_policy(1, policy_dir=POLICY_DIR))
    text = format_backtest(r)
    assert "PASS" in text and "RF-2074" in text and "minutes" in text and "per week" in text


# ---------------------------------------------------------------- diff

def test_diff_policies_flips(history_df):
    old = P([R("ok", "approve", Condition(field="amount_usd", op="<=", value=100))], version=1)
    new = P([R("ok", "approve", Condition(field="amount_usd", op="<=", value=50))], version=2)
    d = diff_policies(history_df, old, new)
    assert isinstance(d, PolicyDiff)
    assert d.to_auto == [] and len(d.to_human) == d.n_flipped > 0
    assert d.dollars_to_human > 0 and d.dollars_to_auto == 0
    assert "RF-2065" in d.newly_caught_detectable      # $58 wrong_item rejected: old approved it, new routes it
    assert d.newly_bad_detectable == []
    assert len(d.per_request) == d.n_flipped


def test_diff_policies_newly_bad(history_df):
    old = load_policy(1, policy_dir=POLICY_DIR)
    new = P(old.rules + [R("all_wrong_item", "approve", Condition(field="stated_reason", op="==", value="wrong_item"))],
            version=2, facts=old.facts)
    d = diff_policies(history_df, old, new)
    assert "RF-1006" in d.newly_bad_detectable and d.blocks_publish is True
