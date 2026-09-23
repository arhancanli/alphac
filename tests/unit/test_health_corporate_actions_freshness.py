"""The health board must see when the corporate-actions lake stops being refreshed.

scripts/corp_actions_weekly.sh was written on 2026-08-02, run once by hand, and never scheduled.
No split or dividend entered data/lake after that pass, so every split announced later reached the
live equity panel as a fake crash or spike, the failure class the job's own header describes
(ALIT, a phantom -4.95% day that tripped the drawdown brake). Nothing on the board could see it:
the daily ticks kept firing and the bar lake kept advancing. Found 2026-09-23, seven weeks late.
The check reads the dataset the engine consumes, not the scheduler, like C6e-deribit.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "health_check_corporate_actions_under_test", _ROOT / "scripts" / "health_check.py"
)
assert _SPEC and _SPEC.loader
HEALTH = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(HEALTH)


def _lake(tmp_path: Path, age_hours: float | None) -> Path:
    root = tmp_path / "corporate_actions"
    (root / "year=2026").mkdir(parents=True)
    if age_hours is not None:
        leaf = root / "year=2026" / "part-0.parquet"
        leaf.write_bytes(b"PAR1")
        stamp = HEALTH.NOW.timestamp() - age_hours * 3600
        os.utime(leaf, (stamp, stamp))
    return root


@pytest.mark.parametrize(
    ("age_hours", "status"),
    [
        (20.0, "PASS"),
        (8 * 24 - 1, "PASS"),
        (8 * 24 + 1, "WARN"),
        (15 * 24 + 1, "FAIL"),
        # The state found on 2026-09-23: last write 2026-08-02, 52 days earlier.
        (52 * 24, "FAIL"),
    ],
)
def test_status_follows_the_age_of_the_newest_partition(
    tmp_path: Path, age_hours: float, status: str
) -> None:
    HEALTH.RESULTS.clear()
    HEALTH.check_corporate_actions(str(_lake(tmp_path, age_hours)))
    (row,) = [r for r in HEALTH.RESULTS if r["id"] == "C6h-corporate-actions"]
    assert row["status"] == status
    assert row["severity"] == "high"


def test_an_empty_lake_fails_rather_than_passing_silently(tmp_path: Path) -> None:
    HEALTH.RESULTS.clear()
    HEALTH.check_corporate_actions(str(_lake(tmp_path, None)))
    (row,) = [r for r in HEALTH.RESULTS if r["id"] == "C6h-corporate-actions"]
    assert row["status"] == "FAIL"
    assert row["observed"] == "no partitions"


def test_the_board_runs_the_check_against_the_live_lake() -> None:
    source = (_ROOT / "scripts" / "health_check.py").read_text()
    body = source.split("def check_loops():", 1)[1].split("\ndef ", 1)[0]
    assert "check_corporate_actions(" in body
    assert HEALTH.CORPORATE_ACTIONS_LAKE.endswith(os.path.join("data", "lake", "corporate_actions"))
