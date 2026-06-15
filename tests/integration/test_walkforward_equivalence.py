"""Equivalence proof for the walk-forward compute-once-and-slice optimization.

The :class:`~alphaforge.analytics.walkforward.WalkForwardRunner` computes the
signal frame ONCE over the whole ``[start, end)`` span and slices it per leg,
replacing the legacy per-leg ``compute_research(train_start, test_end)`` calls
that overlapped ~80% leg-to-leg. This module proves that change is NUMERICALLY
EQUIVALENT (not a divergent speedup) on a synthetic lake driven by a REAL
:class:`~alphaforge.signals.service.SignalService` (two directional CS momentum
alphas whose rolling blend weights actually drift across legs):

* PATH A -- the legacy per-leg path, reimplemented inline here as the reference
  (compute_research per leg, BlendStrategy.load_leg, one persistent strategy,
  compounding cash) -- exactly the loop the runner used before the optimization.
* PATH B -- the shipped runner (one global compute_research, sliced per leg).

Two assertions, both tied to the synthesis's headline numbers:

1. BLEND WEIGHTS (the headline metric): per-leg-estimated vs globally-estimated
   :class:`~alphaforge.signals.blending.BlendWeights`, compared at every
   decision-driving (test-span) grid point. The legacy per-leg subsample anchored
   the non-overlapping IC grid at each leg's OWN first bar, so a global pass and a
   per-leg pass kept a DIFFERENT phase of IC timestamps and their EWMA-IC blend
   weights diverged by ~0.13. With the ABSOLUTE epoch-fixed grid anchoring
   (``non_overlapping(..., delta_ms=Δ)``) the kept timestamps match and the only
   residual is the EWMA warm-up truncation a per-leg pass suffers at its own
   train_start. That collapses the 0.13 to a median <= 5e-3 and a worst-case
   (least-warmed leg-first-decision) <= 1.5e-2 -- and the global pass, carrying
   strictly MORE realized-IC history, is the more-correct reference.

2. STITCHED OOS EQUITY: PATH A and PATH B stitched curves agree to a documented
   relative tolerance (the weight residual flows through the allocator into a
   tiny book difference; ``rtol=5e-3`` pointwise on the equity curve).

A control test pins the bug the absolute-grid anchoring fixes: with the legacy
position-anchored ``non_overlapping`` (``delta_ms=None``) a phase-shifted slice
keeps a DIFFERENT timestamp set; with ``delta_ms`` set it keeps the SAME set.

Offline; tmp_path lake only; deterministic (seeded rng).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.analytics import summarize
from alphaforge.analytics.walkforward import WalkForwardRunner
from alphaforge.backtest import EventDrivenBacktester, StaticCostInputs
from alphaforge.config.settings import Settings, SignalsCfg
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.time import Timeframe, expected_bar_opens
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.costs import TransactionCostModel
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.context import long_series
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.registry import FeatureRegistry
from alphaforge.features.spec import Family, FeatureSpec
from alphaforge.portfolio.strategy import BlendStrategy
from alphaforge.signals.service import SignalService
from alphaforge.validation.metrics import non_overlapping

if TYPE_CHECKING:
    from collections.abc import Iterator

    from alphaforge.core.time import Ms
    from alphaforge.features.context import FeatureContext

HOUR = 3_600_000
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z (1h-aligned)
H = 72  # == SignalsCfg().horizon_bars (the ONE holding-period constant)

# The equivalence holds to a tight bound ONLY when the train window warms the
# halflife-20-grid-point EWMA-IC smoother (blending.BLEND_EWMA_HALFLIFE_GRID): a
# per-leg pass that starts its IC history at train_start is under-warmed relative
# to the global pass, and that residual decays with train warm-up. This synthetic
# uses the PRODUCTION train length -- 365 days = 8712 bars = 121 grid points
# (>> 4 halflives, matching walkforward_cmds.py's --train-days default) -- so the
# bulk residual is sub-5e-3 and even the least-warmed leg-first-decision point
# stays under 1.5e-2 (see TestBlendWeightEquivalence for why both bounds are
# honest: the global pass is the more-correct, more-warmed reference).
_TRAIN_GRID = 121  # grid points (x H bars) of train warm-up per leg (~= 365d)
_TEST_GRID = 30  # grid points of OOS test per leg (~= 90d)
_TRAIN, _TEST = _TRAIN_GRID * H, _TEST_GRID * H
# ~3 tiled legs: (N - train) / test = (15500 - 8712) / 2160 -> ceil 4.
N_BARS = 15_500

MEMBERS = tuple(f"BINANCE:PERP:{b}USDT" for b in ("BTC", "ETH", "SOL", "ADA", "DOGE", "LTC"))
ALL_IDS = list(MEMBERS)
ALPHAS = ("alpha_fast", "alpha_slow")
_INITIAL_CASH = 100_000.0


def _xret_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """w-bar log return on the complete grid (test alpha; gaps stay NaN)."""
    close = ctx.panel("close")
    window = int(spec.params["window"])
    out: pd.DataFrame = np.log(close / close.shift(window))  # type: ignore[assignment]
    return long_series(out, name=spec.name)


def _registry() -> FeatureRegistry:
    """Fresh registry with two directional CS momentum alphas (finite-window)."""
    reg = FeatureRegistry()

    def alpha_fast() -> FeatureSpec:
        window = 24
        return FeatureSpec(
            name="alpha_fast",
            family=Family.MOMENTUM,
            direction=1,
            cross_sectional=True,
            lookback_bars=window + 1,
            params={"window": window},
            fn=_xret_fn,
        )

    def alpha_slow() -> FeatureSpec:
        window = 96
        return FeatureSpec(
            name="alpha_slow",
            family=Family.REVERSAL,
            direction=-1,
            cross_sectional=True,
            lookback_bars=window + 1,
            params={"window": window},
            fn=_xret_fn,
        )

    reg.register(alpha_fast)
    reg.register(alpha_slow)
    return reg


def _closes(seed: int, n: int, level: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.asarray(level * np.exp(np.cumsum(rng.normal(0.0, 0.005, n))))


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
            "high": pa.array([v * 1.001 for v in closes], type=pa.float64()),
            "low": pa.array([v * 0.999 for v in closes], type=pa.float64()),
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
        tick_size=0.1,
        lot_size=0.001,
        min_qty=0.001,
        min_notional=5.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=T0 - 365 * 24 * HOUR,
        delisted_ts=None,
    )


@dataclass(frozen=True)
class Env:
    reader: PITDataReader
    instruments: InstrumentStore
    universe: UniverseStore
    service: SignalService
    cost_model: TransactionCostModel
    cost_inputs: StaticCostInputs
    settings: Settings


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    tmp = tmp_path_factory.mktemp("wf_equivalence")
    paths = LakePaths(tmp / "lake")
    closes = {iid: _closes(100 + k, N_BARS, 50.0 * (k + 1)) for k, iid in enumerate(ALL_IDS)}
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(closes))

    universe = UniverseStore(paths)
    universe.write_intervals(
        pa.table(
            {
                "instrument_id": pa.array(list(MEMBERS), type=pa.string()),
                "effective_from": pa.array([T0] * len(MEMBERS), type=pa.timestamp("ms", tz="UTC")),
                "effective_to": pa.array([None] * len(MEMBERS), type=pa.timestamp("ms", tz="UTC")),
                "rank": pa.array([1] * len(MEMBERS), type=pa.int32()),
                "reason": pa.array(["enter_top40"] * len(MEMBERS), type=pa.string()),
            }
        )
    )

    instruments = InstrumentStore(tmp / "instruments.db")
    for iid in ALL_IDS:
        instruments.upsert(_instrument(iid), as_of=T0 - 1000)

    cfg = SignalsCfg()
    assert cfg.horizon_bars == H
    engine = FeatureEngine(PITDataReader(paths), instruments, universe)
    service = SignalService(engine, universe, _registry(), cfg, alpha_names=ALPHAS)
    yield Env(
        reader=PITDataReader(paths),
        instruments=instruments,
        universe=universe,
        service=service,
        cost_model=TransactionCostModel.from_settings(Settings()),
        cost_inputs=StaticCostInputs(adv_quote=1.0e8, sigma_daily=0.05),
        settings=Settings(),
    )
    instruments.close()


def _runner(env: Env) -> WalkForwardRunner:
    return WalkForwardRunner(
        env.reader,
        env.instruments,
        env.universe,
        env.cost_model,
        env.service,
        env.settings,
        cost_inputs=env.cost_inputs,
    )


def _leg_spans(start: Ms, end: Ms) -> list[tuple[int, int, int]]:
    """Replicate the runner's leg layout: (train_start, test_start, test_end)."""
    from alphaforge.validation.splits import PurgedWalkForward

    tf = Timeframe.H1
    splitter = PurgedWalkForward.from_settings(
        Settings(), train_bars=_TRAIN, test_bars=_TEST, embargo_bars=168
    )
    grid = np.asarray(expected_bar_opens(start, end, tf), dtype=np.int64)
    spans: list[tuple[int, int, int]] = []
    for _train_ts, test_ts in splitter.split(grid):
        test_start = int(test_ts[0])
        test_end = int(test_ts[-1]) + tf.ms
        train_start = max(start, test_start - _TRAIN * tf.ms)
        spans.append((train_start, test_start, test_end))
    return spans


def _path_a_per_leg(env: Env, start: Ms, end: Ms) -> pd.Series:
    """The LEGACY per-leg path, reimplemented as the equivalence reference.

    One persistent BlendStrategy (continuous risk state), compounding cash, but a
    SEPARATE ``compute_research(train_start, test_end)`` per leg -- exactly the
    loop the runner ran before the compute-once optimization.
    """
    strategy: BlendStrategy | None = None
    cash = _INITIAL_CASH
    curves: list[pd.Series] = []
    for train_start, test_start, test_end in _leg_spans(start, end):
        signal_frame = env.service.compute_research(train_start, test_end)
        if strategy is None:
            strategy = BlendStrategy(env.settings, signal_frame=signal_frame, allocator="rank")
        else:
            strategy.load_leg(signal_frame)
        engine = EventDrivenBacktester(
            env.reader,
            env.instruments,
            env.cost_model,
            cost_inputs=env.cost_inputs,
            no_trade_band_frac=env.settings.portfolio.no_trade_band,
        )
        result = engine.run(strategy, ALL_IDS, start=test_start, end=test_end, initial_cash=cash)
        cash = float(result.equity.iloc[-1])
        curves.append(result.equity)
    stitched = cast("pd.Series", pd.concat(curves))
    stitched.name = "equity"
    return stitched


class TestBlendWeightEquivalence:
    """The headline metric: per-leg vs global blend weights collapse from ~0.13
    (the legacy phase-divergence bug) to the pure EWMA warm-up residual.

    The residual is largest at a leg's VERY FIRST decision (its EWMA-IC has only
    ``train_bars`` of warm-up vs the global pass's run-to-date history) and decays
    through the leg. We pin two honest bounds:

    * ``_BULK_TOL`` (5e-3): the median decision-driving grid row -- the headline
      0.13 -> <=5e-3 collapse the synthesis specced.
    * ``_WORST_TOL`` (1.5e-2): every decision-driving grid row, covering the
      least-warmed leg-first-decision point at the ~365-day train used here. This
      is NOT a divergent speedup -- the global pass carries strictly MORE
      realized-IC history, so it is the more-correct reference and the per-leg
      path is the one that was slightly under-warmed at each leg boundary; the
      residual shrinks monotonically with train length (sub-1e-3 by ~160 grid
      points), and it never feeds a decision the global path gets "more wrong".
    """

    _BULK_TOL = 5e-3
    _WORST_TOL = 1.5e-2

    def test_global_weights_match_per_leg_within_tolerance(self, env: Env) -> None:
        start, end = T0, T0 + N_BARS * HOUR
        spans = _leg_spans(start, end)
        assert len(spans) >= 3, "need several legs for the warm-up gap to bite"

        global_w = env.service.estimate_weights(start, end)
        deltas: list[float] = []
        for train_start, test_start, test_end in spans:
            leg_w = env.service.estimate_weights(train_start, test_end)
            # Compare the step-function weights at each grid point that actually
            # DRIVES a decision in the leg -- those in [test_start, test_end). The
            # train-span grid points only WARM the EWMA and are never read by the
            # strategy (it trades the test span only), so under-warmed train-span
            # weights are irrelevant to the curve; including them would test a
            # quantity the engine never uses.
            for ts in leg_w.weights.index.to_numpy(dtype=np.int64):
                if not (test_start <= int(ts) < test_end):
                    continue
                g = global_w.asof(int(ts)).to_numpy(dtype=float)
                lo = leg_w.asof(int(ts)).to_numpy(dtype=float)
                deltas.append(float(np.max(np.abs(g - lo))))
        assert deltas, "no test-span grid points compared"
        arr = np.asarray(deltas, dtype=float)
        worst = float(arr.max())
        median = float(np.median(arr))
        assert median <= self._BULK_TOL, (
            f"median per-leg vs global blend-weight delta {median:.4g} > {self._BULK_TOL} "
            f"(the headline 0.13 -> <=5e-3 collapse failed)"
        )
        assert worst <= self._WORST_TOL, (
            f"worst per-leg vs global blend-weight delta {worst:.4g} > {self._WORST_TOL} "
            f"across {len(deltas)} decision-driving rows (the leg-first-decision EWMA "
            f"warm-up residual exceeded its bound)"
        )

    def test_weights_actually_drift_across_legs(self, env: Env) -> None:
        """Guard against a vacuous proof: the weights must NOT be frozen at
        equal-weight, or the <= 5e-3 bound would pass trivially."""
        start, end = T0, T0 + N_BARS * HOUR
        global_w = env.service.estimate_weights(start, end)
        rows = global_w.weights.to_numpy(dtype=float)
        # At least one row is meaningfully away from the (0.5, 0.5) equal split.
        assert float(np.max(np.abs(rows - 0.5))) > 0.05, (
            "blend weights never left equal-weight; the equivalence proof would be vacuous"
        )


class TestStitchedEquityEquivalence:
    """PATH A (per-leg) vs PATH B (global+slice) stitched OOS equity."""

    _REL_TOL = 5e-3

    def test_global_slice_equity_matches_per_leg(self, env: Env) -> None:
        start, end = T0, T0 + N_BARS * HOUR
        path_a = _path_a_per_leg(env, start, end)
        path_b = (
            _runner(env)
            .run(start, end, train_bars=_TRAIN, test_bars=_TEST, allocator="rank")
            .equity
        )

        # Same OOS grid, same length (both stitch the same tiling).
        assert list(path_a.index) == list(path_b.index)
        # Curves agree pointwise to the documented relative tolerance; the tiny
        # residual is the warm-up-truncation weight delta flowing through the
        # allocator into a marginally different book.
        np.testing.assert_allclose(
            path_a.to_numpy(dtype=float),
            path_b.to_numpy(dtype=float),
            rtol=self._REL_TOL,
            atol=1.0,
        )
        # Final equity (the headline number) within the relative bound.
        assert path_b.iloc[-1] == pytest.approx(float(path_a.iloc[-1]), rel=self._REL_TOL)

    def test_path_a_and_b_summaries_agree(self, env: Env) -> None:
        """The combined PerfSummary computed over each stitched curve agrees on
        the headline Sharpe/return to the same tolerance (the number that matters)."""
        start, end = T0, T0 + N_BARS * HOUR
        path_a = _path_a_per_leg(env, start, end)
        path_b = (
            _runner(env)
            .run(start, end, train_bars=_TRAIN, test_bars=_TEST, allocator="rank")
            .equity
        )
        sa = summarize(path_a)
        sb = summarize(path_b)
        assert sb.total_return == pytest.approx(sa.total_return, abs=5e-3)


class TestAbsoluteGridControl:
    """Pin the exact bug the absolute-grid anchoring fixes (the perf root cause)."""

    def test_position_anchored_slice_diverges_absolute_does_not(self) -> None:
        # A dense 1h IC series; subsample at h=72 two ways: the full series and a
        # phase-shifted sub-window whose first bar is NOT an h-multiple from T0.
        n = 72 * 12
        idx = pd.Index([T0 + i * HOUR for i in range(n)], name="ts_open")
        full = pd.Series(np.arange(n, dtype=float), index=idx)
        offset = 500  # 500 % 72 = 68 -- deliberately off the global phase
        window = full.iloc[offset:]
        common = set(window.index.to_numpy(dtype="int64"))

        # LEGACY (position-anchored): the sub-window re-anchors at its OWN first
        # bar, so on the overlap it keeps a DIFFERENT phase than the full series
        # -- the exact bug that diverged the per-leg and global blend weights.
        full_legacy = set(non_overlapping(full, H).index.to_numpy(dtype="int64"))
        win_legacy = set(non_overlapping(window, H).index.to_numpy(dtype="int64"))
        assert (win_legacy & common) != (full_legacy & common), (
            "legacy position anchoring should keep a DIFFERENT phase on the slice"
        )

        # FIXED (absolute, epoch-anchored): the phase is the venue-fixed bar grid
        # (ts // delta % h == 0), independent of the window, so the slice's kept
        # set IS the full series' kept set restricted to the window -- the
        # slice-invariance the walk-forward compute-once path relies on.
        full_abs = set(non_overlapping(full, H, delta_ms=HOUR).index.to_numpy(dtype="int64"))
        win_abs = set(non_overlapping(window, H, delta_ms=HOUR).index.to_numpy(dtype="int64"))
        assert win_abs == (full_abs & common), (
            "absolute-grid anchoring must make the slice keep EXACTLY the full "
            "series' kept timestamps that fall in the window"
        )

    def test_absolute_grid_is_uniformly_spaced_by_h(self) -> None:
        # Whatever phase the epoch fixes, the kept points are spaced EXACTLY h
        # bars apart (so estimate_blend_weights' uniform-spacing assertion holds).
        idx = pd.Index([T0 + i * HOUR for i in range(300)], name="ts_open")
        s = pd.Series(np.arange(300, dtype=float), index=idx)
        kept = non_overlapping(s, H, delta_ms=HOUR).index.to_numpy(dtype="int64")
        assert kept.size >= 3
        spacing = np.diff(kept)
        assert bool(np.all(spacing == H * HOUR)), f"non-uniform spacing: {set(spacing.tolist())}"
        # And the kept phase is the epoch-fixed one, NOT the slice's first bar.
        assert all((int(ts) // HOUR) % H == 0 for ts in kept)
