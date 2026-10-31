"""Read and write policy versions as policies/vN.json. Versions are never overwritten."""
from __future__ import annotations

import re
from pathlib import Path

from src import settings
from src.logging_setup import get_logger
from src.schemas.policy import Policy

log = get_logger("policy.store")
_RE_VERSION = re.compile(r"^v(\d+)\.json$")


def _dir(policy_dir: Path | None) -> Path:
    return Path(policy_dir) if policy_dir is not None else settings.POLICY_DIR


def policy_path(version: int, policy_dir: Path | None = None) -> Path:
    return _dir(policy_dir) / f"v{version}.json"


def list_versions(policy_dir: Path | None = None) -> list[int]:
    d = _dir(policy_dir)
    if not d.exists():
        return []
    versions = [int(m.group(1)) for p in d.iterdir() if (m := _RE_VERSION.match(p.name))]
    return sorted(versions)


def load_policy(version: int | None = None, policy_dir: Path | None = None) -> Policy:
    """Load one version, or the highest one when version is None."""
    if version is None:
        versions = list_versions(policy_dir)
        if not versions:
            raise FileNotFoundError(f"no policy files in {_dir(policy_dir)}")
        version = versions[-1]
    path = policy_path(version, policy_dir)
    if not path.exists():
        raise FileNotFoundError(path)
    return Policy.model_validate_json(path.read_text())


def save_policy(policy: Policy, policy_dir: Path | None = None) -> Path:
    path = policy_path(policy.version, policy_dir)
    if path.exists():
        raise FileExistsError(f"{path} already exists; policy versions are immutable")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(policy.model_dump_json(indent=2))
    log.info("saved policy v%d (%d facts, %d rules): %s", policy.version, len(policy.facts), len(policy.rules), policy.changelog)
    return path
