"""Replay a policy on history: how much it would automate, and what it would have got wrong.

Ground truth comes from what happened after each historical decision (outcome_note) and
from the reviewers' final decisions. A "bad" auto-approval is one the policy would approve
where the case later charged back, carried a fraud flag the fraud team did not confirm, or a
reviewer rejected / partially refunded it (after appeals). A bad case is "detectable" when a note or a fraud flag was there
to be read; the rest is accepted risk and listed separately.
"""
from __future__ import annotations

import re

import pandas as pd

from src.logging_setup import get_logger
from src.policy.engine import decide_frame, decisions_to_frame, unknown_fact_provider
from src.schemas.backtest import BacktestResult, BadApproval, CapRow, PolicyDiff
from src.schemas.decision import FactProvider
from src.schemas.policy import Policy

log = get_logger("backtest")

DEFAULT_CAPS = [54, 60, 80, 100, 150, 200]
CAP_RULE_ID = "over_cap"
_RE_PERCENT = re.compile(r"(\d+)\s*percent")


# ---------------------------------------------------------------- ground truth

def bad_reason(chargeback: bool, fraud: bool, final: str) -> str:
    parts = []
    if chargeback:
        parts.append("chargeback")
    if fraud:
        parts.append("fraud flag, not confirmed by fraud team")
    if final == "rejected":
        parts.append("reviewer rejected")
    elif final == "partial":
        parts.append("reviewer paid partial")
    return ", ".join(parts)


def overpaid_usd(amount: float, outcome_note: str) -> float:
    """Dollars overpaid if we refund in full what a reviewer only partly refunded."""
    m = _RE_PERCENT.search(outcome_note or "")
    if m:
        return round(amount * (1 - int(m.group(1)) / 100), 2)
    return float(amount)


def ground_truth(history: pd.DataFrame) -> pd.DataFrame:
    df = history.copy()
    note = df["outcome_note"].fillna("").str.lower()
    df["chargeback"] = note.str.contains("chargeback")
    df["overturned"] = note.str.contains("overturned|on appeal")
    df["final_decision"] = df["decision"].where(~df["overturned"], "approved")
    df["fraud_confirmed"] = note.str.contains("fraud team confirmed")
    # A fraud-flagged approval is correct when the fraud team confirmed the stolen card (policy note 5); bad otherwise.
    df["fraud"] = df["fraud_flag"].map(lambda v: v is True) & ~df["fraud_confirmed"]
    df["bad"] = df["chargeback"] | df["fraud"] | df["final_decision"].isin(["rejected", "partial"])
    df["detectable"] = df["bad"] & (df["has_note"] | df["fraud_flag"].map(lambda v: v is True))
    df["bad_reason"] = [bad_reason(c, f, d) for c, f, d in zip(df["chargeback"], df["fraud"], df["final_decision"])]
    return df


# ---------------------------------------------------------------- backtest

def _replay(history: pd.DataFrame, policy: Policy, fact_provider: FactProvider) -> pd.DataFrame:
    gt = ground_truth(history)
    frame = decisions_to_frame(decide_frame(gt, policy, fact_provider))
    merged = gt.merge(frame[["request_id", "outcome", "queue", "rule_id", "reason", "facts_used"]], on="request_id")
    return merged


def _bad_list(df: pd.DataFrame, detectable: bool) -> list[BadApproval]:
    sub = df[(df.outcome == "approve") & df.bad & (df.detectable == detectable)]
    return [BadApproval(request_id=r.request_id, amount_usd=r.amount_usd, rule_id=r.rule_id, reason=r.bad_reason,
                        detectable=detectable) for r in sub.itertuples()]


def run_backtest(history: pd.DataFrame, policy: Policy, fact_provider: FactProvider = unknown_fact_provider) -> BacktestResult:
    df = _replay(history, policy, fact_provider)
    approved = df[df.outcome == "approve"]
    routed = df[df.outcome == "route"]
    human = df[df.decided_by != "auto"]
    weeks = max((df.requested_at.max() - df.requested_at.min()).days / 7, 1.0)
    dollars = float(approved.amount_usd.sum())
    partial_rows = approved[approved.final_decision == "partial"]
    overpaid = float(sum(overpaid_usd(a, n) for a, n in zip(partial_rows.amount_usd, partial_rows.outcome_note.fillna(""))))
    bad_det, bad_undet = _bad_list(df, True), _bad_list(df, False)
    result = BacktestResult(
        policy_version=policy.version, n=len(df), n_auto_approve=len(approved),
        auto_approve_rate=len(approved) / len(df) if len(df) else 0.0,
        dollars_auto_approved=dollars,
        reviewer_minutes_saved=float(approved.review_minutes.fillna(0).sum()),
        remaining_reviewer_minutes=float(routed.review_minutes.fillna(0).sum()),
        agreement_rate=float((approved.final_decision == "approved").mean()) if len(approved) else 1.0,
        overpaid_partial_usd=overpaid,
        bad_detectable=bad_det, bad_undetectable=bad_undet,
        routing_reasons=routed.rule_id.value_counts().to_dict(),
        weeks=weeks, weekly_auto_dollars=dollars / weeks,
        verdict="FAIL" if bad_det else "PASS",
        decisions=df[["request_id", "outcome", "rule_id", "amount_usd", "final_decision", "bad", "detectable", "bad_reason"]]
        .to_dict(orient="records"),
    )
    log.info("backtest policy=v%d auto=%d/%d bad_detectable=%d bad_undetectable=%d verdict=%s",
             policy.version, result.n_auto_approve, result.n, len(bad_det), len(bad_undet), result.verdict)
    _ = human  # kept for readability of the minutes definition above
    return result


def with_cap(policy: Policy, cap: float) -> Policy:
    p = policy.model_copy(deep=True)
    for rule in p.rules:
        if rule.id == CAP_RULE_ID:
            rule.when[0].value = cap
    return p


def cap_table(history: pd.DataFrame, policy: Policy, caps: list[float] = DEFAULT_CAPS,
              fact_provider: FactProvider = unknown_fact_provider) -> list[CapRow]:
    rows = []
    for cap in caps:
        r = run_backtest(history, with_cap(policy, cap), fact_provider)
        rows.append(CapRow(cap=cap, n_auto_approve=r.n_auto_approve, auto_approve_rate=r.auto_approve_rate,
                           dollars_auto_approved=r.dollars_auto_approved, reviewer_minutes_saved=r.reviewer_minutes_saved,
                           n_bad_detectable=len(r.bad_detectable), n_bad_undetectable=len(r.bad_undetectable)))
    return rows


# ---------------------------------------------------------------- diff

def diff_policies(df: pd.DataFrame, old: Policy, new: Policy, fact_provider: FactProvider = unknown_fact_provider) -> PolicyDiff:
    a = _replay(df, old, fact_provider).set_index("request_id")
    b = _replay(df, new, fact_provider).set_index("request_id")
    flipped = a.index[a.outcome != b.outcome]
    to_auto = [i for i in flipped if b.loc[i, "outcome"] == "approve"]
    to_human = [i for i in flipped if b.loc[i, "outcome"] == "route"]
    bad = a["bad"] if "bad" in a else pd.Series(False, index=a.index)
    det = a["detectable"]
    newly_bad = [i for i in to_auto if bad.loc[i]]
    newly_caught = [i for i in to_human if bad.loc[i]]
    per_request = [{
        "request_id": i, "amount_usd": a.loc[i, "amount_usd"], "old_outcome": a.loc[i, "outcome"], "new_outcome": b.loc[i, "outcome"],
        "old_rule": a.loc[i, "rule_id"], "new_rule": b.loc[i, "rule_id"], "bad": bool(bad.loc[i]), "bad_reason": a.loc[i, "bad_reason"],
    } for i in flipped]
    nbd = [i for i in newly_bad if det.loc[i]]
    return PolicyDiff(
        old_version=old.version, new_version=new.version, n_flipped=len(flipped), to_auto=to_auto, to_human=to_human,
        dollars_to_auto=float(a.loc[to_auto, "amount_usd"].sum()), dollars_to_human=float(a.loc[to_human, "amount_usd"].sum()),
        newly_bad_detectable=nbd, newly_bad_undetectable=[i for i in newly_bad if not det.loc[i]],
        newly_caught_detectable=[i for i in newly_caught if det.loc[i]],
        newly_caught_undetectable=[i for i in newly_caught if not det.loc[i]],
        blocks_publish=bool(nbd), per_request=per_request,
    )


# ---------------------------------------------------------------- text

def format_backtest(r: BacktestResult) -> str:
    lines = [
        f"Backtest of policy v{r.policy_version} on {r.n} historical requests ({r.weeks:.1f} weeks)",
        f"  auto-approved        {r.n_auto_approve:>4}  ({r.auto_approve_rate:.0%})   ${r.dollars_auto_approved:,.2f}",
        f"  expected per week    ${r.weekly_auto_dollars:,.2f} auto-approved (baseline for the rollback trigger)",
        f"  reviewer minutes     saved {r.reviewer_minutes_saved:.0f}, still needed {r.remaining_reviewer_minutes:.0f}",
        f"  agreement            {r.agreement_rate:.0%} of auto-approvals were also approved by the final human decision",
        f"  overpaid on partials ${r.overpaid_partial_usd:,.2f}",
        "  bad auto-approvals, detectable (a note or flag was there to read):",
    ]
    lines += [f"    RED    {b.request_id}  ${b.amount_usd:,.2f}  rule={b.rule_id}  {b.reason}" for b in r.bad_detectable] or ["    none"]
    lines.append("  bad auto-approvals, undetectable (nothing in the request could have caught it):")
    lines += [f"    YELLOW {b.request_id}  ${b.amount_usd:,.2f}  rule={b.rule_id}  {b.reason}" for b in r.bad_undetectable] or ["    none"]
    lines.append("  still routed to people, by rule:")
    lines += [f"    {n:>4}  {rule}" for rule, n in sorted(r.routing_reasons.items(), key=lambda kv: -kv[1])]
    lines.append(f"VERDICT: {r.verdict}")
    return "\n".join(lines)


def format_cap_table(rows: list[CapRow]) -> str:
    out = ["| cap | auto-approved | rate | dollars | reviewer minutes saved | bad (detectable) | bad (undetectable) |",
           "|---|---|---|---|---|---|---|"]
    for c in rows:
        out.append(f"| ${c.cap:,.0f} | {c.n_auto_approve} | {c.auto_approve_rate:.0%} | ${c.dollars_auto_approved:,.0f} | "
                   f"{c.reviewer_minutes_saved:.0f} | {c.n_bad_detectable} | {c.n_bad_undetectable} |")
    return "\n".join(out)
