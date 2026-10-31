from src.policy_notes import load_policy_notes, notes_for


def test_load_policy_notes_has_seven():
    notes = load_policy_notes()
    assert len(notes) == 7 and notes[2].startswith("Change of mind")


def test_notes_for_reason_and_fraud():
    assert [n for n, _ in notes_for("changed_mind", fraud_flag=False)] == [2]
    assert [n for n, _ in notes_for("arrived_damaged", fraud_flag=False)] == [3]
    assert [n for n, _ in notes_for("never_arrived", fraud_flag=False)] == [4]
    assert [n for n, _ in notes_for("wrong_item", fraud_flag=False)] == [6]
    assert [n for n, _ in notes_for("late_delivery", fraud_flag=False)] == [6]
    assert [n for n, _ in notes_for("wrong_size", fraud_flag=False)] == [1]
    assert [n for n, _ in notes_for("never_arrived", fraud_flag=True)] == [5, 4]
