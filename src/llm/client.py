"""One thin client for every LLM call: structured output, timing, token and cost logging.

Nothing else in the project imports `anthropic`. If there is no API key the client reports
`available = False` and every call raises LLMUnavailable; callers turn that into "unknown".
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from src import settings
from src.app_settings import load_app_settings, prices_for
from src.logging_setup import get_logger

log = get_logger("llm.client")
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(Exception):
    """No API key configured; the caller must degrade (facts unknown, text box disabled)."""


class UsageInfo(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float


def render_prompt(prompt_name: str, /, **variables: str) -> str:
    """Load src/llm/prompts/<name>.md and fill {placeholders}."""
    template = (PROMPT_DIR / f"{prompt_name}.md").read_text(encoding="utf-8")
    return template.format_map(variables)


class LLMClient:
    def __init__(self, model: str | None = None, api_key: str | None = settings.API_KEY,
                 timeout_s: float = 20.0, max_retries: int = 2, effort: str = "low"):
        self.model = model or load_app_settings().extractor_model
        self.prices = prices_for(self.model)
        self.api_key = api_key
        self.effort = effort
        self.stats = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "latency_ms": 0}
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=max_retries) if api_key else None

    @property
    def available(self) -> bool:
        return self._client is not None

    def _cost(self, input_tokens: int, output_tokens: int) -> float:
        price_in, price_out = self.prices
        return (input_tokens * price_in + output_tokens * price_out) / 1_000_000

    def complete_json(self, system: str, user: str, schema: type[T], max_tokens: int = 1024) -> tuple[T, UsageInfo]:
        """One request, validated against `schema`. Raises LLMUnavailable, ValueError, or the SDK's API errors."""
        if self._client is None:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not set")
        started = time.perf_counter()
        response = self._client.messages.parse(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema, output_config={"effort": self.effort},
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = UsageInfo(
            model=self.model, input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens,
            latency_ms=latency_ms, cost_usd=self._cost(response.usage.input_tokens, response.usage.output_tokens),
        )
        self.stats["calls"] += 1
        self.stats["input_tokens"] += usage.input_tokens
        self.stats["output_tokens"] += usage.output_tokens
        self.stats["cost_usd"] += usage.cost_usd
        self.stats["latency_ms"] += latency_ms
        log.info("llm_call model=%s in=%d out=%d ms=%d usd=%.6f stop=%s", usage.model, usage.input_tokens,
                 usage.output_tokens, latency_ms, usage.cost_usd, getattr(response, "stop_reason", "?"))
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise ValueError(f"model returned no parsable {schema.__name__} (stop_reason={getattr(response, 'stop_reason', '?')})")
        return parsed, usage
