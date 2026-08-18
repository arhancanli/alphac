"""The health board must inspect Deribit artifacts, not merely the scheduled process."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "health_check_deribit_under_test", _ROOT / "scripts" / "health_check.py"
)
assert _SPEC and _SPEC.loader
HEALTH = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(HEALTH)


def test_latest_file_age_uses_newest_artifact(tmp_path: Path) -> None:
    old = tmp_path / "snap_2026-08-14.jsonl"
    new = tmp_path / "snap_2026-08-15.jsonl"
    old.write_text("old")
    new.write_text("new")
    now = HEALTH.NOW.timestamp()
    os.utime(old, (now - 72 * 3600, now - 72 * 3600))
    os.utime(new, (now - 10 * 3600, now - 10 * 3600))
    age, path = HEALTH._latest_file_age_hours(str(tmp_path), "snap_*.jsonl")
    assert age == 10.0
    assert path == str(new)


def test_latest_file_age_is_loud_when_no_snapshot_exists(tmp_path: Path) -> None:
    age, path = HEALTH._latest_file_age_hours(str(tmp_path), "snap_*.jsonl")
    assert age is None
    assert path == ""
