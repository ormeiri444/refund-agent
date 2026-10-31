from pathlib import Path

from src.policy.engine import decide_frame, decisions_to_frame
from src.policy.store import load_policy

POLICY_DIR = Path(__file__).resolve().parents[1] / "policies"


def test_v1_loads_and_validates():
    p = load_policy(1, policy_dir=POLICY_DIR)
    assert p.version == 1
    assert {"damage_photo_confirmed", "carrier_proof_of_delivery", "carrier_investigation_open",
            "card_confirmed_stolen", "our_error_confirmed"} <= set(p.fact_ids())
    assert p.rules[0].id == "fraud_flag_to_fraud_team" and p.rules[0].queue == "fraud"
    assert all(r.description for r in p.rules), "every rule needs a plain-words description for the reviewer"


def test_v1_never_approves_fraud_flag(history_df):
    p = load_policy(1, policy_dir=POLICY_DIR)
    frame = decisions_to_frame(decide_frame(history_df, p))
    flagged = history_df[history_df.fraud_flag == True].request_id
    assert (frame.set_index("request_id").loc[flagged, "outcome"] == "route").all()
    assert (frame.set_index("request_id").loc[flagged, "queue"] == "fraud").all()


def test_v1_routes_unknown_fraud_flag_and_amount(history_df):
    p = load_policy(1, policy_dir=POLICY_DIR)
    frame = decisions_to_frame(decide_frame(history_df, p)).set_index("request_id")
    assert frame.loc["RF-2134", "rule_id"] == "fraud_check_missing"


def test_v1_on_pending_runs_without_llm(pending_df):
    p = load_policy(1, policy_dir=POLICY_DIR)
    frame = decisions_to_frame(decide_frame(pending_df, p))
    assert len(frame) == len(pending_df)
    rule_ids = {r.id for r in p.rules} | {"default_route"}
    assert set(frame.rule_id) <= rule_ids
    assert (frame.outcome == "approve").any() and (frame.outcome == "route").any()


def test_v1_routes_conflicting_duplicate(pending_df):
    p = load_policy(1, policy_dir=POLICY_DIR)
    frame = decisions_to_frame(decide_frame(pending_df, p)).set_index("request_id")
    assert frame.loc["RF-2183", "rule_id"] == "duplicate_conflict"
