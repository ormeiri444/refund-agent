"""Regression tests from the whole-branch review (Critical 1-2, Important 3-6)."""
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from src import settings
from src.policy.store import list_versions, load_policy, save_policy
from src.schemas import Condition

ROOT = Path(__file__).resolve().parents[1]
MANAGER = str(ROOT / "app" / "pages" / "2_Manager_Policy.py")


# ---- Critical 1: CLI decide, then the app, must not crash
def test_cli_decide_then_home_and_queue_render(tmp_outputs):
    save_policy(load_policy(1, policy_dir=ROOT / "policies"))
    env = {**os.environ, "ANTHROPIC_API_KEY": ""}
    # run the CLI against the temp outputs by pointing --out at the temp decisions path
    res = subprocess.run([sys.executable, "-m", "src.cli", "decide", "data/pending.csv", "--no-llm", "--out", str(settings.SYSTEM_DECISIONS_PATH)],
                         capture_output=True, text=True, cwd=ROOT, env=env)
    assert res.returncode == 0, res.stderr
    from src.queue import load_queue, queue_summary
    q = load_queue()
    assert len(q) > 0 and "requested_at" in q.columns and q.amount_usd.notna().all()
    assert queue_summary()["in_queue"] == len(q)
    at = AppTest.from_file(str(ROOT / "app" / "Home.py"), default_timeout=30).run()
    assert not at.exception
    at = AppTest.from_file(str(ROOT / "app" / "pages" / "1_Reviewer_Queue.py"), default_timeout=30).run()
    assert not at.exception


# ---- Critical 2: a translated replace_rule must be stageable
def test_translated_replace_rule_is_staged_as_replace(tmp_outputs, monkeypatch):
    save_policy(load_policy(1, policy_dir=ROOT / "policies"))
    from src.llm.schemas.operation import RuleOperation
    from src.schemas import Rule
    live = load_policy(1)
    cap = next(r for r in live.rules if r.id == "over_cap")
    scripted = RuleOperation(op="replace_rule", target_rule_id="over_cap",
                             rule=cap.model_copy(update={"when": [Condition(field="amount_usd", op=">", value=300)]}),
                             explanation="cap to 300")
    monkeypatch.setattr("src.llm.translator.translate_instruction", lambda *a, **k: scripted)
    import app.pages  # noqa: F401  (package import so the monkeypatch below resolves)
    at = AppTest.from_file(MANAGER, default_timeout=60)
    at.run()
    # the page imports translate_instruction by name; patch where the page looks it up
    monkeypatch.setattr("src.llm.translator.translate_instruction", lambda *a, **k: scripted)
    at.text_area(key="instruction").set_value("From now on, anything over $300 comes to us.").run()
    at.session_state["translated"] = scripted
    at.session_state["translated_from"] = "From now on, anything over $300 comes to us."
    at.run()
    at.button(key="btn_add_to_proposal").click().run()
    assert not at.exception
    assert not any("Not added" in str(e.value) for e in at.error)
    prop = at.session_state["proposal"]
    assert prop is not None
    assert [r.id for r in prop.rules].count("over_cap") == 1
    assert next(r for r in prop.rules if r.id == "over_cap").when[0].value == 300


def test_translator_forces_rule_id_on_replace():
    from src.llm.schemas.operation import RuleOperation
    from src.llm.translator import translate_instruction
    from src.schemas import Rule
    from tests.test_translator import FakeClient
    policy = load_policy(1, policy_dir=ROOT / "policies")
    cap = next(r for r in policy.rules if r.id == "over_cap")
    scripted = RuleOperation(op="replace_rule", target_rule_id="over_cap", rule=cap.model_copy(update={"id": "over_cap_300"}), explanation="x")
    op = translate_instruction("over 300", policy, FakeClient(scripted))
    assert op.op == "replace_rule" and op.rule.id == "over_cap"


def enabled_box(at, rule_id: str):
    """The on/off checkbox of a rule; its key carries a generation suffix that changes on discard / publish / rollback."""
    return next(c for c in at.checkbox if str(c.key).split("@")[0] == f"enabled_{rule_id}")


# ---- Important 3: checkbox disables must not resurrect after Discard / publish / rollback
def test_discard_after_checkbox_leaves_no_proposal(tmp_outputs):
    save_policy(load_policy(1, policy_dir=ROOT / "policies"))
    at = AppTest.from_file(MANAGER, default_timeout=60).run()
    enabled_box(at, "damaged_small").set_value(False).run()
    assert at.session_state["proposal"] is not None
    at.button(key="btn_discard").click().run()
    at.run()
    assert at.session_state["proposal"] is None
    assert enabled_box(at, "damaged_small").value is True


def test_rollback_after_checkbox_publish_leaves_no_proposal(tmp_outputs):
    save_policy(load_policy(1, policy_dir=ROOT / "policies"))
    at = AppTest.from_file(MANAGER, default_timeout=60).run()
    enabled_box(at, "damaged_small").set_value(False).run()
    at.button(key="btn_publish").click().run()
    at.run()
    assert list_versions() == [1, 2] and at.session_state["proposal"] is None
    at.selectbox(key="rollback_version").set_value(1).run()
    at.button(key="btn_rollback").click().run()
    at.run()
    assert list_versions() == [1, 2, 3] and at.session_state["proposal"] is None


# ---- Important 4: transient LLM errors are not cached as unknown
def test_transient_error_is_not_cached(tmp_path):
    import anthropic
    from src.llm.extractor import FactExtractor
    from src.llm.schemas import FactAnswer, FactExtraction
    from tests.test_extractor import ROW, Q, FakeClient
    err = anthropic.APIConnectionError(request=SimpleNamespace())
    client = FakeClient(error=err)
    ex = FactExtractor(client, cache_path=tmp_path / "c.jsonl")
    assert all(v.value is None for v in ex(ROW, Q).values())
    client.error = None
    client.scripted = FactExtraction(answers=[FactAnswer(fact_id="photo_attached", value="true", quote="photos clear"),
                                              FactAnswer(fact_id="card_confirmed_stolen", value="false")])
    out = ex(ROW, Q)
    assert out["photo_attached"].value is True and len(client.calls) == 2


# ---- Important 5: an unknown REFUND_AGENT_MODEL must not crash the pages
def test_unknown_model_env_does_not_crash_sidebar(tmp_outputs, monkeypatch):
    save_policy(load_policy(1, policy_dir=ROOT / "policies"))
    monkeypatch.setenv("REFUND_AGENT_MODEL", "claude-haiku-4-5")
    at = AppTest.from_file(str(ROOT / "app" / "Home.py"), default_timeout=30).run()
    assert not at.exception
    assert at.selectbox(key="model_extractor").value == "claude-haiku-4-5"


# ---- Important 6: Condition shape validation
def test_condition_shape_validation():
    with pytest.raises(ValidationError):
        Condition(field="stated_reason", op="in", value="wrong_size")        # list required
    with pytest.raises(ValidationError):
        Condition(field="amount_usd", op="<=", value=[1, 2])                # scalar required
    with pytest.raises(ValidationError):
        Condition(field="amount_usd", op="<=", value=None)                  # value required
    with pytest.raises(ValidationError):
        Condition(field="fraud_flag", op="is_true", value=True)             # no value allowed
    Condition(field="stated_reason", op="in", value=["wrong_size"])
    Condition(field="fraud_flag", op="is_true")
    Condition(field="amount_usd", op=">", value=300)
