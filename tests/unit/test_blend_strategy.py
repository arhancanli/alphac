"""Unit tests for alphaforge.portfolio.strategy.BlendStrategy.

The first full strategy, exercised through the REAL event-driven engine on a
synthetic tmp_path lake (no mocks of the seam it must honour):

* precomputed mu_ann drives a constraint-respecting book;
* the drawdown ladder flattens at the flat threshold and stays absorbing;
* a stale signal (older than ``staleness_max_bars``) makes the strategy HOLD
  rather than trade a dead feed;
* the live-mode ``mu_provider`` path produces the same kind of book.

Offline, deterministic, tmp_path only.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.backtest import EventDrivenBacktester, StaticCostInputs, StrategyContext
from alphaforge.config.settings import Settings
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.costs import TransactionCostModel
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.portfolio.strategy import BlendStrategy

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from alphaforge.core.time import Ms

HOUR = 3_600_000
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z
N_BARS = 520
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


@dataclasses.dataclass(frozen=True)
class World:
    reader: PITDataReader
    store: InstrumentStore
    cost_model: TransactionCostModel
    closes: dict[str, np.ndarray]
    settings: Settings


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    tmp = tmp_path_factory.mktemp("blend_strategy")
    paths = LakePaths(tmp / "lake")
    closes = {iid: _closes(7 + k, N_BARS, 40.0 * (k + 1)) for k, iid in enumerate(IDS)}
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(closes))
    store = InstrumentStore(tmp / "ops.sqlite")
    for iid in IDS:
        store.upsert(_instrument(iid), as_of=T0 - 365 * 24 * HOUR)
    yield World(
        reader=PITDataReader(paths),
        store=store,
        cost_model=TransactionCostModel.from_settings(Settings()),
        closes=closes,
        settings=Settings(),
    )
    store.close()


def _signal_frame(closes: dict[str, np.ndarray], *, mu: float) -> pd.DataFrame:
    """A constant-mu_ann signal frame over the full (ts_open, id) grid.

    A flat, finite mu makes the rank allocator deterministic: it longs the
    highest-mu names; with ties broken by id, it produces a stable book so the
    test asserts portfolio MECHANICS (caps, ladder, staleness), not alpha.
    """
    rows: list[dict[str, object]] = []
    for k, iid in enumerate(IDS):
        for j in range(len(closes[iid])):
            rows.append(
                {
                    "ts_open": T0 + j * HOUR,
                    "instrument_id": iid,
                    "alpha_blend": float(k - 1.5),  # distinct, stable ranks
                    "mu_ann": mu * float(k - 1.5),
                }
            )
    frame = pd.DataFrame(rows).set_index(["ts_open", "instrument_id"]).sort_index()
    return frame


def _run(world: World, strategy: BlendStrategy, *, start_bar: int, end_bar: int) -> object:
    engine = EventDrivenBacktester(
        world.reader,
        world.store,
        world.cost_model,
        cost_inputs=StaticCostInputs(adv_quote=1.0e8, sigma_daily=0.05),
        no_trade_band_frac=world.settings.portfolio.no_trade_band,
    )
    return engine.run(
        strategy,
        list(IDS),
        start=T0 + start_bar * HOUR,
        end=T0 + end_bar * HOUR,
        initial_cash=100_000.0,
    )


def test_precomputed_book_respects_caps(world: World) -> None:
    """mu_ann -> allocator -> overlay -> w_max clip -> book. The allocator
    enforces the per-asset cap (pre-overlay); the vol-target overlay TARGETS vol
    and would push a weight above w_max, but the F-H re-clip makes the per-name
    hard cap inviolable at DECISION time. Realized position weights can still
    drift a hair past w_max with intra-rebalance price moves, but the target the
    strategy emits never does, and gross stays bounded."""
    w_max = world.settings.portfolio.w_max
    frame = _signal_frame(world.closes, mu=0.05)
    strat = BlendStrategy(
        world.settings, signal_frame=frame, rebalance_bars=24, cov_min_periods=120
    )
    result = _run(world, strat, start_bar=0, end_bar=N_BARS)
    pos = result.positions  # type: ignore[attr-defined]
    assert not pos.empty
    assert result.counters["fills_applied"] > 0  # type: ignore[attr-defined]
    # The allocator's own output respects the per-asset cap exactly.
    assert strat.last_result is not None
    assert float(np.abs(strat.last_result.weights).max()) <= w_max + 1e-6
    # F-H: every emitted DECISION-time target weight is clipped to w_max (the
    # overlay no longer pushes a per-name weight past the cap).
    decision = _decision_target_weights(world, frame)
    assert decision  # at least one rebalance fired
    assert max(abs(w) for w in decision) <= w_max + 1e-9
    # Realized position weights drift only a hair past w_max with price moves.
    assert float(pos["weight"].abs().max()) <= w_max + 0.01
    # Realized gross stays comfortably under the gross cap.
    gross = pos["weight"].abs().groupby(pos["ts"]).sum()
    assert float(gross.max()) <= 1.0 + 0.05


def _decision_target_weights(world: World, frame: pd.DataFrame) -> list[float]:
    """Collect every non-empty target weight the strategy EMITS over a run.

    Wraps the strategy with a recorder so the test inspects decision-time
    targets (pre-engine-discretization), where the F-H per-name cap binds, not
    just the post-drift realized book.
    """
    recorded: list[float] = []
    strat = BlendStrategy(
        world.settings, signal_frame=frame, rebalance_bars=24, cov_min_periods=120
    )
    inner = strat.on_bar_close

    def recording(ctx: object) -> Mapping[str, float]:
        targets = inner(ctx)  # type: ignore[arg-type]
        recorded.extend(float(w) for w in targets.values())
        return targets

    strat.on_bar_close = recording  # type: ignore[assignment, method-assign]
    _run(world, strat, start_bar=0, end_bar=N_BARS)
    return recorded


def test_drawdown_ladder_halts_and_is_absorbing(world: World) -> None:
    """An equity path through -15% flips the ladder to FLAT_HALTED, absorbing."""
    strat = BlendStrategy(
        world.settings,
        signal_frame=_signal_frame(world.closes, mu=0.05),
        rebalance_bars=24,
        cov_min_periods=120,
    )
    eq = [100.0, 95.0, 88.0, 84.0, 999.0]  # crosses -15% at 84, then "recovers"
    states = [strat.ladder.update(e) for e in eq]
    assert states[3].name == "FLAT_HALTED"
    assert states[4].name == "FLAT_HALTED"  # absorbing despite the recovery
    assert strat.ladder.gross_multiplier() == 0.0
    strat.ladder.rearm()
    assert strat.ladder.gross_multiplier() == 1.0


def test_stale_signal_holds(world: World) -> None:
    """A signal frame that stops 100 bars before the test span → HOLD (no trades)."""
    frame = _signal_frame(world.closes, mu=0.05)
    # keep only ts_open in the first 200 bars; the run starts well after staleness.
    frame = frame[frame.index.get_level_values("ts_open") < T0 + 200 * HOUR]
    strat = BlendStrategy(
        world.settings, signal_frame=frame, rebalance_bars=24, cov_min_periods=120
    )
    result = _run(world, strat, start_bar=300, end_bar=N_BARS)
    assert result.counters["fills_applied"] == 0  # type: ignore[attr-defined]


def test_live_mu_provider_path(world: World) -> None:
    """The live-mode callable produces an analogous constraint-respecting book."""

    def provider(_ts: Ms) -> Mapping[str, float]:
        return {iid: 0.05 * (k - 1.5) for k, iid in enumerate(IDS)}

    strat = BlendStrategy(
        world.settings, mu_provider=provider, rebalance_bars=24, cov_min_periods=120
    )
    result = _run(world, strat, start_bar=0, end_bar=N_BARS)
    pos = result.positions  # type: ignore[attr-defined]
    assert not pos.empty
    assert strat.last_result is not None
    assert float(np.abs(strat.last_result.weights).max()) <= 0.15 + 1e-6


def test_requires_exactly_one_signal_source(world: World) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        BlendStrategy(world.settings)
    with pytest.raises(ValueError, match="exactly one"):
        BlendStrategy(
            world.settings,
            signal_frame=_signal_frame(world.closes, mu=0.05),
            mu_provider=lambda _ts: {},
        )


def _ctx(world: World, *, bar: int, equity: float, positions: dict[str, float]) -> StrategyContext:
    """A PIT StrategyContext at ``T0 + bar*HOUR`` over the full run universe."""
    instruments = {iid: world.store.get(iid, as_of=T0 + bar * HOUR) for iid in IDS}
    return StrategyContext(
        reader=world.reader,
        tf=Timeframe.H1,
        ts=T0 + bar * HOUR,
        equity=equity,
        positions=positions,
        instruments={iid: inst for iid, inst in instruments.items() if inst is not None},
    )


def test_half_gross_degrosses_on_next_bar_not_next_rebalance(world: World) -> None:
    """F-B: a NORMAL -> HALF_GROSS transition de-grosses on the NEXT bar.

    Drive the strategy to a rebalance at full gross, then push the ladder into
    HALF_GROSS (a -10% drawdown) on the very next, NON-rebalance bar. The
    strategy must re-emit the last book at HALF gross immediately rather than
    holding ({}) at full gross until the next rebalance ~24 bars later."""
    strat = BlendStrategy(
        world.settings,
        signal_frame=_signal_frame(world.closes, mu=0.05),
        rebalance_bars=24,
        cov_min_periods=120,
    )
    # A first rebalance well past warm-up: populates _last_targets at full gross.
    rebalance = strat.on_bar_close(_ctx(world, bar=300, equity=100_000.0, positions={}))
    assert rebalance  # non-empty target book emitted
    assert strat.ladder.gross_multiplier() == 1.0  # still NORMAL
    pre_mult = dict(rebalance)  # at NORMAL the emitted book IS the pre-mult book

    # The NEXT bar (301) is NOT a rebalance bar. An -11% drawdown (past the
    # -10% dd_halve_gross threshold, clear of float-edge ties) flips the ladder
    # to HALF_GROSS. The strategy must re-emit at half gross NOW.
    degrossed = strat.on_bar_close(_ctx(world, bar=301, equity=89_000.0, positions={}))
    assert strat.ladder.gross_multiplier() == 0.5  # HALF_GROSS
    assert degrossed  # NOT a {} hold
    assert strat.counters["bars_half_gross"] >= 1
    for iid, w in degrossed.items():
        assert w == pytest.approx(0.5 * pre_mult[iid], abs=1e-12)


def test_normal_between_rebalance_holds_empty(world: World) -> None:
    """A NORMAL non-rebalance bar holds ({}) and counts hold_between_rebalance."""
    strat = BlendStrategy(
        world.settings,
        signal_frame=_signal_frame(world.closes, mu=0.05),
        rebalance_bars=24,
        cov_min_periods=120,
    )
    assert strat.on_bar_close(_ctx(world, bar=300, equity=100_000.0, positions={}))
    held = strat.on_bar_close(_ctx(world, bar=301, equity=100_000.0, positions={}))
    assert held == {}
    assert strat.counters["hold_between_rebalance"] >= 1


def test_counters_distinguish_stale_from_between_rebalance(world: World) -> None:
    """F-E: a frozen/stale signal feed yields hold_stale_signal > 0 and is
    distinguishable from healthy between-rebalance holds (a dead feed must not
    read like normal holding)."""
    frame = _signal_frame(world.closes, mu=0.05)
    # Signal stops 100 bars before the test span -> every decision bar is stale.
    frame = frame[frame.index.get_level_values("ts_open") < T0 + 200 * HOUR]
    strat = BlendStrategy(
        world.settings, signal_frame=frame, rebalance_bars=24, cov_min_periods=120
    )
    _run(world, strat, start_bar=300, end_bar=N_BARS)
    c = strat.counters
    assert c["hold_stale_signal"] > 0
    assert c["n_rebalances"] == 0  # never traded a stale feed
    assert c["hold_between_rebalance"] == 0  # no rebalance ever set the schedule


def test_mvo_run_reports_fallback_count(world: World) -> None:
    """F-D: an mvo run on drifted positions records n_fallback_used (the MVO's
    turnover cap can make the ordinary drifted w_prev infeasible, silently
    degrading to the rank fallback)."""
    strat = BlendStrategy(
        world.settings,
        signal_frame=_signal_frame(world.closes, mu=0.05),
        allocator="mvo",
        rebalance_bars=24,
        cov_min_periods=120,
    )
    _run(world, strat, start_bar=0, end_bar=N_BARS)
    c = strat.counters
    assert c["n_rebalances"] > 0
    # Every rebalance is either an optimal solve or a counted fallback.
    assert 0 <= c["n_fallback_used"] <= c["n_rebalances"]
    assert "n_fallback_used" in c
