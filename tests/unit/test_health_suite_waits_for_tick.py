"""The nightly suite must not run while the hourly tick is rewriting the artifact set.

2026-09-06: ``C7b-suite`` had been red every night in the 30-day history. The first failing test
was ``build_research_export()`` raising "forward evidence maturity source drift: paper_state".
The 23:10Z run's ~20-minute suite straddled the 23:25Z tick, which rewrites
``data/paper/state.json`` and then ~15 artifacts over several minutes; a test that reads two of
them a minute apart sees a
binding that no longer matches. The suite was reporting the tick's progress, not the code.

``check_suite`` now waits (bounded) for ``var/locks/live_tick.lock`` to clear before starting,
records how long it waited, and warns if it gave up waiting. The schedule test next door proves
the run also ENDS before the next tick can start.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "health_check_tick_wait_under_test", _ROOT / "scripts" / "health_check.py"
)
assert _SPEC and _SPEC.loader
HEALTH = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(HEALTH)


class _Clock:
    def __init__(self, held_for_polls: int) -> None:
        self.polls = 0
        self.slept: list[float] = []
        self.held_for_polls = held_for_polls

    def isdir(self, path: str) -> bool:
        self.polls += 1
        return self.polls <= self.held_for_polls

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


def test_no_lock_means_no_wait() -> None:
    clock = _Clock(held_for_polls=0)
    waited, still_held = HEALTH.wait_for_tick_lock(
        "x.lock", max_wait_s=300, poll_s=15, isdir=clock.isdir, sleep=clock.sleep
    )
    assert (waited, still_held) == (0, False)
    assert clock.slept == []


def test_a_lock_that_clears_is_waited_out_and_measured() -> None:
    clock = _Clock(held_for_polls=3)
    waited, still_held = HEALTH.wait_for_tick_lock(
        "x.lock", max_wait_s=300, poll_s=15, isdir=clock.isdir, sleep=clock.sleep
    )
    assert still_held is False
    assert waited == 45
    assert clock.slept == [15, 15, 15]


def test_a_lock_that_never_clears_is_given_up_on_at_the_bound() -> None:
    clock = _Clock(held_for_polls=10_000)
    waited, still_held = HEALTH.wait_for_tick_lock(
        "x.lock", max_wait_s=60, poll_s=15, isdir=clock.isdir, sleep=clock.sleep
    )
    assert still_held is True
    assert waited == 60
    assert len(clock.slept) == 4


def _run_suite(monkeypatch, waited: int, still_held: bool) -> dict:
    monkeypatch.setattr(HEALTH, "RESULTS", [])
    monkeypatch.setattr(HEALTH, "wait_for_tick_lock", lambda *a, **k: (waited, still_held))
    monkeypatch.setattr(HEALTH, "sh", lambda *a, **k: (0, "1234 passed in 900s"))
    HEALTH.check_suite()
    return {r["id"]: r for r in HEALTH.RESULTS}


def test_check_suite_records_the_wait_and_stays_green(monkeypatch) -> None:
    res = _run_suite(monkeypatch, waited=45, still_held=False)
    assert res["C7b-suite"]["status"] == "PASS"
    assert "waited 45s" in res["C7b-suite"]["observed"]
    assert "C7c-tick-lock" not in res


def test_check_suite_warns_when_it_ran_beside_a_tick(monkeypatch) -> None:
    res = _run_suite(monkeypatch, waited=300, still_held=True)
    assert res["C7b-suite"]["status"] == "PASS"
    assert res["C7c-tick-lock"]["status"] == "WARN"
    assert "300s" in res["C7c-tick-lock"]["observed"]


def test_the_default_lock_is_the_ticks_lock() -> None:
    assert HEALTH.TICK_LOCK.endswith("var/locks/live_tick.lock")
    tick = (_ROOT / "scripts" / "live_tick.sh").read_text()
    assert 'LOCK="var/locks/live_tick.lock"' in tick, "live_tick.sh moved its lock; follow it"
