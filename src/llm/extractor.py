"""Turn free-text notes into yes/no/unknown facts by asking the model the policy's questions.

This is the only place the LLM touches a refund request, and it can only *add facts*;
the rules engine decides. Everything that can go wrong (no key, timeout, bad output)
degrades to "unknown", which never approves. Answers are cached per (request, note text,
question text, model) so a re-run or a UI refresh never pays twice; a new question, a
reworded question, or a different model triggers a fresh answer for just that item.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import anthropic

from src import settings
from src.llm.client import LLMClient, LLMUnavailable, render_prompt
from src.llm.schemas import FactExtraction
from src.logging_setup import get_logger
from src.schemas import FactQuestion, FactValue

log = get_logger("llm.extractor")
_VALUES = {"true": True, "false": False, "unknown": None}


def _note(row: dict, key: str) -> str:
    v = row.get(key)
    return "" if v is None or (isinstance(v, float) and v != v) else str(v).strip()


def cache_key(request_id: str, customer_note: str, support_note: str, question: FactQuestion, model: str) -> str:
    """Same request, same notes, same question wording, same model -> same answer. Change any one and we ask again."""
    payload = f"{request_id}\n{customer_note}\n{support_note}\n{question.id}\n{question.question}\n{model}"
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


class FactExtractor:
    """Satisfies the engine's FactProvider signature: (row, questions) -> {fact_id: FactValue}."""

    def __init__(self, client: LLMClient, cache_path: Path | None = None, seed_path: Path | None = None, use_seed: bool = True):
        self.client = client
        self.cache_path = Path(cache_path) if cache_path else settings.CACHE_PATH
        default_seed = settings.CACHE_SEED_PATH if use_seed else None
        self.seed_path = Path(seed_path) if seed_path else default_seed
        self.stats = {"calls": 0, "cache_hits": 0, "cache_misses": 0, "errors": 0, "cost_usd": 0.0}
        self._cache: dict[str, FactValue] = {}
        self._lock = threading.Lock()
        for path in (self.seed_path, self.cache_path):
            if path and Path(path).exists():
                for line in Path(path).read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        rec = json.loads(line)
                        self._cache[rec["key"]] = FactValue(value=rec["value"], quote=rec.get("quote", ""))

    def _remember(self, key: str, value: FactValue) -> None:
        with self._lock:
            self._cache[key] = value
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"key": key, "value": value.value, "quote": value.quote}) + "\n")

    def __call__(self, row: dict, questions: list[FactQuestion]) -> dict[str, FactValue]:
        request_id = str(row.get("request_id", ""))
        customer, support = _note(row, "customer_note"), _note(row, "support_note")
        out: dict[str, FactValue] = {}
        pending: list[FactQuestion] = []
        for q in questions:
            cached = self._cache.get(cache_key(request_id, customer, support, q, self.client.model))
            if cached is not None:
                out[q.id] = cached
                self.stats["cache_hits"] += 1
            else:
                pending.append(q)
                self.stats["cache_misses"] += 1
        if not pending:
            return out
        if not customer and not support:
            return {**out, **{q.id: FactValue(value=None) for q in pending}}
        if not self.client.available:
            log.info("facts for %s unknown: LLM unavailable", request_id)
            return {**out, **{q.id: FactValue(value=None) for q in pending}}

        answers = self._ask(request_id, row, customer, support, pending)
        if answers is None:                      # the call failed: unknown for now, and NOT cached, so the next run retries
            return {**out, **{q.id: FactValue(value=None) for q in pending}}
        for q in pending:
            value = answers.get(q.id, FactValue(value=None))
            out[q.id] = value
            self._remember(cache_key(request_id, customer, support, q, self.client.model), value)
        return out

    def _ask(self, request_id: str, row: dict, customer: str, support: str, questions: list[FactQuestion]) -> dict[str, FactValue] | None:
        system = render_prompt("extract_facts")
        user = render_prompt(
            "extract_facts_user",
            stated_reason=str(row.get("stated_reason", "")), category=str(row.get("category", "")),
            customer_note=customer or "(no note)", support_note=support or "(no note)",
            questions="\n".join(f"- {q.id}: {q.question}" for q in questions),
        )
        try:
            parsed, usage = self.client.complete_json(system, user, FactExtraction)
        except (LLMUnavailable, ValueError, anthropic.APIError) as exc:
            self.stats["errors"] += 1
            log.warning("facts for %s unknown (not cached): %s: %s", request_id, type(exc).__name__, exc)
            return None
        self.stats["calls"] += 1
        self.stats["cost_usd"] += usage.cost_usd
        wanted = {q.id for q in questions}
        result: dict[str, FactValue] = {}
        for a in parsed.answers:
            if a.fact_id in wanted:
                result[a.fact_id] = FactValue(value=_VALUES[a.value], quote=a.quote)
        log.debug("facts for %s: %s", request_id, {k: v.value for k, v in result.items()})
        return result
