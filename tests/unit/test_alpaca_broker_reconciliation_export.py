from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "export_alpaca_broker_reconciliation.py"
SPEC = importlib.util.spec_from_file_location("export_alpaca_broker_reconciliation", SCRIPT)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def _curve(path: Path) -> list[tuple[int, float]]:
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT ts, equity_quote FROM equity_curve ORDER BY ts").fetchall()
    finally:
        con.close()


def test_replace_curve_removes_stale_rows_and_keeps_current_snapshot(tmp_path: Path) -> None:
    db = tmp_path / "trading.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE equity_curve (ts INTEGER PRIMARY KEY, equity_quote REAL)")
    con.execute("INSERT INTO equity_curve VALUES (999, 999999)")
    con.commit()
    con.close()

    rows = MOD._replace_curve(db, [(1000, 100.0), (2000, 101.0)], (2500, 101.5))

    assert rows == [(1000, 100.0), (2000, 101.0), (2500, 101.5)]
    assert _curve(db) == rows


def test_degraded_broker_history_preserves_last_good_curve(tmp_path: Path) -> None:
    db = tmp_path / "trading.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE equity_curve (ts INTEGER PRIMARY KEY, equity_quote REAL)")
    con.execute("INSERT INTO equity_curve VALUES (1000, 100)")
    con.commit()
    con.close()

    with pytest.raises(ValueError, match="fewer than two"):
        MOD._replace_curve(db, [(2000, 101.0)], (2500, 101.5))

    assert _curve(db) == [(1000, 100.0)]


def test_compare_requires_real_overlap_and_reports_missing_broker_marks() -> None:
    result = MOD._compare([(1000, 100.0), (2000, 101.0)], [(1000, 100.0)])
    assert result["overlapping_marks"] == 1
    assert result["broker_marks_missing_locally"] == 1
    assert result["all_overlapping_marks_match_to_cent"] is True

    empty = MOD._compare([(1000, 100.0)], [])
    assert empty["all_overlapping_marks_match_to_cent"] is False


def test_compare_fails_when_same_timestamp_differs_by_more_than_cent() -> None:
    result = MOD._compare([(1000, 100.0)], [(1000, 100.02)])
    assert result["max_absolute_equity_difference"] == pytest.approx(0.02)
    assert result["all_overlapping_marks_match_to_cent"] is False


def test_public_holdings_are_broker_weighted_and_side_correct() -> None:
    holdings = MOD._public_holdings(
        [
            {"symbol": "SPY", "qty": "10", "market_value": "6000"},
            {"symbol": "IWM", "qty": "-20", "market_value": "-4000"},
        ],
        equity=10000.0,
        as_of="2026-08-22",
    )

    assert holdings["source"] == "ALPACA_CURRENT_POSITIONS"
    assert holdings["broker_reconciled"] is True
    assert holdings["long"] == [{"ticker": "SPY", "weight_pct": 60.0}]
    assert holdings["short"] == [{"ticker": "IWM", "weight_pct": 40.0}]
    assert holdings["gross_pct"] == 100.0
    assert holdings["net_pct"] == 20.0


def test_account_env_loader_does_not_consult_ambient_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "sleeve.env"
    path.write_text("APCA_API_KEY_ID=dedicated\nAPCA_API_SECRET_KEY=sleeve-secret\n")
    monkeypatch.setenv("APCA_API_KEY_ID", "wrong-global-account")

    loaded = MOD._load_account_env(path)

    assert loaded["APCA_API_KEY_ID"] == "dedicated"


@pytest.mark.workspace_evidence
def test_persisted_reconciliation_is_hash_valid_and_covers_three_unique_accounts() -> None:
    artifact = (
        Path(__file__).resolve().parents[2]
        / "artifacts/engineering/alpaca_broker_reconciliation.json"
    )
    if not artifact.exists():
        pytest.skip("run scripts/export_alpaca_broker_reconciliation.py")
    payload = json.loads(artifact.read_text())
    content_hash = payload.pop("content_hash")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    assert "sha256:" + hashlib.sha256(canonical).hexdigest() == content_hash
    assert payload["author"] == "Arhan Canli"
    assert payload["summary"]["status"] == "PASS"
    assert payload["summary"]["reconciled_alpaca_sleeves"] == 3
    assert payload["summary"]["unique_dedicated_accounts"] is True
    assert all(row["passes"] for row in payload["sleeves"].values())
    assert all(
        row["comparison_after_refresh"]["broker_marks_missing_locally"] == 0
        for row in payload["sleeves"].values()
    )
