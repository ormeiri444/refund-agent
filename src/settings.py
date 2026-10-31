"""Paths, model name, and prices. Everything configurable lives here."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
POLICY_DIR = ROOT_DIR / "policies"
OUTPUTS_DIR = ROOT_DIR / "outputs"
LOG_DIR = OUTPUTS_DIR / "logs"
CACHE_PATH = OUTPUTS_DIR / "llm_cache.jsonl"
CACHE_SEED_PATH = DATA_DIR / "llm_cache_seed.jsonl"   # committed answers for history notes, so the backtest reproduces offline
SYSTEM_DECISIONS_PATH = OUTPUTS_DIR / "system_decisions.jsonl"
REVIEWER_DECISIONS_PATH = OUTPUTS_DIR / "reviewer_decisions.jsonl"

MODEL: str = os.getenv("REFUND_AGENT_MODEL", "claude-haiku-5-5")   # default; the UI can override per job (src/app_settings.py)
API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY") or None
