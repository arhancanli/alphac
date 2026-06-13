"""Unit tests for alphaforge.analytics.walkforward.WalkForwardRunner.

Drives the runner over a synthetic tmp_path lake with a stub
:class:`SignalSource` (a constant-mu frame), asserting the ORCHESTRATION
contract rather than alpha:

* legs tile the evaluable grid; the first ``train_bars`` are warm-up only;
* equity COMPOUNDS across legs (leg k starts at leg k-1's final equity, no
  resets);
* the stitched OOS curve is contiguous and ordered;
* ``save`` writes the documented artifact layout;
* the run is deterministic.

Offline, tmp_path only.
"""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.analytics.walkforward import WalkForwardRunner
from alphaforge.config.settings import Settings
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.costs import TransactionCostModel
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.portfolio.strategy import BlendStrategy

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from alphaforge.backtest import StaticCostInputs
    from alphaforge.core.time import Ms

HOUR = 3_600_000
T0 = 1_672_531_200_000
N_BARS = 1_200
IDS = tuple(f"BINANCE:PERP:{b}USDT" for b in ("BTC", "ETH", "SOL", "ADA"))


def _closes(seed: int, n: int, level: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.asarray(level * np.exp(np.cumsum(rng.normal(0.0, 0.004, n))))


def _ohlcv_table(per_inst: dict[str, np.ndarray]) -> pa.Table:
    iids: list[str] = []
    ts: list[int] = []
    opens: list[float] = []
    closes: list[float] = []
    for iid, close in per_inst.items():
        n = len(close)
        iids.extend([iid] * n)
        ts.extend(T0 + k * HOUR for k in range(n))
        opens.append(float(close[0]))
        opens.extend(float(v) for v in close[:-1])
        closes.extend(float(v) for v in close)
    n_rows = len(iids)
    return pa.table(
        {
            "instrument_id": pa.array(iids, type=pa.string()),
            "ts_open": pa.array(ts, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array(opens, type=pa.float64()),
            "high": pa.array([v * 1.002 for v in closes], type=pa.float64()),
            "low": pa.array([v * 0.998 for v in closes], type=pa.float64()),
            "close": pa.array(closes, type=pa.float64()),
            "volume": pa.array([10.0] * n_rows, type=pa.float64()),
            "quote_volume": pa.array([1.0e6] * n_rows, type=pa.float64()),
            "n_trades": pa.array([42] * n_rows, type=pa.int64()),
            "quality_flags": pa.array([0] * n_rows, type=pa.int32()),
            "ingested_at": pa.array(
                [t + HOUR + 1000 for t in ts], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def _instrument(instrument_id: str) -> Instrument:
    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base=instrument_id.split(":")[2].removesuffix("USDT"),
        quote="USDT",
        tick_size=0.01,
        lot_size=0.0001,
        min_qty=0.0001,
        min_notional=5.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=T0 - 365 * 24 * HOUR,
        delisted_ts=None,
    )


class _ConstMuSource:
    """A stub SignalSource: a constant-mu_ann frame over the requested window.

    Distinct per-id mu gives the rank allocator a stable book, so the runner's
    ORCHESTRATION (tiling, compounding, stitching) is what is under test.
    """

    def compute_research(self, start: Ms, end: Ms) -> pd.DataFrame:
        opens = list(range(start, end, HOUR))
        rows: list[dict[str, object]] = []
        for k, iid in enumerate(IDS):
            for ts_open in opens:
                rows.append(
                    {
                        "ts_open": ts_open,
                        "instrument_id": iid,
                        "alpha_blend": float(k - 1.5),
                        "mu_ann": 0.04 * float(k - 1.5),
                    }
                )
        return pd.DataFrame(rows).set_index(["ts_open", "instrument_id"]).sort_index()


@dataclasses.dataclass(frozen=True)
class World:
    reader: PITDataReader
    store: InstrumentStore
    universe: UniverseStore
    cost_model: TransactionCostModel
    cost_inputs: StaticCostInputs
    settings: Settings


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    from alphaforge.backtest import StaticCostInputs

    tmp = tmp_path_factory.mktemp("walkforward")
    paths = LakePaths(tmp / "lake")
    closes = {iid: _closes(3 + k, N_BARS, 30.0 * (k + 1)) for k, iid in enumerate(IDS)}
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(closes))

    universe = UniverseStore(paths)
    universe.write_intervals(
        pa.table(
            {
                "instrument_id": pa.array(list(IDS), type=pa.string()),
                "effective_from": pa.array([T0] * len(IDS), type=pa.timestamp("ms", tz="UTC")),
                "effective_to": pa.array([None] * len(IDS), type=pa.timestamp("ms", tz="UTC")),
                "rank": pa.array([1] * len(IDS), type=pa.int32()),
                "reason": pa.array(["enter_top40"] * len(IDS), type=pa.string()),
            }
        )
    )
    store = InstrumentStore(tmp / "ops.sqlite")
    for iid in IDS:
        store.upsert(_instrument(iid), as_of=T0 - 365 * 24 * HOUR)
    yield World(
        reader=PITDataReader(paths),
        store=store,
        universe=universe,
        cost_model=TransactionCostModel.from_settings(Settings()),
        cost_inputs=StaticCostInputs(adv_quote=1.0e8, sigma_daily=0.05),
        settings=Settings(),
    )
    store.close()


def _runner(world: World) -> WalkForwardRunner:
    return WalkForwardRunner(
        world.reader,
        world.store,
        world.universe,
        world.cost_model,
        _ConstMuSource(),
        world.settings,
        cost_inputs=world.cost_inputs,
    )


# train 300 bars, test 200 bars; over 1200 bars -> 5 legs (200*4 + 100 tail).
_TRAIN, _TEST = 300, 200


def test_legs_tile_and_equity_compounds(world: World) -> None:
    result = _runner(world).run(
        T0,
        T0 + N_BARS * HOUR,
        train_bars=_TRAIN,
        test_bars=_TEST,
        rebalance_bars=24,
        cov_min_periods=120,
    )
    # 1200 - 300 = 900 test bars / 200 → ceil = 5 legs.
    assert len(result.legs) == 5
    # Test spans tile [train_start, end) with no overlap or gap.
    for prev, nxt in zip(result.legs, result.legs[1:], strict=False):
        assert nxt.test_start == prev.test_end
    assert result.legs[0].test_start == T0 + _TRAIN * HOUR
    assert result.legs[-1].test_end == T0 + N_BARS * HOUR
    # Equity compounds: each leg starts at the prior leg's final equity.
    for prev, nxt in zip(result.legs, result.legs[1:], strict=False):
        assert nxt.result.equity.iloc[0] == pytest.approx(prev.result.equity.iloc[-1], rel=1e-9)
    # The stitched curve is the per-leg curves concatenated, strictly ordered.
    assert result.equity.index.is_monotonic_increasing
    assert result.equity.iloc[0] == pytest.approx(100_000.0, rel=0.5)


def test_save_writes_artifact_layout(world: World, tmp_path: Path) -> None:
    out = tmp_path / "wf_out"
    result = _runner(world).run(
        T0,
        T0 + (300 + 400) * HOUR,  # 2 legs
        train_bars=_TRAIN,
        test_bars=_TEST,
        rebalance_bars=24,
        cov_min_periods=120,
        out_dir=out,
    )
    assert (out / "equity.parquet").exists()
    assert (out / "walkforward.json").exists()
    assert (out / "summary.txt").exists()
    assert (out / "tearsheet.png").exists()
    for leg in result.legs:
        assert (out / "legs" / f"leg_{leg.leg:02d}").is_dir()
    saved = pd.read_parquet(out / "equity.parquet")
    assert list(saved.columns) == ["ts", "equity"]
    assert len(saved) == len(result.equity)

    # F-D / F-E: walkforward.json carries the per-leg risk counters AND the
    # aggregate (the operator's confession — how every bar was produced).
    meta = json.loads((out / "walkforward.json").read_text(encoding="utf-8"))
    expected_keys = {
        "n_rebalances",
        "n_fallback_used",
        "hold_between_rebalance",
        "hold_stale_signal",
        "hold_cov_cold_start",
        "hold_degenerate_xsection",
        "bars_halted_flat",
        "bars_half_gross",
    }
    assert set(meta["config"]["risk_counters"]) == expected_keys
    for leg_row in meta["legs"]:
        assert set(leg_row["risk_counters"]) == expected_keys
    # Per-leg deltas sum to the aggregate (load_leg never resets counters).
    for key in expected_keys:
        per_leg_sum = sum(row["risk_counters"][key] for row in meta["legs"])
        assert per_leg_sum == meta["config"]["risk_counters"][key]
    # A healthy multi-leg rank run trades; it is not all holds/halts.
    assert meta["config"]["risk_counters"]["n_rebalances"] > 0


def _signal_frame_over(start: Ms, end: Ms) -> pd.DataFrame:
    """A constant-mu_ann frame over ``[start, end)`` (the _ConstMuSource shape)."""
    return _ConstMuSource().compute_research(start, end)


def test_load_leg_persists_ladder_across_boundary(world: World) -> None:
    """F-A: ONE strategy reused across legs persists the drawdown ladder, so a
    drawdown straddling a leg boundary trips FLAT_HALT on the TRUE running HWM
    where a fresh-per-leg ladder (HWM reseeded to leg-open equity) would not.

    Leg 0: equity rises to a high-water mark of 100k, then draws down to 87k
    (13% < the 15% flat threshold) -> HALF_GROSS, not yet halted. The leg
    boundary then restarts FLAT at 87k. Leg 1: equity continues down to 84k.
    Against the leg-0 HWM (100k) that is a 16% drawdown -> FLAT_HALTED. Against
    a fresh ladder reseeded to 87k it is only ~3.4% -> never halts. The
    persisted strategy halts; a fresh-per-leg strategy does not."""
    flat_threshold = abs(world.settings.risk.dd_flat_halt)  # 0.15
    assert flat_threshold == pytest.approx(0.15)

    persisted = BlendStrategy(
        world.settings,
        signal_frame=_signal_frame_over(T0, T0 + 600 * HOUR),
        rebalance_bars=24,
        cov_min_periods=120,
    )
    # Leg 0 equity path: HWM 100k, draw to 87k (below the flat threshold).
    for equity in (100_000.0, 95_000.0, 90_000.0, 87_000.0):
        persisted.ladder.update(equity)
    assert persisted.ladder.state.name == "HALF_GROSS"  # 13% dd, not halted

    # Leg boundary: swap the signal frame, preserving the ladder (state + HWM).
    persisted.load_leg(_signal_frame_over(T0 + 300 * HOUR, T0 + 900 * HOUR))
    assert persisted.ladder.state.name == "HALF_GROSS"  # SURVIVED the boundary
    assert persisted.ladder.hwm == pytest.approx(100_000.0)  # TRUE running HWM

    # Leg 1 continues down to 84k -> 16% from the persisted HWM -> FLAT_HALTED.
    persisted.ladder.update(84_000.0)
    assert persisted.ladder.state.name == "FLAT_HALTED"

    # A fresh-per-leg strategy (the OLD optimistic behaviour) would reseed the
    # HWM to leg-1's first print, so the same 84k is only a tiny drawdown and
    # never halts.
    fresh = BlendStrategy(
        world.settings,
        signal_frame=_signal_frame_over(T0 + 300 * HOUR, T0 + 900 * HOUR),
        rebalance_bars=24,
        cov_min_periods=120,
    )
    fresh.ladder.update(84_000.0)  # fresh HWM = 84k
    assert fresh.ladder.state.name == "NORMAL"  # would NOT halt -> optimistic curve


def test_load_leg_resets_rebalance_schedule_and_is_live_mode_guarded(world: World) -> None:
    """load_leg resets the per-leg rebalance schedule (flat restart re-enters
    promptly) and is forbidden in live mode (no per-leg frame)."""
    strat = BlendStrategy(
        world.settings,
        signal_frame=_signal_frame_over(T0, T0 + 600 * HOUR),
        rebalance_bars=24,
        cov_min_periods=120,
    )
    strat.load_leg(_signal_frame_over(T0 + 300 * HOUR, T0 + 900 * HOUR))  # no raise
    live = BlendStrategy(
        world.settings, mu_provider=lambda _ts: {}, rebalance_bars=24, cov_min_periods=120
    )
    with pytest.raises(RuntimeError, match="precomputed-mode only"):
        live.load_leg(_signal_frame_over(T0, T0 + 600 * HOUR))


def test_runner_aggregate_counters_match_legs(world: World) -> None:
    """F-A/F-D/F-E: the runner exposes per-leg risk_counters whose deltas sum to
    the aggregate in config (proving one persistent strategy across legs)."""
    result = _runner(world).run(
        T0,
        T0 + N_BARS * HOUR,
        train_bars=_TRAIN,
        test_bars=_TEST,
        rebalance_bars=24,
        cov_min_periods=120,
    )
    agg = result.config["risk_counters"]
    assert isinstance(agg, dict)
    for key, total in agg.items():
        assert sum(int(leg.risk_counters[key]) for leg in result.legs) == total
    assert agg["n_rebalances"] > 0


def test_deterministic(world: World) -> None:
    kw = {
        "train_bars": _TRAIN,
        "test_bars": _TEST,
        "rebalance_bars": 24,
        "cov_min_periods": 120,
    }
    a = _runner(world).run(T0, T0 + 900 * HOUR, **kw)  # type: ignore[arg-type]
    b = _runner(world).run(T0, T0 + 900 * HOUR, **kw)  # type: ignore[arg-type]
    pd.testing.assert_series_equal(a.equity, b.equity)
