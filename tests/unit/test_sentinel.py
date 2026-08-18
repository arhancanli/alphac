"""The 24/7 sentinel observes running artifacts without mutating them."""

from __future__ import annotations

import datetime as dt
import importlib.util
import os
import sqlite3
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("sentinel_under_test", _ROOT / "scripts/sentinel.py")
assert _SPEC and _SPEC.loader
SENTINEL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(SENTINEL)
NOW = dt.datetime(2026, 8, 16, tzinfo=dt.UTC)


def _seed(root: Path, *, age_h: float = 1.0, status: str = "ok") -> None:
    (root / "var").mkdir(parents=True)
    ts = int((NOW.timestamp() - age_h * 3600) * 1000)
    con = sqlite3.connect(root / "var" / "trading_crypto_perp.sqlite")
    con.execute("CREATE TABLE cycles(cycle_ts INTEGER,status TEXT)")
    con.execute("INSERT INTO cycles VALUES (?,?)", (ts, status))
    con.commit()
    con.close()
    con = sqlite3.connect(root / "var" / "maker_shadow.sqlite")
    con.execute("CREATE TABLE quotes(ts INTEGER,method_version INTEGER)")
    con.execute("INSERT INTO quotes VALUES (?,2)", (ts,))
    con.commit()
    con.close()
    snap = root / "data" / "deribit" / "snapshots" / "snap_2026-08-15.jsonl"
    snap.parent.mkdir(parents=True)
    snap.write_text("{}\n")
    os.utime(snap, (NOW.timestamp() - 10 * 3600, NOW.timestamp() - 10 * 3600))


def _statuses(payload: dict) -> dict[str, str]:
    return {check["id"]: check["status"] for check in payload["checks"]}


def test_green_snapshot_reads_artifacts_and_never_opens_writable_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path)
    monkeypatch.setattr(SENTINEL, "_timer_active", lambda _name: (True, "active"))
    payload = SENTINEL.collect(tmp_path, now=NOW)
    assert payload["overall"] == "PASS"
    assert payload["mutations_permitted"] == ["own_status_file"]


def test_stale_cycle_and_bad_status_fail_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path, age_h=4.0, status="error")
    monkeypatch.setattr(SENTINEL, "_timer_active", lambda _name: (True, "active"))
    payload = SENTINEL.collect(tmp_path, now=NOW)
    statuses = _statuses(payload)
    assert payload["overall"] == "FAIL"
    assert statuses["crypto-cycle-freshness"] == "FAIL"
    assert statuses["crypto-cycle-status"] == "FAIL"
    assert statuses["maker-shadow-freshness"] == "FAIL"


def test_inactive_timer_and_missing_deribit_are_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path)
    for path in (tmp_path / "data" / "deribit" / "snapshots").glob("*"):
        path.unlink()
    monkeypatch.setattr(
        SENTINEL, "_timer_active", lambda name: (name != "af-trade.timer", "inactive")
    )
    payload = SENTINEL.collect(tmp_path, now=NOW)
    statuses = _statuses(payload)
    assert statuses["timer:af-trade.timer"] == "FAIL"
    assert statuses["deribit-freshness"] == "FAIL"


def test_atomic_writer_replaces_only_its_own_status_file(tmp_path: Path) -> None:
    path = tmp_path / "sentinel" / "status.json"
    SENTINEL._write_atomic(path, {"overall": "PASS"})
    assert path.read_text() == '{\n  "overall": "PASS"\n}\n'
    assert list(path.parent.iterdir()) == [path]
