"""The map's schedule column must say when a job runs, including hourly and weekly jobs.

It printed the hourly live tick (`{"Minute": 25}`, no Hour) as "0*:25 daily", and would have
printed the weekly corporate-actions job as "22:00 daily", hiding the one fact a reader needs:
how often splits and dividends are refreshed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "system_map_schedule_labels", REPO / "scripts" / "build_system_map.py"
)
assert _spec is not None and _spec.loader is not None
system_map = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = system_map
_spec.loader.exec_module(system_map)


@pytest.mark.parametrize(
    ("calendar", "label"),
    [
        ({"Hour": 9, "Minute": 0}, "09:00 daily"),
        ({"Minute": 25}, "hourly at :25"),
        ({"Weekday": 6, "Hour": 22, "Minute": 0}, "Sat 22:00 weekly"),
        ({"Weekday": 0, "Hour": 3, "Minute": 5}, "Sun 03:05 weekly"),
        ({"Weekday": 7, "Hour": 3, "Minute": 5}, "Sun 03:05 weekly"),
        ([{"Hour": 2, "Minute": 20}, {"Hour": 8, "Minute": 20}], "2 times daily"),
    ],
)
def test_calendar_labels(calendar: object, label: str) -> None:
    assert system_map._calendar_label(calendar) == label
