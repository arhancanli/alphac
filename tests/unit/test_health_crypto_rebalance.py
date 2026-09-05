"""The health monitor must see a crypto rebalance that died, and one that never came.

2026-09-05: the crypto sleeve's weekly rebalance crashed four Thursdays running. The
existing checks could not see it. ``C6a`` asks whether hourly marks still accrue (they
did), ``C6b`` reads the status of the LATEST cycle (an hourly ``ok`` hold overwrote
the failed rebalance within the hour). The sleeve held stale positions for 37 days and
the 03:10 health run said PASS every night.

Two checks close that hole, both read straight from the trading DB with sqlite3 (no
shell-out): the age of the last cycle that actually emitted a book, and any failed
cycle in the trailing window.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "health_check_crypto_rebalance_under_test", _ROOT / "scripts" / "health_check.py"
)
assert _SPEC and _SPEC.loader
HEALTH = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(HEALTH)

HOUR_MS = 3_600_000
WEEK_MS = 168 * HOUR_MS


def _db(tmp_path: Path, rows: list[tuple[int, str, str]]) -> Path:
    """A trading DB with only the ``cycles`` table the checks read."""
    db = tmp_path / "trading_crypto_perp.sqlite"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE cycles (cycle_ts INTEGER PRIMARY KEY, started_ms INTEGER, "
        "finished_ms INTEGER, status TEXT, detail TEXT)"
    )
    con.executemany(
        "INSERT INTO cycles VALUES (?, ?, ?, ?, ?)",
        [(ts, ts, ts + 1000, status, detail) for ts, status, detail in rows],
    )
    con.commit()
    con.close()
    return db


def _now_ms() -> int:
    return int(HEALTH.NOW.timestamp() * 1000)


def _hourly_holds(start_ms: int, end_ms: int) -> list[tuple[int, str, str]]:
    return [
        (ts, "ok", "hold: no target change (hold_between_rebalance=1)")
        for ts in range(start_ms, end_ms, HOUR_MS)
    ]


def _results(monkeypatch, db: Path) -> dict[str, dict]:
    monkeypatch.setattr(HEALTH, "CRYPTO_DB", str(db))
    monkeypatch.setattr(HEALTH, "RESULTS", [])
    HEALTH.check_crypto_rebalance()
    return {r["id"]: r for r in HEALTH.RESULTS}


def test_a_rebalance_within_cadence_and_no_failures_pass(tmp_path: Path, monkeypatch) -> None:
    now = _now_ms()
    last_rebalance = now - 3 * 24 * HOUR_MS
    rows = _hourly_holds(now - 8 * 24 * HOUR_MS, now)
    rows = [r for r in rows if r[0] != last_rebalance]
    rows.append((last_rebalance, "ok", "orders=15 filled=15 partial=0 rejected=0 skipped_replay=0"))
    res = _results(monkeypatch, _db(tmp_path, rows))
    assert res["C6f-crypto-rebalance"]["status"] == "PASS"
    assert res["C6g-crypto-failed-cycles"]["status"] == "PASS"


def test_the_incident_shape_is_red_on_both_checks(tmp_path: Path, monkeypatch) -> None:
    """Hourly holds all 'ok', the weekly bars 'failed' with the real KeyError, and
    the last book emitted 37 days ago. This exact DB read PASS on 2026-09-05."""
    now = _now_ms()
    last_book = now - 37 * 24 * HOUR_MS
    rows = _hourly_holds(now - 40 * 24 * HOUR_MS, now)
    rows = [r for r in rows if r[0] != last_book]
    rows.append((last_book, "ok", "orders=15 filled=15 partial=0 rejected=0 skipped_replay=0"))
    failed_ts = [last_book + k * WEEK_MS for k in (2, 3, 4, 5)]
    rows = [r for r in rows if r[0] not in failed_ts]
    rows += [
        (ts, "failed", "KeyError: \"instrument 'XUSE:CASH:AALUSD' is unknown to the SCD2 store\"")
        for ts in failed_ts
    ]
    res = _results(monkeypatch, _db(tmp_path, rows))
    assert res["C6f-crypto-rebalance"]["status"] == "FAIL"
    assert res["C6g-crypto-failed-cycles"]["status"] == "FAIL"
    assert "AALUSD" in res["C6g-crypto-failed-cycles"]["evidence"]


def test_one_failed_hourly_cycle_is_a_warning_not_a_red(tmp_path: Path, monkeypatch) -> None:
    """A single transient failure (a venue blip on a hold bar) is worth a WARN; it is
    the weekly cadence going dark that is red."""
    now = _now_ms()
    last_rebalance = now - 2 * 24 * HOUR_MS
    rows = _hourly_holds(now - 8 * 24 * HOUR_MS, now)
    rows = [r for r in rows if r[0] != last_rebalance]
    rows.append((last_rebalance, "ok", "orders=3 filled=3 partial=0 rejected=0 skipped_replay=0"))
    blip = now - 30 * HOUR_MS
    rows = [r for r in rows if r[0] != blip]
    rows.append((blip, "failed", "NetworkError: binanceusdm GET .../depth?symbol=XRPUSDT"))
    res = _results(monkeypatch, _db(tmp_path, rows))
    assert res["C6f-crypto-rebalance"]["status"] == "PASS"
    assert res["C6g-crypto-failed-cycles"]["status"] == "WARN"


def test_no_book_ever_emitted_is_red(tmp_path: Path, monkeypatch) -> None:
    now = _now_ms()
    res = _results(monkeypatch, _db(tmp_path, _hourly_holds(now - 10 * 24 * HOUR_MS, now)))
    assert res["C6f-crypto-rebalance"]["status"] == "FAIL"


def test_kill_switch_engaged_is_an_intentional_halt(tmp_path: Path, monkeypatch) -> None:
    now = _now_ms()
    db = _db(tmp_path, _hourly_holds(now - 10 * 24 * HOUR_MS, now))
    monkeypatch.setattr(HEALTH, "CRYPTO_DB", str(db))
    monkeypatch.setattr(HEALTH, "RESULTS", [])
    HEALTH.check_crypto_rebalance(kill_on=True)
    res = {r["id"]: r for r in HEALTH.RESULTS}
    assert res["C6f-crypto-rebalance"]["status"] == "PASS"
    assert "KILL" in res["C6f-crypto-rebalance"]["observed"]
