"""The health run must START after the tick's lock clears and END before the next tick starts.

The waiting is in ``check_suite`` (``test_health_suite_waits_for_tick.py``); this test pins the
arithmetic of the schedule itself. Given the start minute in the tracked plist template, the
bounded lock wait and the suite budget, the run's worst-case window may not contain the tick's
minute. It was 03:10 with a 45-minute budget: every 23:10Z run straddled 23:25Z.

On the Mac that runs the monitor the installed plist must match the template, so a schedule
edited by hand in ``~/Library/LaunchAgents`` cannot drift from the reviewed one.
"""

from __future__ import annotations

import importlib.util
import plistlib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "health_check_schedule_under_test", _ROOT / "scripts" / "health_check.py"
)
assert _SPEC and _SPEC.loader
HEALTH = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(HEALTH)

TEMPLATE = _ROOT / "deploy" / "com.accapital.health.plist.template"
INSTALLED = Path.home() / "Library" / "LaunchAgents" / "com.accapital.health.plist"


def _load(path: Path) -> dict:
    with path.open("rb") as fh:
        return plistlib.load(fh)


def test_template_is_tracked_and_names_the_monitor() -> None:
    assert TEMPLATE.exists(), "deploy/com.accapital.health.plist.template is missing"
    d = _load(TEMPLATE)
    assert d["Label"] == "com.accapital.health"
    assert d["ProgramArguments"][0] == "/usr/bin/python3"
    assert d["ProgramArguments"][1].endswith("/alphaforge/scripts/health_check.py")


def test_worst_case_window_cannot_contain_the_tick_minute() -> None:
    d = _load(TEMPLATE)
    cal = d["StartCalendarInterval"]
    start = cal["Minute"]
    worst_case_minutes = (HEALTH.TICK_LOCK_MAX_WAIT_S + HEALTH.SUITE_BUDGET_S) / 60
    assert worst_case_minutes < 60, "a window over an hour always contains the tick"
    end = start + worst_case_minutes
    tick = HEALTH.TICK_MINUTE
    contained = any((start <= m <= end) for m in (tick, tick + 60))
    assert not contained, (
        f"health starts :{start:02d}, worst case ends :{end % 60:04.1f} "
        f"(wait {HEALTH.TICK_LOCK_MAX_WAIT_S}s + budget {HEALTH.SUITE_BUDGET_S}s); "
        f"the tick at :{tick:02d} falls inside"
    )
    assert start > tick, "start after the tick's minute so the lock wait is the normal case"


def test_installed_plist_matches_the_template() -> None:
    if not INSTALLED.exists():
        import pytest

        pytest.skip("not the machine that runs the monitor")
    t, i = _load(TEMPLATE), _load(INSTALLED)
    for key in ("Label", "ProgramArguments", "StartCalendarInterval"):
        assert t[key] == i[key], (key, t[key], i[key])
