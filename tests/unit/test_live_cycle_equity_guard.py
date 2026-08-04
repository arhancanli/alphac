"""Regression: live_cycle's equity target book drops non-XUSE ids (2026-07-18).

Defect 2 of the marking-fix campaign, executor side: the equity WF artifact
historically contained ``BINANCE:PERP:*`` position rows (unscoped universe). The
WF is now scoped at the source, but ``scripts/live_cycle.py::_target_weights``
carries a defense-in-depth guard: the equity profile's sized book must NEVER
contain a non-XUSE instrument, and anything dropped is printed loudly.

This test drives the REAL ``_target_weights`` (imported from the script) over a
fake ``artifacts/walkforward/equity_live_fwd`` leg containing a crypto row.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "live_cycle.py"


def _load_live_cycle():
    spec = importlib.util.spec_from_file_location("live_cycle_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["live_cycle_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_leg(root: Path, wf: str, rows: list[tuple[int, str, float]]) -> None:
    leg = root / "artifacts" / "walkforward" / wf / "legs" / "leg_00"
    leg.mkdir(parents=True)
    tbl = pa.table(
        {
            "ts": pa.array([r[0] for r in rows], type=pa.int64()),
            "instrument_id": pa.array([r[1] for r in rows], type=pa.string()),
            "qty": pa.array([1.0] * len(rows), type=pa.float64()),
            "mark": pa.array([10.0] * len(rows), type=pa.float64()),
            "weight": pa.array([r[2] for r in rows], type=pa.float64()),
            "unreal_pnl": pa.array([0.0] * len(rows), type=pa.float64()),
        }
    )
    pq.write_table(tbl, leg / "positions.parquet")


def test_equity_target_book_drops_binance_perp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ts = 1_752_800_000_000
    _write_leg(
        tmp_path,
        "equity_live_fwd",
        [
            (ts, "XUSE:CASH:AAPLUSD", 0.05),
            (ts, "XUSE:CASH:MSFTUSD", -0.03),
            (ts, "BINANCE:PERP:BTCUSDT", 0.04),  # the leak: must NEVER reach Alpaca
        ],
    )
    monkeypatch.chdir(tmp_path)
    mod = _load_live_cycle()
    w = mod._target_weights("equity")
    out = capsys.readouterr().out
    assert set(w) == {"XUSE:CASH:AAPLUSD", "XUSE:CASH:MSFTUSD"}
    assert "BINANCE:PERP:BTCUSDT" not in w
    assert "ASSET-CLASS GUARD" in out
    assert "BINANCE:PERP:BTCUSDT" in out


def test_managed_futures_book_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard is equity-profile-only: the MF path is byte-identical (all-XUSE
    anyway, and the campaign forbids touching MF behavior)."""
    ts = 1_752_800_000_000
    _write_leg(
        tmp_path,
        "mf_live_fwd",
        [(ts, "XUSE:CASH:SPYUSD", 0.10), (ts, "XUSE:CASH:GLDUSD", 0.05)],
    )
    monkeypatch.chdir(tmp_path)
    mod = _load_live_cycle()
    w = mod._target_weights("managed_futures")
    assert set(w) == {"XUSE:CASH:SPYUSD", "XUSE:CASH:GLDUSD"}
