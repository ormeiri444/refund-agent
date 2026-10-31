"""Append-only JSONL logs for system and reviewer decisions. The audit trail."""
from __future__ import annotations

import json
from pathlib import Path


def append_records(path: Path, records: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, default=str) + "\n")


def read_records(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def replace_records(path: Path, records: list[dict], key: str = "request_id") -> None:
    """Drop any existing records whose key matches a new record, then append the new ones."""
    new_keys = {r[key] for r in records}
    kept = [r for r in read_records(path) if r.get(key) not in new_keys]
    reset(path)
    append_records(path, kept + records)


def reset(path: Path) -> None:
    Path(path).unlink(missing_ok=True)
