"""CI tripwire for engine materialization at universe scale (A5-5).

A marked-``slow`` memory+time guard, NOT a fix: it builds a synthetic temp-lake
universe of >100 perps over a modest hourly history and runs the smallest
meaningful pipeline slice the engine supports — one ``EventDrivenBacktester.run``
over the full universe with a single trade decision (then hold). The full run
exercises the load-bearing materialization cost: ``_load_bars`` turns the bulk
PIT ``ohlcv`` read into a ``dict[str, dict[Ms, BarView]]`` with one ``BarView``
dataclass per (instrument, bar) — i.e. ``names * bars`` Python objects — before
the event loop walks the bar-close grid.

The test asserts ``tracemalloc`` peak and wall-time stay under EXPLICIT budgets.
The budgets are set GENEROUSLY from a measured baseline so the test passes today
and only fails if the materialization REGRESSES (e.g. someone makes the per-bar
map quadratic in the universe size, or holds the whole lake table resident on
top of the per-instrument maps). It is deliberately marked ``slow`` so it does
not bloat the default test run; deselect with ``-m 'not slow'``.

Measured baseline (local, deterministic peak): 120 names x 336 hourly bars
(= 40 320 rows) -> tracemalloc peak ~30 MB, wall ~0.8 s. The budgets below are
roughly 3x the peak and 10x the wall, leaving ample headroom for slower CI
hardware and cold filesystem caches while still tripping on a multiplicative
materialization blowup.

The crypto production math is untouched: this is a new test file that wires the
public engine exactly as the golden master does (``StaticCostInputs`` so no
``LakeCostInputs`` lake re-read confounds the profile).
"""

from __future__ import annotations

import time
import tracemalloc
from pathlib import Path

import pyarrow as pa
import pytest

from alphaforge.backtest.engine import (
    EventDrivenBacktester,
    ScriptedStrategy,
    StaticCostInputs,
)
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.costs import TransactionCostModel
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter

pytestmark = pytest.mark.slow

HOUR = 3_600_000
T0 = 1_704_153_600_000  # 2024-01-02T00:00:00Z — UTC midnight (1h/4h/8h aligned)
LISTED = 1_577_836_800_000  # 2020-01-01T00:00:00Z — well before the run

# Synthetic universe shape: comfortably > 100 names over a modest history. The
# product of the two is what stresses the per-bar BarView materialization.
N_NAMES = 120
N_BARS = 336  # two weeks of hourly bars

# Pinned cost-model constants (same regime as the golden master) so the fill
# arithmetic is well-defined; their exact values are irrelevant to the guard.
ADV = 1e8
SIGMA = 0.02
CASH0 = 100_000.0

# EXPLICIT budgets, set generously from the measured baseline above. They are
# a regression tripwire, not a tight bound — a healthy run sits far under both.
PEAK_BUDGET_BYTES = 96 * 1024 * 1024  # ~3.2x the ~30 MB baseline peak
WALL_BUDGET_S = 8.0  # ~10x the ~0.8 s baseline wall, headroom for slow CI


def _iid(i: int) -> str:
    return f"BINANCE:PERP:SY{i:03d}USDT"


def _make_instrument(instrument_id: str) -> Instrument:
    symbol = instrument_id.split(":")[2]
    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base=symbol.removesuffix("USDT"),
        quote="USDT",
        tick_size=0.1,
        lot_size=1.0,
        min_qty=1.0,
        min_notional=10.0,
        contract_multiplier=1.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=LISTED,
        delisted_ts=None,
    )


def _ohlcv_table(ids: list[str]) -> pa.Table:
    """``N_NAMES * N_BARS`` flat hourly bars, prices alternating tightly around a
    per-instrument base (nonzero but trivial returns — the guard profiles
    materialization, not strategy behaviour)."""
    instruments: list[str] = []
    ts_open: list[int] = []
    open_: list[float] = []
    high: list[float] = []
    low: list[float] = []
    close: list[float] = []
    volume: list[float] = []
    quote_volume: list[float] = []
    n_trades: list[int] = []
    quality_flags: list[int] = []
    ingested_at: list[int] = []
    for j, x in enumerate(ids):
        base = 20.0 + j
        for k in range(N_BARS):
            o = base + (k % 2) * 0.1
            c = base + ((k + 1) % 2) * 0.1
            instruments.append(x)
            ts_open.append(T0 + k * HOUR)
            open_.append(o)
            high.append(max(o, c) * 1.01)
            low.append(min(o, c) * 0.99)
            close.append(c)
            volume.append(10.0)
            quote_volume.append(1_000.0)
            n_trades.append(42)
            quality_flags.append(0)
            ingested_at.append(T0 + k * HOUR + HOUR + 30_000)
    _ts = pa.timestamp("ms", tz="UTC")
    return pa.table(
        {
            "instrument_id": pa.array(instruments, type=pa.string()),
            "ts_open": pa.array(ts_open, type=_ts),
            "open": pa.array(open_, type=pa.float64()),
            "high": pa.array(high, type=pa.float64()),
            "low": pa.array(low, type=pa.float64()),
            "close": pa.array(close, type=pa.float64()),
            "volume": pa.array(volume, type=pa.float64()),
            "quote_volume": pa.array(quote_volume, type=pa.float64()),
            "n_trades": pa.array(n_trades, type=pa.int64()),
            "quality_flags": pa.array(quality_flags, type=pa.int32()),
            "ingested_at": pa.array(ingested_at, type=_ts),
        }
    )


def _build_lake(root: Path) -> tuple[PITDataReader, InstrumentStore, list[str]]:
    ids = [_iid(i) for i in range(N_NAMES)]
    paths = LakePaths(root / "lake")
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(ids))
    store = InstrumentStore(root / "ops.sqlite")
    for x in ids:
        store.upsert(_make_instrument(x), as_of=1)
    return PITDataReader(paths), store, ids


@pytest.mark.no_cover
def test_engine_scale_memory_and_time_guard(tmp_path: Path) -> None:
    """One full run over >100 names stays under explicit peak/wall budgets.

    Tripwire only: a green run sits far below both budgets. A red run means the
    engine's per-bar ``BarView`` materialization (``_load_bars``) — or anything
    downstream that scales with ``names * bars`` — has regressed at universe
    scale and must be investigated before it reaches a real universe.

    Coverage tracing is disabled for this timing assertion: branch instrumentation
    multiplies the measured wall time while leaving the workload unchanged. Memory
    measurement remains active through ``tracemalloc``.
    """
    reader, store, ids = _build_lake(tmp_path)
    # Smallest meaningful slice: one decision early (open a tiny equal-weight
    # book), then hold for the rest of the grid. Every bar close is still walked,
    # so the full materialized bar map is touched.
    script = {T0 + 2 * HOUR: {x: 0.5 / len(ids) for x in ids}}
    engine = EventDrivenBacktester(
        reader,
        store,
        TransactionCostModel(),
        cost_inputs=StaticCostInputs(adv_quote=ADV, sigma_daily=SIGMA),
    )

    tracemalloc.start()
    try:
        start = time.perf_counter()
        result = engine.run(
            ScriptedStrategy(script),
            ids,
            start=T0,
            end=T0 + N_BARS * HOUR,
            initial_cash=CASH0,
        )
        wall_s = time.perf_counter() - start
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        store.close()

    # Sanity: the run actually exercised the full universe and grid (guards
    # against a future change silently no-op'ing the slice and hiding a regression).
    assert len(ids) > 100
    assert len(result.equity) == N_BARS

    assert peak_bytes < PEAK_BUDGET_BYTES, (
        f"engine materialization peak regressed: {peak_bytes / 1e6:.1f} MB "
        f">= budget {PEAK_BUDGET_BYTES / 1e6:.0f} MB at {len(ids)} names x "
        f"{N_BARS} bars (baseline ~30 MB)"
    )
    assert wall_s < WALL_BUDGET_S, (
        f"engine wall-time regressed: {wall_s:.2f} s >= budget {WALL_BUDGET_S:.1f} s "
        f"at {len(ids)} names x {N_BARS} bars (baseline ~0.8 s)"
    )
