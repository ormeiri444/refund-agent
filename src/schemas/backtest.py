"""Results of replaying a policy on history, and of comparing two policies."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BadApproval(BaseModel):
    request_id: str
    amount_usd: float | None
    rule_id: str
    reason: str          # "chargeback", "fraud flag", "reviewer rejected", "reviewer paid partial" (comma-joined)
    detectable: bool     # a note or a fraud flag was there to be read


class CapRow(BaseModel):
    cap: float
    n_auto_approve: int
    auto_approve_rate: float
    dollars_auto_approved: float
    reviewer_minutes_saved: float
    n_bad_detectable: int
    n_bad_undetectable: int


class BacktestResult(BaseModel):
    policy_version: int
    n: int
    n_auto_approve: int
    auto_approve_rate: float
    dollars_auto_approved: float
    reviewer_minutes_saved: float
    remaining_reviewer_minutes: float
    agreement_rate: float
    overpaid_partial_usd: float
    bad_detectable: list[BadApproval] = Field(default_factory=list)
    bad_undetectable: list[BadApproval] = Field(default_factory=list)
    routing_reasons: dict[str, int] = Field(default_factory=dict)
    weeks: float
    weekly_auto_dollars: float
    verdict: Literal["PASS", "FAIL"]
    decisions: list[dict] = Field(default_factory=list)


class PolicyDiff(BaseModel):
    old_version: int
    new_version: int | None
    n_flipped: int
    to_auto: list[str] = Field(default_factory=list)
    to_human: list[str] = Field(default_factory=list)
    dollars_to_auto: float = 0.0
    dollars_to_human: float = 0.0
    newly_bad_detectable: list[str] = Field(default_factory=list)
    newly_bad_undetectable: list[str] = Field(default_factory=list)
    newly_caught_detectable: list[str] = Field(default_factory=list)
    newly_caught_undetectable: list[str] = Field(default_factory=list)
    blocks_publish: bool = False
    per_request: list[dict] = Field(default_factory=list)
