from src.decisions import append_records, read_records, reset


def test_append_and_read_round_trip(tmp_path):
    path = tmp_path / "d.jsonl"
    append_records(path, [{"request_id": "RF-1", "outcome": "approve"}])
    append_records(path, [{"request_id": "RF-2", "outcome": "route", "facts": {"a": None}}])
    assert read_records(path) == [{"request_id": "RF-1", "outcome": "approve"},
                                  {"request_id": "RF-2", "outcome": "route", "facts": {"a": None}}]


def test_read_missing_file_is_empty(tmp_path):
    assert read_records(tmp_path / "nope.jsonl") == []


def test_reset_removes_file(tmp_path):
    path = tmp_path / "d.jsonl"
    append_records(path, [{"x": 1}])
    reset(path)
    assert read_records(path) == [] and not path.exists()
    reset(path)  # idempotent
