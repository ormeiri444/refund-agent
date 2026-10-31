"""The reviewer's queue: what the system routed, minus what a person already decided.

Two append-only files are the whole state: the system's decisions (one per request, latest
run wins) and the reviewers' decisions. The queue is derived from them on every read, so
restarting the app never loses or resurrects anything.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src import settings
from src.data.normalize import load_requests
from src.decisions import append_records, read_records, replace_records, reset
from src.logging_setup import get_logger
from src.policy.engine import decide_frame
from src.schemas import Decision, FactProvider, Policy
from src.schemas.review import ReviewerDecision

log = get_logger("queue")

REVIEWERS = ["S. Kwan", "R. Mizrahi", "D. Patel", "J. Alvarez"]

REQUEST_COLUMNS = [
    "request_id", "requested_at", "source", "customer_id", "tenure_months", "prior_refunds_12m", "amount_usd", "category",
    "payment_method", "stated_reason", "customer_note", "support_note", "days_since_delivery", "fraud_flag", "has_note",
    "duplicate_conflict",
]
_REQUESTS_PATH = settings.OUTPUTS_DIR / "requests_snapshot.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_snapshot(df: pd.DataFrame, snapshot_path: Path) -> None:
    """Store the request rows the queue page shows, next to the decisions file."""
    snapshot = df[[c for c in REQUEST_COLUMNS if c in df.columns]].copy()
    snapshot["requested_at"] = snapshot["requested_at"].astype(str)
    snapshot = snapshot.astype(object).where(snapshot.notna(), None)
    replace_records(snapshot_path, snapshot.to_dict(orient="records"))


def run_system(csv_path: Path, policy: Policy, fact_provider: FactProvider,
               decisions_path: Path | None = None) -> list[Decision]:
    """Decide every request in the file and store both the decisions and the request rows the queue will show."""
    df = load_requests(csv_path)
    decisions = decide_frame(df, policy, fact_provider)
    decisions_path = Path(decisions_path) if decisions_path else settings.SYSTEM_DECISIONS_PATH
    replace_records(decisions_path, [d.model_dump() for d in decisions])
    write_snapshot(df, decisions_path.parent / "requests_snapshot.jsonl")
    log.info("run_system: %d requests from %s, policy v%d", len(decisions), csv_path, policy.version)
    return decisions


def _system_frame() -> pd.DataFrame:
    sys_records = read_records(settings.SYSTEM_DECISIONS_PATH)
    if not sys_records:
        return pd.DataFrame(columns=["request_id", "outcome", "queue", "rule_id", "rule_name", "reason", "facts_used", "policy_version"])
    sys_df = pd.DataFrame(sys_records)
    req = pd.DataFrame(read_records(settings.OUTPUTS_DIR / "requests_snapshot.jsonl"))
    if req.empty:
        return sys_df
    req["requested_at"] = pd.to_datetime(req["requested_at"], errors="coerce")
    merged = sys_df.drop(columns=["amount_usd"], errors="ignore").merge(req, on="request_id", how="left")
    return merged


def _oldest_first(df: pd.DataFrame) -> pd.DataFrame:
    keys = [c for c in ("requested_at", "request_id") if c in df.columns]
    return df.sort_values(keys, na_position="last").reset_index(drop=True)


def _decided_ids() -> set[str]:
    return {r["request_id"] for r in read_records(settings.REVIEWER_DECISIONS_PATH)}


def load_queue() -> pd.DataFrame:
    df = _system_frame()
    if df.empty:
        return df
    df = df[(df.outcome == "route") & ~df.request_id.isin(_decided_ids())]
    return _oldest_first(df)


def load_auto_approved() -> pd.DataFrame:
    df = _system_frame()
    if df.empty:
        return df
    return _oldest_first(df[df.outcome == "approve"])


def load_reviewer_decisions() -> pd.DataFrame:
    return pd.DataFrame(read_records(settings.REVIEWER_DECISIONS_PATH))


def record_reviewer_decision(d: ReviewerDecision) -> None:
    if d.request_id in _decided_ids():
        raise ValueError(f"{d.request_id} was already decided by a reviewer")
    if d.action == "partial":
        row = _system_frame().set_index("request_id")
        requested = float(row.loc[d.request_id, "amount_usd"]) if d.request_id in row.index else None
        if d.amount_usd is None or d.amount_usd <= 0 or (requested is not None and d.amount_usd > requested):
            raise ValueError(f"partial amount must be between 0 and the requested amount ({requested})")
    append_records(settings.REVIEWER_DECISIONS_PATH, [d.model_dump()])
    log.info("reviewer_decision request=%s action=%s amount=%s reviewer=%s policy=v%d",
             d.request_id, d.action, d.amount_usd, d.reviewer, d.policy_version)


def queue_summary() -> dict:
    df = _system_frame()
    q = load_queue()
    reviewed = read_records(settings.REVIEWER_DECISIONS_PATH)
    today = datetime.now(timezone.utc).date().isoformat()
    return {
        "in_queue": int(len(q)),
        "fraud_queue": int((df.queue == "fraud").sum()) if not df.empty else 0,
        "auto_approved": int((df.outcome == "approve").sum()) if not df.empty else 0,
        "auto_approved_usd": float(df.loc[df.outcome == "approve", "amount_usd"].sum()) if not df.empty else 0.0,
        "decided_by_reviewers": len(reviewed),
        "decided_today": sum(1 for r in reviewed if str(r.get("decided_at", "")).startswith(today)),
        "dollars_in_queue": float(q.amount_usd.sum()) if not q.empty else 0.0,
        "policy_version": int(df.policy_version.iloc[0]) if not df.empty else None,
    }


def reset_demo() -> None:
    """Forget every decision (system and reviewer) so the demo can be replayed. Keeps the LLM cache."""
    for path in (settings.SYSTEM_DECISIONS_PATH, settings.REVIEWER_DECISIONS_PATH, settings.OUTPUTS_DIR / "requests_snapshot.jsonl"):
        reset(path)
    log.info("reset_demo: decisions cleared")
