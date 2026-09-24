"""The nightly suite check must say how many tests failed, not quote one of them.

C7b recorded only the last line of pytest's output that mentioned a failure. On 2026-09-22 that
line was one FAILED test, and the board read as "one test is red" for a suite with eighteen
failures, most of them red since 2026-09-14 to 09-16. A single line is a sample, not a count.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "health_check_suite_evidence_under_test", _ROOT / "scripts" / "health_check.py"
)
assert _SPEC and _SPEC.loader
HEALTH = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(HEALTH)

RED = """\
........F..F
=========================== short test summary info ============================
FAILED tests/unit/test_a.py::test_one - AssertionError: x
FAILED tests/unit/test_b.py::test_two - ValueError: y
ERROR tests/unit/test_c.py::test_three - FileNotFoundError: z
FAILED tests/unit/test_d.py::test_four
2 failed, 1 error, 500 passed in 460.12s (0:07:40)
"""


def test_a_red_suite_reports_the_count_and_names_the_failures() -> None:
    evidence = HEALTH._suite_evidence(RED)
    assert evidence.startswith("4 failing: ")
    for name in ("test_a.py::test_one", "test_b.py::test_two", "test_c.py::test_three"):
        assert name in evidence
    assert "2 failed, 1 error, 500 passed" in evidence


def test_more_failures_than_fit_are_counted_not_dropped() -> None:
    out = "\n".join(f"FAILED tests/unit/test_{i}.py::test_x - boom" for i in range(40))
    evidence = HEALTH._suite_evidence(out + "\n40 failed in 1.0s\n")
    assert evidence.startswith("40 failing: ")
    assert "+35 more" in evidence
    assert len(evidence) <= 400


def test_a_green_suite_reports_pytests_own_summary() -> None:
    assert HEALTH._suite_evidence("....\n1234 passed in 400.0s\n") == "1234 passed in 400.0s"


def test_the_suite_check_uses_the_counting_evidence() -> None:
    source = (_ROOT / "scripts" / "health_check.py").read_text()
    body = source.split("def check_suite():", 1)[1].split("\ndef ", 1)[0]
    assert "evidence=_suite_evidence(out)" in body


def test_the_full_suite_output_is_saved_where_the_board_can_cite_it(tmp_path: Path) -> None:
    target = tmp_path / "var" / "health" / "suite_last.log"
    HEALTH.save_suite_output(RED, str(target))
    assert target.read_text(encoding="utf-8") == RED
    assert not target.with_name("suite_last.log.tmp").exists()
    assert HEALTH.SUITE_LOG.endswith("var/health/suite_last.log")


def test_check_suite_saves_what_pytest_printed(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "suite_last.log"
    recorded: list[tuple] = []
    monkeypatch.setattr(HEALTH, "SUITE_LOG", str(target))
    monkeypatch.setattr(HEALTH, "wait_for_tick_lock", lambda: (0, False))
    monkeypatch.setattr(HEALTH, "sh", lambda *args, **kwargs: (1, RED))
    monkeypatch.setattr(HEALTH, "add", lambda *args, **kwargs: recorded.append((args, kwargs)))
    assert HEALTH.check_suite() is False
    assert target.read_text(encoding="utf-8") == RED
    ((args, kwargs),) = recorded
    assert args[0] == "C7b-suite" and "full output" in kwargs["observed"]
