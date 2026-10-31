from types import SimpleNamespace

import pytest

from src.llm.extractor import FactExtractor
from src.llm.schemas import FactAnswer, FactExtraction
from src.schemas import FactQuestion, FactValue

Q = [FactQuestion(id="photo_attached", question="Photo attached?"),
     FactQuestion(id="card_confirmed_stolen", question="Card stolen?")]
ROW = {"request_id": "RF-9", "stated_reason": "arrived_damaged", "category": "home",
       "customer_note": "mug chipped", "support_note": "photos clear"}
USAGE = SimpleNamespace(model="m", input_tokens=10, output_tokens=5, latency_ms=1, cost_usd=0.0001)


class FakeClient:
    model = "fake-model"

    def __init__(self, scripted=None, available=True, error=None):
        self.scripted, self.available, self.error, self.calls = scripted, available, error, []

    def complete_json(self, system, user, schema, max_tokens=1024):
        from src.llm.client import LLMUnavailable
        if not self.available:
            raise LLMUnavailable()
        self.calls.append(user)
        if self.error:
            raise self.error
        return self.scripted, USAGE


def test_offline_returns_unknown_without_call(tmp_path):
    ex = FactExtractor(FakeClient(available=False), cache_path=tmp_path / "c.jsonl")
    out = ex(ROW, Q)
    assert out == {"photo_attached": FactValue(value=None), "card_confirmed_stolen": FactValue(value=None)}
    assert ex.stats["calls"] == 0


def test_no_notes_returns_unknown_without_call(tmp_path):
    client = FakeClient(scripted=FactExtraction(answers=[]))
    ex = FactExtractor(client, cache_path=tmp_path / "c.jsonl")
    out = ex({**ROW, "customer_note": "", "support_note": ""}, Q)
    assert all(v.value is None for v in out.values()) and client.calls == []


def test_answers_mapped_to_fact_values_with_quotes(tmp_path):
    client = FakeClient(scripted=FactExtraction(answers=[
        FactAnswer(fact_id="photo_attached", value="true", quote="photos clear"),
        FactAnswer(fact_id="card_confirmed_stolen", value="false", quote="")]))
    ex = FactExtractor(client, cache_path=tmp_path / "c.jsonl")
    out = ex(ROW, Q)
    assert out["photo_attached"] == FactValue(value=True, quote="photos clear")
    assert out["card_confirmed_stolen"] == FactValue(value=False, quote="")
    assert "Customer wrote: mug chipped" in client.calls[0] and "photo_attached: Photo attached?" in client.calls[0]


def test_caches_per_question(tmp_path):
    client = FakeClient(scripted=FactExtraction(answers=[
        FactAnswer(fact_id="photo_attached", value="true", quote="photos clear"),
        FactAnswer(fact_id="card_confirmed_stolen", value="unknown")]))
    ex = FactExtractor(client, cache_path=tmp_path / "c.jsonl")
    first = ex(ROW, Q)
    ex2 = FactExtractor(client, cache_path=tmp_path / "c.jsonl")   # fresh instance, same file
    second = ex2(ROW, Q)
    assert first == second and len(client.calls) == 1
    assert ex2.stats["cache_hits"] == 2 and ex2.stats["calls"] == 0


def test_only_asks_uncached_questions(tmp_path):
    client = FakeClient(scripted=FactExtraction(answers=[FactAnswer(fact_id="photo_attached", value="true", quote="photos clear")]))
    ex = FactExtractor(client, cache_path=tmp_path / "c.jsonl")
    ex(ROW, Q[:1])
    client.scripted = FactExtraction(answers=[FactAnswer(fact_id="card_confirmed_stolen", value="false")])
    out = ex(ROW, Q)
    assert len(client.calls) == 2 and "photo_attached" not in client.calls[1]
    assert out["photo_attached"].value is True and out["card_confirmed_stolen"].value is False


def test_cache_key_changes_when_note_or_question_changes(tmp_path):
    client = FakeClient(scripted=FactExtraction(answers=[FactAnswer(fact_id="photo_attached", value="true", quote="x")]))
    ex = FactExtractor(client, cache_path=tmp_path / "c.jsonl")
    ex(ROW, Q[:1])
    ex({**ROW, "support_note": "no photos yet"}, Q[:1])
    ex(ROW, [FactQuestion(id="photo_attached", question="Was a photo received?")])
    assert len(client.calls) == 3


def test_malformed_response_is_unknown(tmp_path):
    ex = FactExtractor(FakeClient(error=ValueError("bad json")), cache_path=tmp_path / "c.jsonl")
    out = ex(ROW, Q)
    assert all(v.value is None for v in out.values()) and ex.stats["errors"] == 1


def test_api_error_is_unknown(tmp_path):
    import anthropic
    err = anthropic.APIConnectionError(request=SimpleNamespace())
    ex = FactExtractor(FakeClient(error=err), cache_path=tmp_path / "c.jsonl")
    assert all(v.value is None for v in ex(ROW, Q).values())


def test_ignores_extra_and_missing_ids(tmp_path):
    client = FakeClient(scripted=FactExtraction(answers=[
        FactAnswer(fact_id="photo_attached", value="true", quote="photos clear"),
        FactAnswer(fact_id="something_else", value="true", quote="?")]))
    ex = FactExtractor(client, cache_path=tmp_path / "c.jsonl")
    out = ex(ROW, Q)
    assert set(out) == {"photo_attached", "card_confirmed_stolen"}
    assert out["card_confirmed_stolen"].value is None


def test_unknown_answers_are_cached_too(tmp_path):
    client = FakeClient(scripted=FactExtraction(answers=[FactAnswer(fact_id="photo_attached", value="unknown")]))
    ex = FactExtractor(client, cache_path=tmp_path / "c.jsonl")
    ex(ROW, Q[:1]); ex(ROW, Q[:1])
    assert len(client.calls) == 1


def test_cache_key_includes_model_so_a_model_switch_retries(tmp_path):
    client = FakeClient(scripted=FactExtraction(answers=[FactAnswer(fact_id="photo_attached", value="unknown")]))
    client.model = "claude-haiku-5-5"
    ex = FactExtractor(client, cache_path=tmp_path / "c.jsonl")
    ex(ROW, Q[:1])
    client.model = "claude-sonnet-5-5"
    ex2 = FactExtractor(client, cache_path=tmp_path / "c.jsonl")
    ex2(ROW, Q[:1])
    assert len(client.calls) == 2


def test_use_seed_false_ignores_default_seed(tmp_path, monkeypatch):
    seed = tmp_path / "seed.jsonl"
    FactExtractor(FakeClient(scripted=FactExtraction(answers=[FactAnswer(fact_id="photo_attached", value="true", quote="x")])),
                  cache_path=seed)(ROW, Q[:1])
    monkeypatch.setattr("src.llm.extractor.settings.CACHE_SEED_PATH", seed)
    client = FakeClient(scripted=FactExtraction(answers=[FactAnswer(fact_id="photo_attached", value="false")]))
    ex = FactExtractor(client, cache_path=tmp_path / "c.jsonl", use_seed=False)
    assert ex(ROW, Q[:1])["photo_attached"].value is False and len(client.calls) == 1


def test_seed_file_is_read_before_cache(tmp_path):
    seed = tmp_path / "seed.jsonl"
    ex0 = FactExtractor(FakeClient(scripted=FactExtraction(answers=[FactAnswer(fact_id="photo_attached", value="true", quote="photos clear")])),
                        cache_path=seed)
    ex0(ROW, Q[:1])
    client = FakeClient(scripted=FactExtraction(answers=[]))
    ex = FactExtractor(client, cache_path=tmp_path / "c.jsonl", seed_path=seed)
    assert ex(ROW, Q[:1])["photo_attached"].value is True and client.calls == []
