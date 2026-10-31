import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import settings
from src.policy.store import list_versions, load_policy, save_policy

ROOT = Path(__file__).resolve().parents[1]
PAGE = str(ROOT / "app" / "pages" / "2_Manager_Policy.py")


@pytest.fixture
def with_v1(tmp_outputs):
    save_policy(load_policy(1, policy_dir=ROOT / "policies"))   # into the temp policy dir
    return tmp_outputs


def run_page():
    return AppTest.from_file(PAGE, default_timeout=60).run()


def enabled_box(at, rule_id: str):
    """The on/off checkbox of a rule. Its key carries a generation suffix that changes on discard / publish."""
    return next(c for c in at.checkbox if str(c.key).split("@")[0] == f"enabled_{rule_id}")


def test_manager_page_renders_live_policy(with_v1):
    at = run_page()
    assert not at.exception
    assert any("v1" in str(m.value) for m in at.markdown) or any("v1" in str(x.value) for x in at.caption)


def test_form_add_route_rule_dry_run_and_publish(with_v1):
    at = run_page()
    at.selectbox(key="form_then").set_value("route").run()
    at.text_input(key="form_rule_id").set_value("over_300").run()
    at.text_input(key="form_rule_name").set_value("Over 300 to people").run()
    at.text_input(key="form_rule_description").set_value("Anything over $300 goes to a reviewer.").run()
    at.selectbox(key="cond_field_0").set_value("amount_usd").run()
    at.selectbox(key="cond_op_0").set_value(">").run()
    at.text_input(key="cond_value_0").set_value("300").run()
    assert at.selectbox(key="form_position").value == "top"          # route rules default to the top
    at.button(key="btn_add_to_proposal").click().run()
    assert not at.exception
    at.button(key="btn_dry_run").click().run()
    assert not at.exception
    assert any("decided differently" in str(m.value) for m in at.markdown)
    assert any(m.label == "to automatic" for m in at.metric)            # the big-number tiles are shown
    at.button(key="btn_publish").click().run()
    assert not at.exception
    assert list_versions() == [1, 2]
    v2 = load_policy(2)
    assert v2.rules[0].id == "over_300" and "Over 300" in v2.changelog or "over" in v2.changelog.lower()


def test_form_approve_rule_defaults_to_bottom(with_v1):
    at = run_page()
    at.selectbox(key="form_then").set_value("approve").run()
    assert at.selectbox(key="form_position").value == "bottom"


def test_fail_verdict_requires_publish_anyway(with_v1):
    at = run_page()
    # a loose rule that approves any wrong_item: the backtest marks RF-1006 etc. as newly bad
    at.selectbox(key="form_then").set_value("approve").run()
    at.text_input(key="form_rule_id").set_value("all_wrong_item").run()
    at.text_input(key="form_rule_name").set_value("All wrong items").run()
    at.text_input(key="form_rule_description").set_value("Approve any wrong item.").run()
    at.selectbox(key="cond_field_0").set_value("stated_reason").run()
    at.selectbox(key="cond_op_0").set_value("==").run()
    at.text_input(key="cond_value_0").set_value("wrong_item").run()
    at.selectbox(key="form_position").set_value("top").run()
    at.button(key="btn_add_to_proposal").click().run()
    at.button(key="btn_dry_run").click().run()
    assert not at.exception
    assert any("RF-1006" in str(m.value) for m in list(at.markdown) + list(at.dataframe) + list(at.error))
    changed = [df.value for df in at.dataframe if "old_rule" in df.value.columns]
    assert len(changed) == 2, "history and pending tables of requests that would change"
    assert "bad" in changed[0].columns                                  # history: outcomes are known
    assert "bad" not in changed[1].columns and "bad_reason" not in changed[1].columns   # pending: no outcome yet
    assert any("no outcome yet" in str(c.value) for c in at.caption)
    assert at.button(key="btn_publish").disabled or any("anyway" in str(b.label).lower() for b in at.button)
    assert list_versions() == [1]


def test_toggle_disable_rule_into_proposal(with_v1):
    at = run_page()
    enabled_box(at, "damaged_small").set_value(False).run()
    assert not at.exception
    at.button(key="btn_dry_run").click().run()
    at.button(key="btn_publish").click().run()
    assert list_versions() == [1, 2]
    assert not next(r for r in load_policy(2).rules if r.id == "damaged_small").enabled


def test_add_fact_question_offline_is_unknown_but_allowed(with_v1):
    at = run_page()
    at.text_input(key="fact_id").set_value("police_report").run()
    at.text_input(key="fact_question").set_value("Does the note mention a police report?").run()
    at.button(key="btn_add_fact").click().run()
    assert not at.exception
    at.button(key="btn_publish").click().run()
    assert "police_report" in load_policy(2).fact_ids()


def test_rollback_republishes_old_content(with_v1):
    at = run_page()
    enabled_box(at, "damaged_small").set_value(False).run()
    at.button(key="btn_publish").click().run()
    assert list_versions() == [1, 2]
    at = run_page()
    at.selectbox(key="rollback_version").set_value(1).run()
    at.button(key="btn_rollback").click().run()
    assert not at.exception
    assert list_versions() == [1, 2, 3]
    v3 = load_policy(3)
    assert next(r for r in v3.rules if r.id == "damaged_small").enabled and "rollback" in v3.changelog.lower()


def test_translate_offline_shows_cannot_express(with_v1):
    at = run_page()
    at.text_area(key="instruction").set_value("Angry customers get a human.").run()
    at.button(key="btn_translate").click().run()
    assert not at.exception
    assert any("unavailable" in str(w.value).lower() or "can't" in str(w.value).lower() for w in list(at.warning) + list(at.error) + list(at.info))


def test_sidebar_model_switch_saves_settings(with_v1):
    at = run_page()
    at.selectbox(key="model_extractor").set_value("claude-sonnet-5-5").run()
    assert not at.exception
    from src.app_settings import load_app_settings
    assert load_app_settings().extractor_model == "claude-sonnet-5-5"


def test_discard_resets_rule_checkboxes(with_v1):
    at = run_page()
    enabled_box(at, "damaged_small").set_value(False).run()
    assert any("disabled rule damaged_small" in str(m.value) for m in at.markdown)
    old_key = enabled_box(at, "damaged_small").key
    at.button(key="btn_discard").click().run()
    assert not at.exception
    box = enabled_box(at, "damaged_small")
    assert box.value is True and box.key != old_key          # a fresh widget, so the browser shows it ticked again
    assert not any("disabled rule" in str(m.value) for m in at.markdown)
    assert any("Proposal: none yet" in str(s.value) for s in at.subheader)
