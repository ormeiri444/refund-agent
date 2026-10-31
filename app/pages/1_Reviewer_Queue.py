"""Reviewer Queue: the requests the system did not take, with everything a person needs to decide."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app._shared import fact_lines, live_policy, money, sidebar_status  # noqa: E402
from src.policy_notes import notes_for  # noqa: E402
from src.queue import REVIEWERS, load_auto_approved, load_queue, load_reviewer_decisions, record_reviewer_decision  # noqa: E402
from src.schemas.review import ReviewerDecision  # noqa: E402

st.set_page_config(page_title="Reviewer Queue", page_icon="🗂", layout="wide")
sidebar_status()
st.title("Reviewer Queue")

policy = live_policy()
queue = load_queue()
if queue.empty:
    st.info("Nothing waiting. Run the system from the Home page, or every routed request has been decided.")
    st.stop()

# ---- filters and the list
which = st.radio("Show", ["all", "reviewer", "fraud"], horizontal=True, key="queue_filter",
                 help="Fraud-flagged requests land in the fraud queue (policy note 5).")
shown = queue if which == "all" else queue[queue.queue == which]
st.caption(f"{len(shown)} waiting, {money(shown.amount_usd.sum())}. Oldest first.")
table = shown[["request_id", "requested_at", "amount_usd", "stated_reason", "queue", "rule_name", "reason"]].copy()
table["requested_at"] = table["requested_at"].dt.date.astype(str)
st.dataframe(table, hide_index=True, width="stretch")

# ---- one request
options = list(shown.request_id)
selected = st.selectbox("Open a request", options, key="selected_request")
row = shown.set_index("request_id").loc[selected]

left, right = st.columns([3, 2])
with left:
    st.subheader(f"{selected} · {money(row.amount_usd)} · {row.stated_reason.replace('_', ' ')}")
    st.markdown(f"**Why it is here:** {row.reason}")
    rule = next((r for r in policy.rules if r.id == row.rule_id), None) if policy else None
    st.caption(f"Rule `{row.rule_id}` (policy v{int(row.policy_version)}): " + (policy.describe_rule(rule) if rule else "no rule matched"))
    facts = fact_lines(row.facts_used)
    st.markdown("**What the notes say** (read by the model, with the words it relied on):")
    st.markdown("\n".join(f"- {line}" for line in facts) if facts else "- no note-based fact was needed for this rule")
    st.markdown("**Customer wrote:** " + (row.customer_note or "_nothing_"))
    st.markdown("**Support wrote:** " + (row.support_note or "_nothing_"))
    for number, text in notes_for(row.stated_reason, row.fraud_flag):
        st.info(f"Policy note {number}: {text}")
with right:
    st.markdown("**Request details**")
    details = {
        "requested": str(row.requested_at.date()) if hasattr(row.requested_at, "date") else str(row.requested_at),
        "source": row.source, "category": row.category, "payment": row.payment_method,
        "days since delivery": row.days_since_delivery, "fraud flag": {True: "yes", False: "no"}.get(row.fraud_flag, "unknown"),
        "customer": row.customer_id, "tenure (months)": row.tenure_months, "refunds in last 12m": row.prior_refunds_12m,
        "duplicate with different details": "yes" if row.get("duplicate_conflict") else "no",
    }
    st.table({k: [str(v)] for k, v in details.items()})

# ---- decide
st.markdown("### Decide")
reviewer_choice = st.selectbox("Reviewer", REVIEWERS + ["Other"], key="reviewer_name")
reviewer = st.text_input("Your name", key="reviewer_other") if reviewer_choice == "Other" else reviewer_choice
reason = st.text_input("Reason (required for partial and reject)", key="decision_reason")
partial_amount = st.number_input("Partial amount (USD)", min_value=0.0, max_value=float(row.amount_usd or 0),
                                 value=round(float(row.amount_usd or 0) / 2, 2), step=1.0, key="partial_amount")


def decide(action: str, amount: float | None = None) -> None:
    if action in ("partial", "reject") and not reason.strip():
        st.warning("A reason is required for a partial refund or a rejection.")
        return
    if not reviewer:
        st.warning("Pick or type the reviewer's name.")
        return
    try:
        record_reviewer_decision(ReviewerDecision(
            request_id=selected, action=action, amount_usd=amount if action == "partial" else (row.amount_usd if action == "approve" else None),
            reason=reason.strip(), reviewer=reviewer, decided_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            policy_version=int(row.policy_version)))
    except ValueError as exc:
        st.error(str(exc))
        return
    st.session_state["last_decision"] = f"{selected}: {action}" + (f" {money(amount)}" if action == "partial" else "")
    st.rerun()


b1, b2, b3, b4 = st.columns(4)
if b1.button("Approve in full", key="btn_approve", type="primary"):
    decide("approve")
if b2.button("Approve partial", key="btn_partial"):
    decide("partial", partial_amount)
if b3.button("Reject", key="btn_reject"):
    decide("reject")
if b4.button("Send to fraud queue", key="btn_fraud"):
    decide("to_fraud")
if "last_decision" in st.session_state:
    st.success(f"Recorded {st.session_state.pop('last_decision')}. It has left the queue.")

# ---- audit and history
with st.expander(f"Approved automatically by the system ({len(load_auto_approved())}) — spot-check"):
    auto = load_auto_approved()
    if not auto.empty:
        a = auto[["request_id", "amount_usd", "stated_reason", "rule_name", "reason", "customer_note", "support_note"]]
        st.dataframe(a, hide_index=True, width="stretch")
with st.expander("Decided by reviewers"):
    done = load_reviewer_decisions()
    st.dataframe(done, hide_index=True, width="stretch") if not done.empty else st.write("none yet")
