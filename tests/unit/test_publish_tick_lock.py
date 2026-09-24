"""The nightly publish and the hourly tick never regenerate the shared evidence at the same time.

2026-09-24: the publish ran into the 22:25 tick; the tick rewrote the broker reconciliation and
forward_evidence_maturity.json mid-publish and research_export refused on source drift.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TICK = (ROOT / "scripts" / "live_tick.sh").read_text(encoding="utf-8")
PUBLISH = (ROOT / "scripts" / "live_publish.sh").read_text(encoding="utf-8")


def _first_work_line(script: str) -> int:
    return next(
        n
        for n, line in enumerate(script.splitlines())
        if re.match(r"^\s*(uv run|\./scripts/)", line)
    )


def _line_of(script: str, needle: str) -> int:
    return next(n for n, line in enumerate(script.splitlines()) if needle in line)


def test_both_scripts_take_or_honour_the_publish_lock_before_any_work() -> None:
    assert _line_of(PUBLISH, 'mkdir "$PUBLISH_LOCK"') < _first_work_line(PUBLISH)
    assert _line_of(TICK, 'if [ -d "$PUBLISH_LOCK" ]') < _first_work_line(TICK)
    assert "var/locks/live_publish.lock" in TICK and "var/locks/live_publish.lock" in PUBLISH


def _tick_guard() -> str:
    lines = TICK.splitlines()
    start = _line_of(TICK, 'PUBLISH_LOCK="var/locks/live_publish.lock"')
    end = next(n for n in range(start, len(lines)) if lines[n].strip() == "fi")
    return "\n".join(lines[start : end + 1]) + "\necho WORK_RAN\n"


def _run_guard(workdir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/zsh", "-c", _tick_guard()], cwd=workdir, capture_output=True, text=True, check=False
    )


def test_a_tick_steps_aside_while_a_publish_runs_and_ignores_a_dead_publishs_lock(
    tmp_path: Path,
) -> None:
    (tmp_path / "var" / "log").mkdir(parents=True)
    lock = tmp_path / "var" / "locks" / "live_publish.lock"
    assert "WORK_RAN" in _run_guard(tmp_path).stdout  # no publish: the tick works

    lock.mkdir(parents=True)
    result = _run_guard(tmp_path)
    assert result.returncode == 0 and "WORK_RAN" not in result.stdout
    assert "skipping this hour" in (tmp_path / "var" / "log" / "live_tick.log").read_text()

    stale = time.time() - 4 * 3600
    os.utime(lock, (stale, stale))
    assert "WORK_RAN" in _run_guard(tmp_path).stdout  # a 4-hour-old lock is a dead run's
