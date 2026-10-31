import json

from src.app_settings import MODEL_CHOICES, AppSettings, load_app_settings, save_app_settings


def test_defaults_and_round_trip(tmp_path, monkeypatch):
    path = tmp_path / "app_settings.json"
    monkeypatch.setattr("src.app_settings.SETTINGS_PATH", path)
    monkeypatch.delenv("REFUND_AGENT_MODEL", raising=False)
    monkeypatch.delenv("REFUND_AGENT_TRANSLATOR_MODEL", raising=False)
    s = load_app_settings()
    assert s == AppSettings(extractor_model="claude-haiku-5-5", translator_model="claude-haiku-5-5")
    save_app_settings(AppSettings(extractor_model="claude-sonnet-5-5", translator_model="claude-opus-5-5"))
    assert json.loads(path.read_text())["extractor_model"] == "claude-sonnet-5-5"
    assert load_app_settings().translator_model == "claude-opus-5-5"


def test_env_overrides_file(tmp_path, monkeypatch):
    path = tmp_path / "app_settings.json"
    monkeypatch.setattr("src.app_settings.SETTINGS_PATH", path)
    save_app_settings(AppSettings(extractor_model="claude-sonnet-5-5", translator_model="claude-sonnet-5-5"))
    monkeypatch.setenv("REFUND_AGENT_MODEL", "claude-opus-5-5")
    monkeypatch.setenv("REFUND_AGENT_TRANSLATOR_MODEL", "claude-haiku-5-5")
    s = load_app_settings()
    assert s.extractor_model == "claude-opus-5-5" and s.translator_model == "claude-haiku-5-5"


def test_model_choices_have_prices():
    assert set(MODEL_CHOICES) == {"claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"}
    assert all(len(v) == 2 for v in MODEL_CHOICES.values())


def test_client_prices_follow_model(monkeypatch):
    from src.llm.client import LLMClient
    c = LLMClient(api_key=None, model="claude-sonnet-5-5")
    assert c.prices == (2.0, 10.0)
    assert LLMClient(api_key=None, model="claude-haiku-5-5").prices == (0.10, 0.50)
