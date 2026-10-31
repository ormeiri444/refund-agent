from pathlib import Path

import pytest

from src import settings
from src.policy.engine import unknown_fact_provider
from src.policy.store import load_policy
from src.queue import (
    REVIEWERS,
    load_auto_approved,
    load_queue,
    queue_summary,
    record_reviewer_decision,
    reset_demo,
    run_system,
)
from src.schemas.review import ReviewerDecision

PENDING = Path(__file__).resolve().parents[1] / "data" / "pending.csv"
POLICY_DIR = Path(__file__).resolve().parents[1] / "policies"


@pytest.fixture
def ran(tmp_outputs):
    policy = load_policy(1, policy_dir=POLICY_DIR)
    decisions = run_system(PENDING, policy, unknown_fact_provider)
    return decisions


def decision(request_id, action="approve", amount=None, reviewer="S. Kwan"):
    return ReviewerDecision(request_id=request_id, action=action, amount_usd=amount, reason="looks fine",
                            reviewer=reviewer, decided_at="2026-10-31T10:00:00+00:00", policy_version=1)


def test_run_system_writes_system_decisions(ran, tmp_outputs):
    assert len(ran) == 20
    assert (tmp_outputs / "system_decisions.jsonl").exists()
    assert settings.SYSTEM_DECISIONS_PATH == tmp_outputs / "system_decisions.jsonl"


def test_queue_contains_only_routed_with_request_fields(ran):
    q = load_queue()
    routed = [d for d in ran if d.outcome == "route"]
    assert len(q) == len(routed) and set(q.request_id) == {d.request_id for d in routed}
    for col in ("amount_usd", "stated_reason", "customer_note", "support_note", "queue", "rule_id", "reason", "facts_used",
                "tenure_months", "prior_refunds_12m", "requested_at"):
        assert col in q.columns


def test_queue_oldest_first(ran):
    q = load_queue()
    assert list(q.requested_at) == sorted(q.requested_at)


def test_queue_excludes_decided(ran):
    first = load_queue().request_id.iloc[0]
    record_reviewer_decision(decision(first))
    q = load_queue()
    assert first not in set(q.request_id) and len(q) == len(ran) - sum(d.outcome == "approve" for d in ran) - 1


def test_second_decision_rejected(ran):
    rid = load_queue().request_id.iloc[0]
    record_reviewer_decision(decision(rid))
    with pytest.raises(ValueError, match=rid):
        record_reviewer_decision(decision(rid, action="reject"))


def test_partial_requires_amount_within_request(ran):
    row = load_queue().iloc[0]
    with pytest.raises(ValueError):
        record_reviewer_decision(decision(row.request_id, action="partial", amount=None))
    with pytest.raises(ValueError):
        record_reviewer_decision(decision(row.request_id, action="partial", amount=row.amount_usd + 1))
    record_reviewer_decision(decision(row.request_id, action="partial", amount=round(row.amount_usd / 2, 2)))


def test_auto_approved_table(ran):
    a = load_auto_approved()
    assert len(a) == sum(d.outcome == "approve" for d in ran) and (a.rule_id != "default_route").all()


def test_queue_summary_counts(ran):
    s = queue_summary()
    assert s["in_queue"] == sum(d.outcome == "route" for d in ran)
    assert s["fraud_queue"] == sum(d.queue == "fraud" for d in ran)
    assert s["auto_approved"] == sum(d.outcome == "approve" for d in ran)
    assert s["decided_by_reviewers"] == 0 and s["dollars_in_queue"] > 0
    record_reviewer_decision(decision(load_queue().request_id.iloc[0]))
    assert queue_summary()["decided_by_reviewers"] == 1


def test_reset_demo_removes_decisions_keeps_cache(ran, tmp_outputs):
    settings.CACHE_PATH.write_text('{"key": "k", "value": true, "quote": "q"}\n')
    record_reviewer_decision(decision(load_queue().request_id.iloc[0]))
    reset_demo()
    assert not settings.SYSTEM_DECISIONS_PATH.exists() and not settings.REVIEWER_DECISIONS_PATH.exists()
    assert settings.CACHE_PATH.exists() and load_queue().empty


def test_reviewers_list():
    assert REVIEWERS == ["S. Kwan", "R. Mizrahi", "D. Patel", "J. Alvarez"]
