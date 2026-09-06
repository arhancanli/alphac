"""The validation API's status probe is both a health check and the keep-alive that stops the
free-tier store from pausing. The check must read the BODY, not just the status code: a 200 with
store_reachable=false is the failure this exists to catch."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "health_check_validation_api_under_test", _ROOT / "scripts" / "health_check.py"
)
assert _SPEC and _SPEC.loader
HEALTH = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(HEALTH)


def _run(monkeypatch, status: int, body: dict | None) -> dict:
    monkeypatch.setattr(HEALTH, "RESULTS", [])
    monkeypatch.setattr(HEALTH, "_http_json", lambda url, timeout=20: (status, body))
    HEALTH.check_validation_api()
    return {r["id"]: r for r in HEALTH.RESULTS}["C10-validation-api"]


def test_reachable_store_passes(monkeypatch) -> None:
    assert _run(monkeypatch, 200, {"data": {"store_reachable": True}})["status"] == "PASS"


def test_unreachable_store_fails_even_on_200(monkeypatch) -> None:
    assert _run(monkeypatch, 200, {"data": {"store_reachable": False}})["status"] == "FAIL"


def test_non_200_fails(monkeypatch) -> None:
    assert _run(monkeypatch, 503, {"data": {"store_reachable": False}})["status"] == "FAIL"


def test_unparseable_fails_closed(monkeypatch) -> None:
    assert _run(monkeypatch, 200, None)["status"] == "FAIL"


def test_usage_count_is_carried_into_the_observation_when_the_store_reports_it(monkeypatch) -> None:
    """2026-09-06: the status endpoint reports aggregate usage so arrival is measured, not assumed.
    The nightly mail is where the owner reads it, so the observation must carry the numbers."""
    row = _run(
        monkeypatch,
        200,
        {
            "data": {
                "store_reachable": True,
                "usage_available": True,
                "usage": {
                    "validations_today": 12,
                    "validations_total": 12,
                    "keys_issued_today": 5,
                    "as_of_utc_day": "2026-09-06",
                },
            }
        },
    )
    assert row["status"] == "PASS"
    assert "validations_today=12" in row["observed"]
    assert "keys_issued_today=5" in row["observed"]
    assert "validations_total=12" in row["observed"]


def test_missing_usage_is_named_not_faked(monkeypatch) -> None:
    row = _run(
        monkeypatch,
        200,
        {"data": {"store_reachable": True, "usage": None, "usage_available": False}},
    )
    assert row["status"] == "PASS"
    assert "usage unavailable" in row["observed"]
