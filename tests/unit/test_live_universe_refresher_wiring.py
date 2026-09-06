"""The live loop's monthly universe refresh was never wired.

``LiveLoop`` has carried a ``universe_refresher`` seam since 2026-08-11, with the self-healing
catch-up that repairs a missed monthly rebalance. ``paper_cmds._build_loop`` never passed one,
so the seam and its repair were dead code live and the crypto sleeve kept trading the
cross-section selected on 2026-06-01. Found 2026-09-05 during the frozen-rebalance audit.

Two guards. The adapter must (a) rebuild through the SAME asset-class-scoped builder the
``universe rebuild`` CLI uses, over ``[backfill_start, cycle_ts]`` with ``now=cycle_ts``, and
(b) report the newest rebalance on record for THIS asset class only, so a fresh equity
rebalance in the shared store cannot mask a stale crypto membership. And the wiring must
actually reach ``LiveLoop(...)`` -- a static check on the builder function, because a
constructor default of ``None`` is exactly how this stayed unwired for four weeks.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pyarrow as pa

from alphaforge.cli.paper_cmds import _UniverseRefresherAdapter
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.universe.store import UniverseStore

DAY = 86_400_000
JUN = 1_780_272_000_000  # 2026-06-01T00:00Z
JUL = JUN + 30 * DAY
AUG = JUL + 31 * DAY


def _inst(iid: str, cls: AssetClass) -> Instrument:
    perp = cls is AssetClass.CRYPTO_PERP
    return Instrument(
        instrument_id=iid,
        asset_class=cls,
        market_type=MarketType.PERP if perp else MarketType.CASH,
        base=iid.split(":")[2].removesuffix("USDT" if perp else "USD"),
        quote="USDT" if perp else "USD",
        tick_size=0.01,
        lot_size=1.0,
        min_qty=1.0,
        min_notional=0.0,
        can_short=True,
        maker_fee_bps=1.0,
        taker_fee_bps=1.0,
        funding_interval_hours=8 if perp else None,
        listed_ts=JUN - 400 * DAY,
        delisted_ts=None,
    )


class _FakeBuilder:
    def __init__(self) -> None:
        self.calls: list[dict[str, int]] = []

    def rebuild(self, *, start: int, end: int, now: int) -> object:
        self.calls.append({"start": start, "end": end, "now": now})
        return object()


def _stores(tmp_path: Path) -> tuple[UniverseStore, InstrumentStore]:
    universe = UniverseStore(LakePaths(tmp_path / "lake"))
    universe.write_intervals(
        pa.table(
            {
                "instrument_id": pa.array(
                    ["BINANCE:PERP:BTCUSDT", "BINANCE:PERP:ETHUSDT", "XUSE:CASH:AAPLUSD"],
                    type=pa.string(),
                ),
                "effective_from": pa.array([JUN, JUN, AUG], type=pa.timestamp("ms", tz="UTC")),
                "effective_to": pa.array([None, None, None], type=pa.timestamp("ms", tz="UTC")),
                "rank": pa.array([1, 2, 1], type=pa.int32()),
                "reason": pa.array(["enter"] * 3, type=pa.string()),
            }
        )
    )
    instruments = InstrumentStore(tmp_path / "ops.sqlite")
    instruments.upsert(_inst("BINANCE:PERP:BTCUSDT", AssetClass.CRYPTO_PERP), as_of=JUN - 1000)
    instruments.upsert(_inst("BINANCE:PERP:ETHUSDT", AssetClass.CRYPTO_PERP), as_of=JUN - 1000)
    instruments.upsert(_inst("XUSE:CASH:AAPLUSD", AssetClass.EQUITY), as_of=JUN - 1000)
    return universe, instruments


def test_newest_rebalance_is_scoped_to_the_asset_class(tmp_path: Path) -> None:
    universe, instruments = _stores(tmp_path)
    try:
        crypto = _UniverseRefresherAdapter(
            _FakeBuilder(), universe, instruments, AssetClass.CRYPTO_PERP, start_ms=JUN - 365 * DAY
        )
        equity = _UniverseRefresherAdapter(
            _FakeBuilder(), universe, instruments, AssetClass.EQUITY, start_ms=JUN - 365 * DAY
        )
        assert crypto.newest_rebalance_ms() == JUN  # the August equity rebalance must not mask it
        assert equity.newest_rebalance_ms() == AUG
    finally:
        instruments.close()


def test_refresh_rebuilds_from_backfill_start_to_the_cycle(tmp_path: Path) -> None:
    universe, instruments = _stores(tmp_path)
    builder = _FakeBuilder()
    try:
        adapter = _UniverseRefresherAdapter(
            builder, universe, instruments, AssetClass.CRYPTO_PERP, start_ms=JUN - 365 * DAY
        )
        adapter.refresh(cycle_ts=AUG + 5 * DAY)
        assert builder.calls == [
            {"start": JUN - 365 * DAY, "end": AUG + 5 * DAY, "now": AUG + 5 * DAY}
        ]
    finally:
        instruments.close()


def test_an_empty_class_reports_unknown_not_stale(tmp_path: Path) -> None:
    universe, instruments = _stores(tmp_path)
    try:
        adapter = _UniverseRefresherAdapter(
            _FakeBuilder(), universe, instruments, AssetClass.FUTURE, start_ms=JUN
        )
        assert adapter.newest_rebalance_ms() is None
    finally:
        instruments.close()


def test_build_loop_passes_a_refresher_to_the_live_loop() -> None:
    """Static: the LiveLoop(...) call inside _build_loop names universe_refresher=. A default of
    None is how the seam stayed unwired for four weeks, so the wiring itself is under test."""
    src = Path(__file__).resolve().parents[2] / "src/alphaforge/cli/paper_cmds.py"
    tree = ast.parse(src.read_text())
    build = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_build_loop"
    )
    calls = [
        n
        for n in ast.walk(build)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "LiveLoop"
    ]
    assert len(calls) == 1
    keywords = {k.arg for k in calls[0].keywords}
    assert "universe_refresher" in keywords, "LiveLoop is built without a universe_refresher again"
    value = next(k.value for k in calls[0].keywords if k.arg == "universe_refresher")
    assert not (isinstance(value, ast.Constant) and value.value is None), (
        "universe_refresher=None is not wiring"
    )
