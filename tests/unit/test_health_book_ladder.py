"""C12-book-ladder must page the owner on a halt, fail when the consumer file is not bound to
the artifact, and never read a missing artifact as green."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "health_check_book_ladder_under_test", _ROOT / "scripts" / "health_check.py"
)
assert _SPEC and _SPEC.loader
HEALTH = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(HEALTH)


def _artifact(state: str, *, age_hours: float = 0.5, as_of_days: int = 0) -> dict:
    now = HEALTH.NOW
    return {
        "content_hash": "sha256:abc",
        "generated_at": (now - dt.timedelta(hours=age_hours)).isoformat(),
        "as_of": (now.date() - dt.timedelta(days=as_of_days)).isoformat(),
        "state": state,
        "gross_multiplier": {"NORMAL": 1.0, "HALF_GROSS": 0.5, "FLAT_HALTED": 0.0}[state],
        "drawdown": 0.028,
        "marks": 37,
        "halts": [] if state != "FLAT_HALTED" else [{"halted_on": "2026-09-10"}],
        "ladder": {"dd_half_frac": 0.055, "dd_flat_frac": 0.11},
        "activation": {"live": False},
    }


def _run(monkeypatch, tmp_path: Path, artifact: dict | None, current: dict | None) -> dict:
    monkeypatch.setattr(HEALTH, "RESULTS", [])
    monkeypatch.setattr(HEALTH, "AF", str(tmp_path))
    if artifact is not None:
        path = tmp_path / "artifacts" / "engineering" / "book_drawdown_ladder.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(artifact))
    if current is not None:
        path = tmp_path / "var" / "book_ladder" / "current.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current))
    HEALTH.check_book_ladder()
    return {r["id"]: r for r in HEALTH.RESULTS}["C12-book-ladder"]


BOUND = {"artifact_content_hash": "sha256:abc"}


@pytest.mark.parametrize(
    ("state", "expected", "severity"),
    [
        ("NORMAL", "PASS", "high"),
        ("HALF_GROSS", "WARN", "high"),
        ("FLAT_HALTED", "FAIL", "critical"),
    ],
)
def test_the_ladder_state_maps_onto_the_board(monkeypatch, tmp_path, state, expected, severity):
    row = _run(monkeypatch, tmp_path, _artifact(state), BOUND)
    assert row["status"] == expected and row["severity"] == severity
    assert "bound" in row["observed"] and "NOT BOUND" not in row["observed"]
    if state == "FLAT_HALTED":
        assert "owner rearm required" in row["observed"]


def test_an_unbound_consumer_file_fails_even_when_the_book_is_calm(monkeypatch, tmp_path):
    row = _run(monkeypatch, tmp_path, _artifact("NORMAL"), {"artifact_content_hash": "sha256:old"})
    assert row["status"] == "FAIL" and "NOT BOUND" in row["observed"]


def test_a_missing_artifact_or_consumer_file_is_a_failure_not_a_pass(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path / "a", None, BOUND)["status"] == "FAIL"
    assert _run(monkeypatch, tmp_path / "b", _artifact("NORMAL"), None)["status"] == "FAIL"


def test_a_stale_artifact_warns(monkeypatch, tmp_path):
    stale = _run(monkeypatch, tmp_path / "a", _artifact("NORMAL", age_hours=5), BOUND)
    assert stale["status"] == "WARN"
    old_marks = _run(monkeypatch, tmp_path / "b", _artifact("NORMAL", as_of_days=6), BOUND)
    assert old_marks["status"] == "WARN"


def test_the_check_is_wired_into_main() -> None:
    source = (_ROOT / "scripts" / "health_check.py").read_text()
    main_body = source[source.index("def main():") :]
    assert "check_book_ladder()" in main_body
