"""The Refund Ops Manager's notes (data/policy_notes.csv), and which note applies to a request."""
from __future__ import annotations

from functools import lru_cache

import pandas as pd

from src import settings

REASON_TO_NOTES: dict[str, list[int]] = {
    "wrong_size": [1], "changed_mind": [2], "arrived_damaged": [3], "never_arrived": [4],
    "wrong_item": [6], "late_delivery": [6],
}


@lru_cache(maxsize=1)
def load_policy_notes() -> dict[int, str]:
    df = pd.read_csv(settings.DATA_DIR / "policy_notes.csv")
    return {int(row.iloc[0]): str(row.iloc[1]) for _, row in df.iterrows()}


def notes_for(stated_reason: str, fraud_flag: bool | None) -> list[tuple[int, str]]:
    notes = load_policy_notes()
    numbers = ([5] if fraud_flag is True else []) + REASON_TO_NOTES.get(stated_reason, [])
    return [(n, notes[n]) for n in numbers if n in notes]
