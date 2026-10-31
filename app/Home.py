"""Refund Agent demo: run the system on a file, see the numbers, open the two pages."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app._shared import get_fact_provider, live_policy, money, sidebar_status  # noqa: E402
from src import settings  # noqa: E402
from src.queue import queue_summary, reset_demo, run_system  # noqa: E402

st.set_page_config(page_title="Refund Agent", page_icon="↩", layout="wide")
sidebar_status()

st.title("Refund Agent")
st.write(
    "Rules decide which refund requests are approved automatically. A model only reads the free-text notes to answer "
    "the policy's yes/no questions. Everything the rules don't cover goes to a person. "
    "Use **Reviewer Queue** to work the requests that need a person, and **Manager Policy** to change the rules."
)

policy = live_policy()
pending = settings.DATA_DIR / "pending.csv"
col_run, col_reset = st.columns([3, 1])
with col_run:
    if st.button(f"Run the system on {pending.name} with policy v{policy.version if policy else '?'}", key="btn_run", type="primary",
                 disabled=policy is None):
        provider, label = get_fact_provider()
        decisions = run_system(pending, policy, provider)
        n_auto = sum(d.outcome == "approve" for d in decisions)
        st.success(f"{len(decisions)} requests decided: {n_auto} approved automatically, {len(decisions) - n_auto} sent to people ({label}).")
with col_reset:
    if st.button("Reset demo", key="btn_reset", help="Forget every decision so the walkthrough can be replayed."):
        reset_demo()
        st.info("Decisions cleared.")

s = queue_summary()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Waiting for a person", s["in_queue"], help="Routed by the rules and not yet decided by a reviewer.")
c2.metric("In the fraud queue", s["fraud_queue"])
c3.metric("Approved automatically", s["auto_approved"], money(s["auto_approved_usd"]))
c4.metric("Decided by reviewers", s["decided_by_reviewers"], f"{s['decided_today']} today")
st.caption(f"Dollars waiting for a person: {money(s['dollars_in_queue'])}. Decisions are stored in `outputs/` as JSON lines.")
