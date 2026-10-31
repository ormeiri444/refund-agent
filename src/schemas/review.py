"""What a reviewer records when they decide a routed request."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ReviewAction = Literal["approve", "partial", "reject", "to_fraud"]


class ReviewerDecision(BaseModel):
    request_id: str
    action: ReviewAction
    amount_usd: float | None = None     # refunded amount; required for partial
    reason: str = ""
    reviewer: str
    decided_at: str
    policy_version: int
