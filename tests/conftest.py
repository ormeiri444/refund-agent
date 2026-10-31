import os
from pathlib import Path

import pandas as pd
import pytest

# Tests never talk to the real API: an empty key beats .env (load_dotenv does not override existing vars).
os.environ["ANTHROPIC_API_KEY"] = ""

from src.data.normalize import normalize_requests

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(scope="session")
def raw_history_df() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "history.csv", dtype=str)


@pytest.fixture(scope="session")
def raw_pending_df() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "pending.csv", dtype=str)


@pytest.fixture(scope="session")
def history_df(raw_history_df) -> pd.DataFrame:
    return normalize_requests(raw_history_df)


@pytest.fixture(scope="session")
def pending_df(raw_pending_df) -> pd.DataFrame:
    return normalize_requests(raw_pending_df)


@pytest.fixture
def tmp_outputs(tmp_path, monkeypatch):
    """Point every settings path at a temp dir so tests never touch outputs/."""
    from src import settings

    out = tmp_path / "outputs"
    out.mkdir()
    monkeypatch.setattr(settings, "OUTPUTS_DIR", out)
    monkeypatch.setattr(settings, "LOG_DIR", out / "logs")
    monkeypatch.setattr(settings, "CACHE_PATH", out / "llm_cache.jsonl")
    monkeypatch.setattr(settings, "SYSTEM_DECISIONS_PATH", out / "system_decisions.jsonl")
    monkeypatch.setattr(settings, "REVIEWER_DECISIONS_PATH", out / "reviewer_decisions.jsonl")
    monkeypatch.setattr(settings, "POLICY_DIR", tmp_path / "policies")
    (tmp_path / "policies").mkdir()
    from src import app_settings
    monkeypatch.setattr(app_settings, "SETTINGS_PATH", out / "app_settings.json")
    return out
