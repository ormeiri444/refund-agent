"""Choices the manager can change from the UI: which model does which job. Env var > file > default."""
from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel

from src import settings

SETTINGS_PATH: Path = settings.OUTPUTS_DIR / "app_settings.json"
DEFAULT_MODEL = "claude-haiku-5-5"

# model id -> (USD per million input tokens, USD per million output tokens), Anthropic list prices.
MODEL_CHOICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


class AppSettings(BaseModel):
    extractor_model: str = DEFAULT_MODEL     # reads the notes, per request
    translator_model: str = DEFAULT_MODEL    # turns the manager's English into a rule


def load_app_settings() -> AppSettings:
    data = {}
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text())
        except json.JSONDecodeError:
            data = {}
    s = AppSettings(**{k: v for k, v in data.items() if k in AppSettings.model_fields})
    if os.getenv("REFUND_AGENT_MODEL"):
        s.extractor_model = os.environ["REFUND_AGENT_MODEL"]
    if os.getenv("REFUND_AGENT_TRANSLATOR_MODEL"):
        s.translator_model = os.environ["REFUND_AGENT_TRANSLATOR_MODEL"]
    return s


def save_app_settings(s: AppSettings) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(s.model_dump(), indent=2))


def prices_for(model: str) -> tuple[float, float]:
    return MODEL_CHOICES.get(model, (0.0, 0.0))
