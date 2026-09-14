"""C11-external-ledgers must carry the audit's verdict onto the nightly board, and must not
read silence as green: an audit that produced nothing is a WARN, never a PASS."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "health_check_external_ledgers_under_test", _ROOT / "scripts" / "health_check.py"
)
assert _SPEC and _SPEC.loader
HEALTH = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(HEALTH)


def _document(status: str) -> dict:
    return {
        "status": status,
        "external_identities_not_in_canonical": 118,
        "external_trees": [{"path": "/x/alphac-clone"}],
        "canonical": {"distinct_hypothesis_identities": 229},
        "merged_distinct_hypothesis_identities": 347,
        "budget": 400,
        "staged_reviews_reached_without_record": [320],
    }


def _run(monkeypatch, tmp_path: Path, document: dict | None, rc: int = 1) -> dict:
    monkeypatch.setattr(HEALTH, "RESULTS", [])
    monkeypatch.setattr(HEALTH, "HEALTH", str(tmp_path))
    calls: list[str] = []

    def fake_sh(cmd: str, timeout: int = 120, env=None):
        calls.append(cmd)
        if document is not None:
            (tmp_path / "external_ledgers.json").write_text(json.dumps(document))
        return rc, "audit output"

    monkeypatch.setattr(HEALTH, "sh", fake_sh)
    HEALTH.check_external_ledgers()
    assert calls and "audit_external_experiment_ledgers.py" in calls[0]
    assert str(tmp_path / "external_ledgers.json") in calls[0]
    return {r["id"]: r for r in HEALTH.RESULTS}["C11-external-ledgers"]


@pytest.mark.parametrize(
    ("audit_status", "expected"),
    [
        ("CANONICAL_UNION_COMPLETE", "PASS"),
        ("EXTERNAL_IDENTITIES_UNRECONCILED", "WARN"),
        ("STAGED_REVIEW_REACHED_WITHOUT_RECORD", "FAIL"),
        ("MERGED_UNION_EXCEEDS_BUDGET", "FAIL"),
        ("SOMETHING_NEW", "FAIL"),
    ],
)
def test_the_audit_verdict_maps_onto_the_board(monkeypatch, tmp_path, audit_status, expected):
    row = _run(monkeypatch, tmp_path, _document(audit_status))
    assert row["status"] == expected
    assert row["group"] == "honesty"
    assert "118 external identities" in row["observed"]
    assert "347/400" in row["observed"]


def test_no_result_is_a_warning_not_a_pass(monkeypatch, tmp_path):
    row = _run(monkeypatch, tmp_path, None, rc=2)
    assert row["status"] == "WARN"
    assert "produced no result" in row["observed"]


def test_a_crash_exit_code_is_a_warning_even_if_a_stale_result_exists(monkeypatch, tmp_path):
    row = _run(monkeypatch, tmp_path, _document("CANONICAL_UNION_COMPLETE"), rc=2)
    assert row["status"] == "WARN"


def test_the_check_is_wired_into_main() -> None:
    source = (_ROOT / "scripts" / "health_check.py").read_text()
    main_body = source[source.index("def main():") :]
    assert "check_external_ledgers()" in main_body
