from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import settings
from src.policy.engine import unknown_fact_provider
from src.policy.store import load_policy
from src.queue import load_queue, load_reviewer_decisions, run_system

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ran(tmp_outputs):
    run_system(ROOT / "data" / "pending.csv", load_policy(1, policy_dir=ROOT / "policies"), unknown_fact_provider)
    return tmp_outputs


def test_home_renders_without_exception(tmp_outputs):
    at = AppTest.from_file(str(ROOT / "app" / "Home.py"), default_timeout=30).run()
    assert not at.exception


def test_reviewer_queue_renders_and_lists_routed(ran):
    at = AppTest.from_file(str(ROOT / "app" / "pages" / "1_Reviewer_Queue.py"), default_timeout=30).run()
    assert not at.exception
    first = load_queue().request_id.iloc[0]
    assert any(first in str(x.options) for x in at.selectbox)


def test_reviewer_approve_removes_from_queue(ran):
    at = AppTest.from_file(str(ROOT / "app" / "pages" / "1_Reviewer_Queue.py"), default_timeout=30).run()
    before = len(load_queue())
    first = load_queue().request_id.iloc[0]
    at.selectbox(key="selected_request").set_value(first).run()
    at.button(key="btn_approve").click().run()
    assert not at.exception
    assert len(load_queue()) == before - 1
    rec = load_reviewer_decisions().iloc[0]
    assert rec.request_id == first and rec.action == "approve" and rec.policy_version == 1


def test_reviewer_partial_requires_reason(ran):
    at = AppTest.from_file(str(ROOT / "app" / "pages" / "1_Reviewer_Queue.py"), default_timeout=30).run()
    first = load_queue().request_id.iloc[0]
    at.selectbox(key="selected_request").set_value(first).run()
    at.button(key="btn_partial").click().run()
    assert first in set(load_queue().request_id)          # nothing recorded without a reason
    assert any("reason" in str(e.value).lower() for e in list(at.error) + list(at.warning))


def test_reviewer_escapes_dollar_signs_in_markdown(ran):
    """Streamlit markdown treats $...$ as LaTeX; a reason with two amounts rendered as math."""
    at = AppTest.from_file(str(ROOT / "app" / "pages" / "1_Reviewer_Queue.py"), default_timeout=30).run()
    queue = load_queue()
    over_cap = queue[queue.rule_id == "over_cap"].request_id.iloc[0]
    at.selectbox(key="selected_request").set_value(over_cap).run()
    assert not at.exception
    why = next(m.value for m in at.markdown if m.value.startswith("**Why it is here:**"))
    assert "\\$200" in why and "\\$150" in why
    assert "$2" not in why.replace("\\$", "")
