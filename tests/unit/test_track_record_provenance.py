from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name: str):
    path = REPO / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_track_provenance_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def modules():
    return _load("glassbox_export"), _load("research_export")


def _state(curve: list[dict[str, object]]) -> dict[str, object]:
    return {
        "go_live_date": "2026-08-07",
        "live_curve": curve,
        "research_curve": [
            {"date": "2020-01-01", "equity": 100_000.0},
            {"date": "2020-01-02", "equity": 100_100.0},
        ],
        "transparency": ["paper only"],
    }


def test_realized_state_curve_is_truthfully_labelled_on_both_exports(
    modules, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    glassbox, research = modules
    state = _state(
        [
            {"date": "2026-08-07", "equity": 100_000.0},
            {"date": "2026-08-08", "equity": 98_500.0},
        ]
    )
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    reconciliation = tmp_path / "alpaca_broker_reconciliation.json"
    reconciliation.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(glassbox, "REPO", tmp_path)
    monkeypatch.setattr(glassbox, "STATE_JSON", state_path)
    monkeypatch.setattr(glassbox, "ALPACA_RECONCILIATION_JSON", reconciliation)

    glassbox_record = glassbox.build_track_record()
    research_record = research.build_track_record(state)
    for record in (glassbox_record, research_record):
        assert "broker-derived composite marks" in record["live_source"]
        assert "go-live seed" not in record["live_source"]
        assert record["live_provenance"]["legacy_sqlite_authoritative"] is False


def test_stale_sqlite_cannot_override_the_composite(
    modules, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    glassbox, _ = modules
    state = _state(
        [
            {"date": "2026-08-07", "equity": 100_000.0},
            {"date": "2026-08-22", "equity": 98_495.86},
        ]
    )
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    stale_db = tmp_path / "trading.sqlite"
    with sqlite3.connect(stale_db) as connection:
        connection.execute("CREATE TABLE equity_curve (ts INTEGER, equity_quote REAL)")
        connection.execute("INSERT INTO equity_curve VALUES (1, 777777.0)")
    monkeypatch.setattr(glassbox, "REPO", tmp_path)
    monkeypatch.setattr(glassbox, "STATE_JSON", state_path)
    monkeypatch.setattr(glassbox, "TRADING_SQLITE", stale_db)
    monkeypatch.setattr(
        glassbox, "ALPACA_RECONCILIATION_JSON", tmp_path / "missing-reconciliation.json"
    )

    record = glassbox.build_track_record()
    assert record["live_nav_current_usd"] == 98_495.86
    assert all(point["nav_usd"] != 777_777.0 for point in record["live_curve"])


def test_single_unchanged_point_is_the_only_seed_label(modules) -> None:
    _, research = modules
    record = research.build_track_record(
        _state([{"date": "2026-08-07", "equity": 100_000.0}])
    )
    assert record["live_source"] == "go-live seed (no realized marks have accrued yet)"
