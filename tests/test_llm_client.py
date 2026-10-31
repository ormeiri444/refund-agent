from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from src.llm.client import LLMClient, LLMUnavailable, UsageInfo, render_prompt


class Out(BaseModel):
    answer: str


class FakeMessages:
    """Stands in for anthropic.Anthropic().messages; records the call and returns a scripted parse() result."""

    def __init__(self, parsed=None, usage=(120, 30), error=None):
        self.parsed, self.usage, self.error, self.calls = parsed, usage, error, []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(parsed_output=self.parsed, stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=self.usage[0], output_tokens=self.usage[1]))


def make_client(monkeypatch, fake: FakeMessages, **kw) -> LLMClient:
    monkeypatch.setattr("src.llm.client.anthropic.Anthropic", lambda **_: SimpleNamespace(messages=fake))
    return LLMClient(api_key="sk-test", model="claude-haiku-5-5", **kw)


def test_unavailable_without_key():
    c = LLMClient(api_key=None)
    assert c.available is False
    with pytest.raises(LLMUnavailable):
        c.complete_json("sys", "user", Out)


def test_complete_json_returns_parsed_and_usage_with_cost(monkeypatch):
    fake = FakeMessages(parsed=Out(answer="yes"), usage=(1_000_000, 1_000_000))
    c = make_client(monkeypatch, fake)
    out, usage = c.complete_json("be brief", "is it?", Out)
    assert out == Out(answer="yes")
    assert isinstance(usage, UsageInfo) and usage.input_tokens == 1_000_000 and usage.output_tokens == 1_000_000
    assert usage.cost_usd == pytest.approx(0.10 + 0.50)        # Haiku 5.5 list prices per MTok
    assert usage.model == "claude-haiku-5-5" and usage.latency_ms >= 0
    call = fake.calls[0]
    assert call["model"] == "claude-haiku-5-5" and call["output_format"] is Out
    assert call["system"] == "be brief" and call["messages"] == [{"role": "user", "content": "is it?"}]
    assert call["output_config"] == {"effort": "low"}


def test_complete_json_missing_parsed_output_raises_value_error(monkeypatch):
    c = make_client(monkeypatch, FakeMessages(parsed=None))
    with pytest.raises(ValueError):
        c.complete_json("s", "u", Out)


def test_complete_json_api_errors_propagate(monkeypatch):
    import anthropic
    err = anthropic.APIConnectionError(request=SimpleNamespace())
    c = make_client(monkeypatch, FakeMessages(error=err))
    with pytest.raises(anthropic.APIConnectionError):
        c.complete_json("s", "u", Out)


def test_client_tracks_totals(monkeypatch):
    fake = FakeMessages(parsed=Out(answer="x"), usage=(100, 10))
    c = make_client(monkeypatch, fake)
    c.complete_json("s", "u", Out)
    c.complete_json("s", "u", Out)
    assert c.stats["calls"] == 2 and c.stats["input_tokens"] == 200 and c.stats["cost_usd"] > 0


def test_render_prompt_substitutes(tmp_path, monkeypatch):
    (tmp_path / "hello.md").write_text("Hi {name}, {thing}.")
    monkeypatch.setattr("src.llm.client.PROMPT_DIR", tmp_path)
    assert render_prompt("hello", name="Or", thing="welcome") == "Hi Or, welcome."
