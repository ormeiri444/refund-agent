import pytest

from src.schemas.policy import Policy, Rule
from src.policy.store import list_versions, load_policy, policy_path, save_policy


def policy(v: int) -> Policy:
    return Policy(version=v, changelog=f"v{v}", created_at="2026-10-30",
                  rules=[Rule(id="r", name="r", when=[], then="route")])


def test_save_then_load_round_trip(tmp_path):
    path = save_policy(policy(1), policy_dir=tmp_path)
    assert path == policy_path(1, policy_dir=tmp_path) == tmp_path / "v1.json"
    assert load_policy(1, policy_dir=tmp_path) == policy(1)


def test_load_latest_picks_highest_version(tmp_path):
    for v in (1, 3, 2):
        save_policy(policy(v), policy_dir=tmp_path)
    assert load_policy(policy_dir=tmp_path).version == 3
    assert list_versions(policy_dir=tmp_path) == [1, 2, 3]


def test_save_refuses_overwrite(tmp_path):
    save_policy(policy(1), policy_dir=tmp_path)
    with pytest.raises(FileExistsError):
        save_policy(policy(1), policy_dir=tmp_path)


def test_load_missing_version_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_policy(7, policy_dir=tmp_path)


def test_load_latest_with_no_policies_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_policy(policy_dir=tmp_path)
