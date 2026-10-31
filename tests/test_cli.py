import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args, env_extra=None):
    env = {**os.environ, **(env_extra or {}), "ANTHROPIC_API_KEY": ""}  # empty beats .env
    return subprocess.run([sys.executable, "-m", "src.cli", *args], capture_output=True, text=True, env=env, cwd=ROOT)


def test_decide_pending_without_llm(tmp_path):
    out = tmp_path / "decisions.jsonl"
    res = run_cli("decide", "data/pending.csv", "--no-llm", "--out", str(out))
    assert res.returncode == 0, res.stderr
    assert "approve" in res.stdout and "route" in res.stdout and "policy v1" in res.stdout
    records = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(records) == 20
    assert {"request_id", "outcome", "queue", "rule_id", "reason", "policy_version", "facts_used"} <= set(records[0])


def test_decide_rerun_replaces_records_for_same_ids(tmp_path):
    out = tmp_path / "decisions.jsonl"
    run_cli("decide", "data/pending.csv", "--no-llm", "--out", str(out))
    run_cli("decide", "data/pending.csv", "--no-llm", "--out", str(out))
    records = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(records) == 20


def test_decide_with_explicit_policy_version(tmp_path):
    res = run_cli("decide", "data/pending.csv", "--no-llm", "--policy", "1", "--out", str(tmp_path / "d.jsonl"))
    assert res.returncode == 0 and "policy v1" in res.stdout


def test_decide_missing_file_fails_cleanly(tmp_path):
    res = run_cli("decide", "data/nope.csv", "--no-llm", "--out", str(tmp_path / "d.jsonl"))
    assert res.returncode != 0 and "nope.csv" in (res.stderr + res.stdout)


def test_console_script_installed(tmp_path):
    import shutil
    exe = shutil.which("refund-agent", path=str(Path(sys.executable).parent))
    assert exe, "pip install -e . should provide the refund-agent command"
    res = subprocess.run([exe, "decide", "data/pending.csv", "--no-llm", "--out", str(tmp_path / "d.jsonl")],
                         capture_output=True, text=True, cwd=ROOT, env={**os.environ, "ANTHROPIC_API_KEY": ""})
    assert res.returncode == 0 and "policy v1" in res.stdout


def test_backtest_command_passes_on_v1(tmp_path):
    res = run_cli("backtest", "--no-llm", "--policy", "1", "--no-write")
    assert res.returncode == 0, res.stderr
    assert "VERDICT: PASS" in res.stdout and "RF-2074" in res.stdout and "| cap |" in res.stdout


def test_backtest_command_fails_on_bad_policy(tmp_path):
    import json
    from src.policy.store import load_policy
    bad_dir = tmp_path / "policies"
    bad_dir.mkdir()
    p = load_policy(1).model_dump()
    p["rules"].append({"id": "loose", "name": "loose", "description": "approve any wrong item",
                       "when": [{"field": "stated_reason", "op": "==", "value": "wrong_item"}], "then": "approve"})
    (bad_dir / "v1.json").write_text(json.dumps(p))
    res = run_cli("backtest", "--no-llm", "--policy-dir", str(bad_dir), "--no-write")
    assert res.returncode == 1 and "VERDICT: FAIL" in res.stdout and "RF-1006" in res.stdout


def test_decide_without_key_reports_llm_unavailable(tmp_path):
    res = run_cli("decide", "data/pending.csv", "--out", str(tmp_path / "d.jsonl"))  # run_cli strips the key
    assert res.returncode == 0
    assert "LLM unavailable" in (res.stdout + res.stderr) or "facts unknown" in (res.stdout + res.stderr)
    assert "facts: LLM extractor not wired yet" not in (res.stdout + res.stderr)
