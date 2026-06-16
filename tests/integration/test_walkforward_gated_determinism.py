"""Determinism proof for the gated walk-forward (Phase 12; ``12_FINAL.md`` D1-D7).

The runtime guarantee the type-checker cannot give: two independent
``WalkForwardRunner.run(ml=True, regime=True)`` invocations over the SAME tiny
synthetic ``tmp_path`` lake produce a BYTE-IDENTICAL stitched OOS equity curve, the
identical :class:`~alphaforge.analytics.walkforward.ValidationReport` (variant +
nested blend-only baseline), and the identical per-leg risk counters. Both gates fire
for real — a genuine :class:`~alphaforge.regime.hmm.RegimeHMM` Baum-Welch fit (seeded
``RANDOM_STATE = 42``, deterministic ``SeedSequence`` per-seed children) and a genuine
:class:`~alphaforge.ml.model.HistGBMMetaModel` fit (``random_state = 42``) — so the
determinism is asserted against the heavyweight stochastic seams, not a stubbed gate.

Why this can ever be deterministic: every random draw in the pipeline is seeded with a
FIXED constant —

* the synthetic daily-BTC series (``default_rng(7)``) and the hourly closes
  (``default_rng(101 + k)``) are the fixture's only data randomness, identical run-to-run;
* the HMM multi-seed restart loop derives its per-seed RNGs from a fixed
  ``np.random.SeedSequence(RANDOM_STATE)`` (``regime.hmm`` finding 13);
* the HistGBM classifier is constructed with ``random_state = 42``.

A re-run that diverged would betray hidden global RNG state, a dict-iteration-order
dependence, or a non-deterministic merge/sort in the gate broadcast — exactly the
classes of bug a determinism review exists to catch. The two runs write to SEPARATE
``out_dir``s and SEPARATE experiment ledgers so neither perturbs the other.

Kept FAST: 5 instruments, ~1.5k 1h bars, ``--train 31d / --test 4d`` ⇒ a handful of
legs. The two genuine HMM fits on ~720-740 daily rows are the only heavyweight steps;
the fixture is built once (module-scoped) and the two runs reuse it. Offline,
``tmp_path`` lake only, no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.analytics.walkforward import WalkForwardResult, WalkForwardRunner
from alphaforge.backtest import StaticCostInputs
from alphaforge.config.settings import Settings, SignalsCfg
from alphaforge.core.instruments import Instrument, InstrumentStore
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
from alphaforge.signals.service import SignalService
from alphaforge.validation.experiments import ExperimentLog

if TYPE_CHECKING:
    from collections.abc import Iterator

    from alphaforge.core.time import Ms
    from alphaforge.features.context import FeatureContext
    from alphaforge.validation.dsr import DSRReport

HOUR = 3_600_000
DAY = 24 * HOUR
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z (1h-aligned)
H = 72  # == SignalsCfg().horizon_bars

# ~44 days of 1h bars: 31d train warms the cost-inputs ADV median, the covariance window
# and the momentum lookback so the OOS curve trades; train=744 / test=96 tiles a few legs.
N_BARS = 1056
_TRAIN_DAYS = 31
_TEST_DAYS = 4
_TRAIN, _TEST = _TRAIN_DAYS * 24, _TEST_DAYS * 24

BTC = "BINANCE:PERP:BTCUSDT"
MEMBERS = (BTC, *(f"BINANCE:PERP:{b}USDT" for b in ("ETH", "SOL", "ADA", "DOGE")))
ALL_IDS = list(MEMBERS)
_DRIFTS = (0.002, -0.002, 0.0015, -0.0015, 0.001)
_ALPHA = "alpha_mom"

# Same daily-BTC anchoring as test_walkforward_full_pipeline: the early legs cold-start
# (< MIN_FIT_DAYS), the later legs fit the real HMM, so determinism is tested across BOTH
# the IdentityRegime fallback and a genuine seeded Baum-Welch fit.
_DAILY_LOOKBACK_DAYS = 708
_DAILY_START = T0 - _DAILY_LOOKBACK_DAYS * DAY
_DAILY_END = T0 + N_BARS * HOUR

_INITIAL_CASH = 100_000.0


def _xret_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    close = ctx.panel("close")
    window = int(spec.params["window"])
    out: pd.DataFrame = np.log(close / close.shift(window))  # type: ignore[assignment]
    return long_series(out, name=spec.name)


def _registry() -> FeatureRegistry:
    reg = FeatureRegistry()

    def alpha_mom() -> FeatureSpec:
        window = 48
        return FeatureSpec(
            name=_ALPHA,
            family=Family.MOMENTUM,
            direction=1,
            cross_sectional=True,
            lookback_bars=window + 1,
            params={"window": window},
            fn=_xret_fn,
        )

    reg.register(alpha_mom)
    return reg


def _closes(seed: int, n: int, level: float, drift: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.asarray(level * np.exp(np.cumsum(rng.normal(drift, 0.012, n))))


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
            "volume": pa.array([100.0] * n_rows, type=pa.float64()),
            "quote_volume": pa.array([1.0e7] * n_rows, type=pa.float64()),
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
        listed_ts=T0 - 800 * DAY,
        delisted_ts=None,
    )


@dataclass(frozen=True)
class _SyntheticDailyBtc:
    """A deterministic ``DailyBtcReader`` over a synthetic sine+noise daily BTC series."""

    frame: pd.DataFrame

    def read_daily_btc(self, start: Ms, end: Ms) -> pd.DataFrame:
        del start  # deep history reaches before the hourly run start (production parity)
        ts = self.frame.index.to_numpy(dtype=np.int64)
        return self.frame.iloc[ts < int(end)]


def _daily_btc_frame() -> pd.DataFrame:
    """A >= MIN_FIT_DAYS synthetic daily BTC OHLC frame (sine+noise; default_rng(7))."""
    n_days = (_DAILY_END - _DAILY_START) // DAY
    ts = np.asarray([_DAILY_START + k * DAY for k in range(int(n_days))], dtype=np.int64)
    rng = np.random.default_rng(7)
    k = np.arange(ts.size, dtype=float)
    daily_ret = 0.01 * np.sin(2.0 * np.pi * k / 90.0) + rng.normal(0.0, 0.02, ts.size)
    close = 30_000.0 * np.exp(np.cumsum(daily_ret))
    open_ = np.empty_like(close)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    span = np.abs(daily_ret) + 0.005
    high = np.maximum(open_, close) * (1.0 + span)
    low = np.minimum(open_, close) * (1.0 - span)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=pd.Index(ts, dtype="int64", name="ts_open"),
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
    daily_btc: _SyntheticDailyBtc


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    tmp = tmp_path_factory.mktemp("wf_gated_determinism")
    paths = LakePaths(tmp / "lake")
    closes = {
        iid: _closes(101 + k, N_BARS, 50.0 * (k + 1), _DRIFTS[k]) for k, iid in enumerate(ALL_IDS)
    }
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

    instruments = InstrumentStore(tmp / "ops.sqlite")
    for iid in ALL_IDS:
        instruments.upsert(_instrument(iid), as_of=T0 - 800 * DAY)

    cfg = SignalsCfg()
    assert cfg.horizon_bars == H
    reader = PITDataReader(paths)
    service = SignalService(
        FeatureEngine(reader, instruments, universe),
        universe,
        _registry(),
        cfg,
        alpha_names=(_ALPHA,),
    )
    yield Env(
        reader=reader,
        instruments=instruments,
        universe=universe,
        service=service,
        cost_model=TransactionCostModel.from_settings(Settings()),
        cost_inputs=StaticCostInputs(adv_quote=1.0e8, sigma_daily=0.05),
        settings=Settings(),
        daily_btc=_SyntheticDailyBtc(_daily_btc_frame()),
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
        daily_btc_reader=env.daily_btc,
    )


def _stub_dsr(rets: pd.Series, n_trials: int, var_sr: float, ann: float) -> DSRReport:
    """A deterministic DSR stub: the determinism check is on equity + Sharpe, not scipy."""
    from alphaforge.analytics.metrics import sharpe
    from alphaforge.validation.dsr import DSRReport

    sr_ann = float(sharpe(rets, ann))
    del n_trials, var_sr
    return DSRReport(
        psr=0.99,
        dsr=0.99,
        sr_ann=sr_ann,
        sr_per_period=float(sharpe(rets, 1.0)),
        skew=0.0,
        kurtosis=3.0,
        n_obs=len(rets),
        expected_max_sr=0.0,
    )


def _run_gated(env: Env, out_dir: object) -> WalkForwardResult:
    """One full ``ml=True, regime=True`` walk-forward to a fresh out_dir + ledger."""
    from pathlib import Path

    out = Path(str(out_dir))
    log = ExperimentLog(out / "experiments.jsonl")
    return _runner(env).run(
        T0,
        T0 + N_BARS * HOUR,
        train_bars=_TRAIN,
        test_bars=_TEST,
        allocator="rank",
        out_dir=out,
        now_ms=T0 + (N_BARS + 1) * HOUR,
        alpha_names=[_ALPHA],
        experiment_log=log,
        dsr_fn=_stub_dsr,
        ml=True,
        regime=True,
    )


@dataclass(frozen=True)
class _TwoRuns:
    first: WalkForwardResult
    second: WalkForwardResult


@pytest.fixture(scope="module")
def two_runs(env: Env, tmp_path_factory: pytest.TempPathFactory) -> _TwoRuns:
    """Run the IDENTICAL gated config TWICE (separate out_dirs + ledgers), module-scoped."""
    first = _run_gated(env, tmp_path_factory.mktemp("run_a"))
    second = _run_gated(env, tmp_path_factory.mktemp("run_b"))
    return _TwoRuns(first=first, second=second)


class TestEquityDeterminism:
    """The headline determinism guarantee: two gated runs, byte-identical equity."""

    def test_two_gated_runs_produce_a_nonflat_curve(self, two_runs: _TwoRuns) -> None:
        """Guard against a vacuous proof: the OOS curve must actually trade and move.

        Two flat (never-traded) equity curves would be trivially equal. The fixture's
        persistently-ranked cross-section drives a non-constant curve, so the equality
        below is asserted against a curve that genuinely exercised the gated pipeline.
        """
        equity = two_runs.first.equity
        assert len(equity) > 0
        assert two_runs.first.fills.shape[0] > 0, "the gated book never traded"
        assert float(equity.std()) > 0.0, "a flat curve makes the determinism check vacuous"

    def test_stitched_equity_is_byte_identical(self, two_runs: _TwoRuns) -> None:
        """``run A`` and ``run B`` equity curves are EXACTLY equal (index + values).

        ``Series.equals`` compares dtype, index and every value with no tolerance — a
        single divergent ULP fails. This is the strict determinism predicate: nothing in
        the gated path (the seeded HMM Baum-Welch fit, the seeded HistGBM fit, the gate
        broadcast merge_asof, the per-leg compounding) leaks non-deterministic state.
        """
        a = two_runs.first.equity
        b = two_runs.second.equity
        assert a.equals(b), "gated equity diverged between two identical runs (non-determinism)"
        # Belt-and-braces over Series.equals: the raw arrays are bit-identical too.
        assert np.array_equal(
            a.to_numpy(dtype="float64"), b.to_numpy(dtype="float64")
        )
        assert np.array_equal(
            a.index.to_numpy(dtype="int64"), b.index.to_numpy(dtype="int64")
        )

    def test_final_equity_matches_exactly(self, two_runs: _TwoRuns) -> None:
        """The headline number — final marked OOS equity — is identical to the last bit."""
        a = float(two_runs.first.equity.iloc[-1])
        b = float(two_runs.second.equity.iloc[-1])
        assert a.hex() == b.hex(), f"final equity diverged: {a!r} vs {b!r}"


class TestValidationDeterminism:
    """The attached anti-overfit verdict + its nested baseline are run-invariant."""

    def test_validation_report_is_identical(self, two_runs: _TwoRuns) -> None:
        """variant / gate_inactive_frac / clears_baseline_gate / Sharpe are identical.

        Both runs use the same ``_stub_dsr`` and a FRESH ledger seeded only by this run's
        trials, so DSR/PSR are fixtures; the load-bearing determinism is on the curve-derived
        ``sr_ann`` and the gate fields. The whole ``to_json_obj`` (including the nested
        blend-only baseline block) must round-trip identically.
        """
        va = two_runs.first.validation
        vb = two_runs.second.validation
        assert va is not None
        assert vb is not None
        assert va.variant == vb.variant == "ml+regime"
        assert va.gate_inactive_frac == vb.gate_inactive_frac
        assert va.clears_baseline_gate == vb.clears_baseline_gate
        assert va.sr_ann.hex() == vb.sr_ann.hex()
        assert va.to_json_obj() == vb.to_json_obj()

    def test_baseline_block_is_present_and_identical(self, two_runs: _TwoRuns) -> None:
        """The gated variant carries a blend-only baseline whose Sharpe is run-invariant."""
        va = two_runs.first.validation
        vb = two_runs.second.validation
        assert va is not None
        assert vb is not None
        assert va.baseline is not None, "a gated variant must carry a blend-only baseline (D5)"
        assert vb.baseline is not None
        assert va.baseline.sr_ann.hex() == vb.baseline.sr_ann.hex()


class TestPerLegDeterminism:
    """Per-leg risk counters + leg spans match exactly across the two runs."""

    def test_leg_count_and_spans_match(self, two_runs: _TwoRuns) -> None:
        a = two_runs.first.legs
        b = two_runs.second.legs
        assert len(a) == len(b) > 0
        for la, lb in zip(a, b, strict=True):
            assert (la.train_start, la.test_start, la.test_end) == (
                lb.train_start,
                lb.test_start,
                lb.test_end,
            )

    def test_per_leg_risk_counters_match(self, two_runs: _TwoRuns) -> None:
        """The per-leg risk-counter deltas (rebalances / fallbacks / holds / halts) match.

        The risk state persists across legs (one strategy, F-A); a non-deterministic gate
        would perturb sizing and hence the rebalance/no-trade-band counters leg-by-leg.
        """
        for la, lb in zip(two_runs.first.legs, two_runs.second.legs, strict=True):
            assert la.risk_counters == lb.risk_counters
