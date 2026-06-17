"""Full gated walk-forward, end-to-end on a tiny lake (``12_FINAL.md`` test 4 / D3/D4).

The runtime proof the type-checker cannot give: ``WalkForwardRunner.run(ml=True,
regime=True)`` is driven END-TO-END through the truth engine on a synthetic ``tmp_path``
lake with a REAL :class:`~alphaforge.regime.hmm.RegimeHMM` fit (a ``>= MIN_FIT_DAYS``
synthetic daily-BTC reader) and a REAL per-leg :class:`~alphaforge.ml.model.HistGBMMetaModel`
fit. Spies on :meth:`HistGBMMetaModel.fit` and :meth:`RegimeHMM.fit` capture the exact
matrices that reach each fit so the OOS-honest invariants are asserted on the wire, not
inferred from the types:

* **D3/D4 — no test-span row enters EITHER fit, for every leg.** The spied ``X.index``
  ``ts_open`` max (the meta fit) and the spied ``obs.index`` max (the HMM fit) are BOTH
  strictly ``< test_start`` of the leg they belong to (the expanding HMM window
  ``ts_open < test_start`` and the purged train window ``[train_start, test_start)``).
* **D3 cold-start fallback.** The daily-BTC series is anchored so the EARLY legs' expanding
  windows carry ``< MIN_FIT_DAYS`` finite daily obs and the LATER legs carry ``>=`` it: the
  early legs fall back to :class:`~alphaforge.regime.hmm.IdentityRegime` (``G ≡ 1``) and bump
  ``gate_inactive_frac`` rather than raising, while the later legs fit the real HMM (the
  ``RegimeHMM.fit`` spy actually fires) — both paths exercised in one run.
* **ONE stitched artifact set.** ``equity.parquet`` + ``walkforward.json`` + one tearsheet
  (``.txt``) + one ``legs/`` tree are written exactly once for the whole OOS path.
* **Pipeline order — next-open fills.** Every fill prints at ``decision_ts + Δ`` (the next
  open), the same next-open discipline ``test_mu_contract.py`` / the golden master pin:
  factors → blend → ml gate → regime gate → optimizer → next-open fills.

Kept FAST: a few instruments, ~1k 1h bars, ``--train 31d / --test 4d`` ⇒ a handful of legs;
the only heavyweight is the genuine Baum-Welch HMM fit on ~720-740 daily rows (a few
seconds). Offline, ``tmp_path`` lake only, deterministic (seeded rng), no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.analytics.walkforward import WalkForwardResult, WalkForwardRunner
from alphaforge.backtest import StaticCostInputs
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
from alphaforge.ml.model import FitWindows, HistGBMMetaModel
from alphaforge.regime.hmm import MIN_FIT_DAYS, RegimeHMM
from alphaforge.signals.service import SignalService
from alphaforge.validation.experiments import ExperimentLog
from alphaforge.validation.splits import PurgedWalkForward

if TYPE_CHECKING:
    from collections.abc import Iterator

    from alphaforge.core.time import Ms
    from alphaforge.features.context import FeatureContext
    from alphaforge.validation.dsr import DSRReport

HOUR = 3_600_000
DAY = 24 * HOUR
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z (1h-aligned)
H = 72  # == SignalsCfg().horizon_bars

# ~44 days of 1h bars: the 31-day train warms the LakeCostInputs 30d-median ADV, the
# 240-bar covariance window and the 169-bar momentum lookback so the OOS curve trades;
# train=744 / test=96 tiles a handful of OOS legs (see _leg_spans).
N_BARS = 1056
_TRAIN_DAYS = 31
_TEST_DAYS = 4
_TRAIN, _TEST = _TRAIN_DAYS * 24, _TEST_DAYS * 24

# BTC is the regime gate's market anchor; the rest give the blend a cross-section to rank.
BTC = "BINANCE:PERP:BTCUSDT"
MEMBERS = (BTC, *(f"BINANCE:PERP:{b}USDT" for b in ("ETH", "SOL", "ADA", "DOGE")))
ALL_IDS = list(MEMBERS)
# Per-instrument constant drifts so the cross-section is persistently RANKED (a non-flat,
# Sharpe/DSR-defined OOS curve — a flat curve has zero-variance returns and the validation
# step would error rather than assert).
_DRIFTS = (0.002, -0.002, 0.0015, -0.0015, 0.001)
_ALPHA = "alpha_mom"

# The synthetic daily-BTC series starts this many days before T0. Chosen so the EARLY legs'
# expanding (< test_start) windows carry < MIN_FIT_DAYS finite obs (cold-start IdentityRegime)
# and the LATER legs carry >=, so BOTH the fallback and a genuine RegimeHMM.fit fire in one
# run. Finite obs at a leg with test_start day-offset d from T0 is ~ (_DAILY_LOOKBACK_DAYS + d)
# minus the ~14-day Yang-Zhang + 1-bar-return warm-up build_observations drops; the crossover
# at MIN_FIT_DAYS sits inside the run's leg fan (test_start offsets ~31..40 days).
_DAILY_LOOKBACK_DAYS = 708
_DAILY_START = T0 - _DAILY_LOOKBACK_DAYS * DAY
_DAILY_END = T0 + N_BARS * HOUR

_INITIAL_CASH = 100_000.0


def _xret_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """w-bar log return on the complete grid (a tiny finite-window CS alpha)."""
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
            # Deep, finite quote volume so the LakeCostInputs 30d-median ADV is large and every
            # modest test order clears the fill model's 5%-of-ADV gate.
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
    """A :class:`~alphaforge.analytics.walkforward.DailyBtcReader` over a synthetic series.

    Returns a deterministic sine+noise daily BTC OHLC frame (int64 ``ts_open`` index, float
    OHLC) with DEEP history reaching ``_DAILY_LOOKBACK_DAYS`` before the run start — enough
    ``>= MIN_FIT_DAYS`` rows that a late leg's expanding ``ts_open < test_start`` slice actually
    fits the real HMM, while the runner's own per-leg slice (the leak guard) is exercised
    verbatim. The runner reads this once over the run window and slices per leg; like the
    production ``PITDataReader``-backed daily-BTC adapter it carries history from BEFORE the
    hourly run window (the HMM's expanding fit needs ≈2y of daily bars the 44-day hourly lake
    does not span), so the read honours only the UPPER ``end`` bound (PIT clamp) and exposes the
    full pre-run daily history below it — the runner's ``ts_open < test_start`` slice is the only
    place the test span is excluded (D3).
    """

    frame: pd.DataFrame

    def read_daily_btc(self, start: Ms, end: Ms) -> pd.DataFrame:
        del start  # deep history reaches before the hourly run start (production parity)
        ts = self.frame.index.to_numpy(dtype=np.int64)
        return self.frame.iloc[ts < int(end)]


def _daily_btc_frame() -> pd.DataFrame:
    """A >= MIN_FIT_DAYS synthetic daily BTC OHLC frame (sine+noise; deterministic)."""
    n_days = (_DAILY_END - _DAILY_START) // DAY
    ts = np.asarray([_DAILY_START + k * DAY for k in range(int(n_days))], dtype=np.int64)
    rng = np.random.default_rng(7)
    # A slow vol-regime sine on the daily log-return drives a genuine two/three-state HMM,
    # plus light idiosyncratic noise so neither the return nor the vol observation degenerates.
    k = np.arange(ts.size, dtype=float)
    daily_ret = 0.01 * np.sin(2.0 * np.pi * k / 90.0) + rng.normal(0.0, 0.02, ts.size)
    close = 30_000.0 * np.exp(np.cumsum(daily_ret))
    open_ = np.empty_like(close)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    # Intraday range scaled by the |daily move| so the Yang-Zhang vol observation varies.
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
    tmp = tmp_path_factory.mktemp("wf_full_pipeline")
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


def _leg_spans(start: Ms, end: Ms) -> list[tuple[int, int, int]]:
    """Replicate the runner's leg layout: ``(train_start, test_start, test_end)`` per leg."""
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


def _stub_dsr(rets: pd.Series, n_trials: int, var_sr: float, ann: float) -> DSRReport:
    """A deterministic DSR stub (the real DSR pulls scipy; the leak invariants do not need it)."""
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


class _FitSpy:
    """Capture the per-call ``ts_open`` extent that reaches each real fit (the leak probe).

    Wraps the FROZEN :meth:`HistGBMMetaModel.fit` / :meth:`RegimeHMM.fit` (Phase 9/11 are not
    edited): the spy records the max decision/observation ``ts_open`` handed to each fit, then
    delegates to the genuine method so the run is a REAL gated walk-forward, not a stub.
    """

    def __init__(self) -> None:
        self.meta_max_ts: list[int] = []
        self.hmm_max_ts: list[int] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spy = self
        real_meta_fit = HistGBMMetaModel.fit
        real_hmm_fit = RegimeHMM.fit

        def meta_fit(
            self_model: HistGBMMetaModel,
            X: pd.DataFrame,
            y: pd.Series,
            w: pd.Series,
            t1: pd.Series,
            windows: FitWindows,
            *,
            label_is_net: bool = True,
            allow_gross_label: bool = False,
        ) -> HistGBMMetaModel:
            ts = X.index.get_level_values("ts_open").to_numpy(dtype=np.int64)
            if ts.size:
                spy.meta_max_ts.append(int(ts.max()))
            return real_meta_fit(
                self_model,
                X,
                y,
                w,
                t1,
                windows,
                label_is_net=label_is_net,
                allow_gross_label=allow_gross_label,
            )

        def hmm_fit(self_model: RegimeHMM, obs: pd.DataFrame) -> RegimeHMM:
            ts = obs.index.to_numpy(dtype=np.int64)
            if ts.size:
                spy.hmm_max_ts.append(int(ts.max()))
            return real_hmm_fit(self_model, obs)

        monkeypatch.setattr(HistGBMMetaModel, "fit", meta_fit)
        monkeypatch.setattr(RegimeHMM, "fit", hmm_fit)


@dataclass(frozen=True)
class _GatedRun:
    """The shared, typed result bundle every gated-pipeline test reads off (module-scoped)."""

    result: WalkForwardResult
    spans: list[tuple[int, int, int]]
    spy: _FitSpy
    out_dir: Path


@pytest.fixture(scope="module")
def gated_run(env: Env, tmp_path_factory: pytest.TempPathFactory) -> Iterator[_GatedRun]:
    """Run ``ml=True, regime=True`` ONCE (module-scoped), capturing the fit spies + spans.

    The genuine Baum-Welch HMM fit on ~720-740 daily rows is the only heavyweight step, so the
    full gated walk-forward is run a single time and every test reads off the shared result.
    """
    mp = pytest.MonkeyPatch()
    spy = _FitSpy()
    spy.install(mp)
    start, end = T0, T0 + N_BARS * HOUR
    out_dir = tmp_path_factory.mktemp("wf_full_out")
    log = ExperimentLog(out_dir / "experiments.jsonl")
    result = _runner(env).run(
        start,
        end,
        train_bars=_TRAIN,
        test_bars=_TEST,
        allocator="rank",
        out_dir=out_dir,
        now_ms=T0 + (N_BARS + 1) * HOUR,
        alpha_names=[_ALPHA],
        experiment_log=log,
        dsr_fn=_stub_dsr,
        ml=True,
        regime=True,
    )
    spans = _leg_spans(start, end)
    yield _GatedRun(result=result, spans=spans, spy=spy, out_dir=out_dir)
    mp.undo()


class TestNoTestSpanLeak:
    """D3/D4: NO ``ts_open >= test_start`` row enters EITHER real fit, for every leg."""

    def test_at_least_one_real_meta_and_hmm_fit_fired(self, gated_run: _GatedRun) -> None:
        """The spies fired — a real HistGBM AND a real RegimeHMM fit actually ran.

        Guards against a vacuous leak proof: if every leg cold-started to identity, the
        ``< test_start`` assertions below would hold trivially. We require at least one genuine
        meta fit and at least one genuine HMM fit (the late legs cross MIN_FIT_DAYS), so the
        leak invariant is asserted against fits that really consumed data.
        """
        spy = gated_run.spy
        assert spy.meta_max_ts, "no HistGBMMetaModel.fit fired — the ml gate never trained"
        assert spy.hmm_max_ts, (
            "no RegimeHMM.fit fired — the regime gate cold-started on every leg "
            "(the daily-BTC series is too short to cross MIN_FIT_DAYS on any leg)"
        )

    def test_no_meta_fit_consumed_a_test_span_decision_bar(self, gated_run: _GatedRun) -> None:
        """Every meta fit's max decision ``ts_open`` precedes its leg's ``test_start`` (D4).

        The fits fire in leg order; each captured max must sit strictly before SOME leg's
        ``test_start`` and, conservatively, before the LATEST leg's ``test_start`` (the purged
        train window ``[train_start, test_start)`` and ``fit_end = test_start - h·Δ`` both
        clamp the fit strictly below the test span).
        """
        spy = gated_run.spy
        spans = gated_run.spans
        test_starts = sorted(test_start for _ts, test_start, _te in spans)
        # The meta fits fire one-per-(non-cold-start)-leg, in leg order; pair each captured max
        # with the leg it belongs to and assert it precedes that leg's own test_start. Because
        # an early leg may cold-start the META path too (too few events), pair from the LAST
        # legs backward (the legs that actually trained), the tightest honest pairing.
        maxes = spy.meta_max_ts
        paired_test_starts = test_starts[len(test_starts) - len(maxes) :]
        for captured_max, leg_test_start in zip(maxes, paired_test_starts, strict=True):
            assert captured_max < leg_test_start, (
                f"meta fit saw decision ts_open {captured_max} >= test_start "
                f"{leg_test_start} (a test-span bar leaked into the per-leg meta fit)"
            )

    def test_no_hmm_fit_consumed_a_test_span_daily_obs(self, gated_run: _GatedRun) -> None:
        """Every HMM fit's max daily ``obs.index`` precedes its leg's ``test_start`` (D3).

        The expanding window is sliced ``ts_open < test_start`` BEFORE build_observations, so the
        captured max daily obs ts must sit strictly below the leg's test_start. The HMM fits fire
        only on the legs that cross MIN_FIT_DAYS (the later legs), paired from the last backward.
        """
        spy = gated_run.spy
        spans = gated_run.spans
        test_starts = sorted(test_start for _ts, test_start, _te in spans)
        maxes = spy.hmm_max_ts
        paired_test_starts = test_starts[len(test_starts) - len(maxes) :]
        for captured_max, leg_test_start in zip(maxes, paired_test_starts, strict=True):
            assert captured_max < leg_test_start, (
                f"HMM fit saw daily obs ts_open {captured_max} >= test_start "
                f"{leg_test_start} (a test-span day leaked into the expanding HMM fit)"
            )


class TestColdStartFallback:
    """D3: an early leg with < MIN_FIT_DAYS obs uses IdentityRegime (G≡1) and bumps the frac."""

    def test_some_but_not_all_legs_cold_started(self, gated_run: _GatedRun) -> None:
        """``0 < gate_inactive_frac < 1``: the early legs fell back, the late legs fit (D3).

        The daily-BTC anchor is tuned so the early legs' expanding windows carry
        ``< MIN_FIT_DAYS`` finite obs (IdentityRegime fallback — counted in ``gate_inactive``)
        and the later legs carry ``>=`` (a real HMM fit). Both ends of the fallback are
        therefore exercised in ONE run, and the run survives (no raise) — the headline D3
        invariant: a missing-data leg gates by ``G ≡ 1``, never a crash.
        """
        result = gated_run.result
        validation = result.validation
        assert validation is not None
        frac = validation.gate_inactive_frac
        # The cold-start legs fired the fallback; the real-fit legs did not — strictly between.
        assert 0.0 < frac < 1.0, (
            f"expected a MIX of cold-start and real-fit legs (0 < frac < 1); got {frac} "
            "(the daily-BTC anchor no longer straddles MIN_FIT_DAYS across the leg fan)"
        )

    def test_cold_start_count_matches_legs_below_min_fit_days(self, gated_run: _GatedRun) -> None:
        """The fallback count equals the number of legs whose < test_start window is < MIN_FIT_DAYS.

        Cross-checks the runner's ``gate_inactive`` against the daily series directly: a leg
        cold-starts iff the count of finite daily obs available before its ``test_start`` is
        below :data:`~alphaforge.regime.hmm.MIN_FIT_DAYS`. Number of HMM fits that actually fired
        (the spy) must equal the number of legs at/above MIN_FIT_DAYS.
        """
        result = gated_run.result
        spans = gated_run.spans
        spy = gated_run.spy
        daily = _daily_btc_frame()
        daily_ts = daily.index.to_numpy(dtype=np.int64)
        n_legs = len(spans)

        below = 0
        atleast = 0
        for _ts, test_start, _te in spans:
            pre = daily.iloc[daily_ts < test_start]
            # build_observations drops the YZ + 1-bar-return warm-up; mirror that finite count.
            from alphaforge.regime.hmm import build_observations

            try:
                obs = build_observations(pre)
                finite = len(obs)
            except ValueError:
                finite = 0
            if finite < MIN_FIT_DAYS:
                below += 1
            else:
                atleast += 1

        validation = result.validation
        assert validation is not None
        frac = validation.gate_inactive_frac
        assert frac == pytest.approx(below / n_legs)
        assert len(spy.hmm_max_ts) == atleast, (
            f"expected {atleast} real HMM fits (legs >= MIN_FIT_DAYS); the spy saw "
            f"{len(spy.hmm_max_ts)}"
        )


class TestOneStitchedArtifactSet:
    """One stitched OOS artifact set is written for the whole gated walk-forward."""

    def test_single_equity_json_tearsheet_and_legs_tree(self, gated_run: _GatedRun) -> None:
        out_dir = gated_run.out_dir
        assert (out_dir / "equity.parquet").exists()
        assert (out_dir / "walkforward.json").exists()
        assert (out_dir / "summary.txt").exists()
        # Exactly ONE stitched tearsheet (the text panel always renders; the png is best-effort).
        assert (out_dir / "tearsheet.txt").exists()
        # ONE legs/ tree with one subdir per leg (no duplicate stitched curves).
        leg_dirs = sorted((out_dir / "legs").glob("leg_*"))
        assert len(leg_dirs) == len(gated_run.spans)
        # The stitched equity is a single monotone-in-time curve over the OOS span.
        equity = pd.read_parquet(out_dir / "equity.parquet")
        ts = equity["ts"].to_numpy(dtype=np.int64)
        assert ts.size > 0
        assert bool(np.all(np.diff(ts) > 0)), "stitched equity ts must be strictly increasing"


class TestNextOpenFills:
    """Pipeline order ends in next-open fills: every fill prints at ``decision_ts + Δ``."""

    def test_every_fill_is_at_the_next_open(self, gated_run: _GatedRun) -> None:
        """Every fill prints at the NEXT open — ``fill.ts == decision_ts`` (the decision close).

        The engine decides at a bar's CLOSE ``t`` (= ``decision_ts``, encoded in the
        ``client_order_id`` ``bt-{decision_ts}-{iid}``) and fills against the bar OPENING at that
        close — ``Fill.ts == next_bar.ts_open == decision_ts`` (engine.py: "the bar opening at
        that close, ts_open == decision_ts"). So the fill prints exactly one bar (Δ) after the
        decision bar's OWN open (``decision_ts - Δ``): never on the decision bar itself. This pins
        the tail of the gated pipeline factors→blend→ml→regime→optimizer→next-open fills (the same
        next-open discipline the golden master / mu-contract tests assert on the un-gated path).
        """
        result = gated_run.result
        fills = result.fills
        assert len(fills) > 0, "the gated OOS book never traded — cannot assert next-open fills"
        fill_ts = fills["ts"].to_numpy(dtype=np.int64)
        cids = [str(c) for c in fills["client_order_id"].tolist()]
        for ts_val, cid in zip(fill_ts, cids, strict=True):
            assert cid.startswith("bt-"), f"unexpected client_order_id shape: {cid!r}"
            decision_ts = int(cid.split("-")[1])
            # Fill at the next open = the bar opening at the decision close (ts_open ==
            # decision_ts), i.e. exactly Δ after the decision bar's own open — no same-bar
            # lookahead. The decision bar's own open is decision_ts - Δ; the fill is one Δ later.
            assert int(ts_val) == decision_ts, (
                f"fill ts {int(ts_val)} != decision close {decision_ts} (next-open violated)"
            )
            assert int(ts_val) == (decision_ts - HOUR) + HOUR  # = decision bar open + Δ
