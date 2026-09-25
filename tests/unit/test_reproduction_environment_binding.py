"""An environment binding holds only when the bound bytes are current or recoverable from git."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "reproduction_audit_under_test",
    ROOT / "scripts" / "audit_clean_workspace_reproduction_contracts.py",
)
assert _SPEC and _SPEC.loader
AUDIT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(AUDIT)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_current_historical_and_unrecoverable_bindings(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.test")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    lock = tmp_path / "uv.lock"
    lock.write_text("old\n")
    _git(tmp_path, "add", "uv.lock")
    _git(tmp_path, "commit", "-qm", "old")
    old = hashlib.sha256(b"old\n").hexdigest()
    lock.write_text("new\n")
    new = hashlib.sha256(b"new\n").hexdigest()

    current = AUDIT.environment_record(tmp_path, "uv.lock", new)
    assert current["binding_valid"] and current["binding_source"] == "current_file"

    historical = AUDIT.environment_record(tmp_path, "uv.lock", old)
    assert historical["binding_valid"] and historical["binding_source"].startswith("git:")

    never = AUDIT.environment_record(tmp_path, "uv.lock", "0" * 64)
    assert not never["binding_valid"] and never["binding_source"] == "unrecoverable"
