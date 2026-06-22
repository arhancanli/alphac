"""Honest trial count + must-beat-baseline gate (``12_FINAL.md`` test 5, D5/D6).

This exercises the :class:`~alphaforge.analytics.walkforward.WalkForwardRunner`'s
anti-overfit accounting END-TO-END against ONE shared
:class:`~alphaforge.validation.experiments.ExperimentLog`, on a TINY synthetic
``tmp_path`` lake driven by the REAL ``SignalService`` (no signal stubs — the runner's
own gated machinery runs the four legs). A deterministic ``dsr_fn`` stub controls the
DSR/Sharpe so the assertions never depend on the random fixture's realized curve.

What is pinned (CRITIQUE_overfit #1/#2):

* **D6 honest trial count.** Running blend-only, ``--ml``, ``--regime`` and
  ``--ml --regime`` against the SAME ledger yields FOUR distinct config hashes
  (``n_trials() == 4``); each gated run also re-records the blend-only baseline under
  the SAME (gate-keyless) ``base_trial_config``, so it is idempotent and never a 5th
  trial. Re-running any one combination is idempotent (still 4).
* **D6 gate params are in the hash, not just the booleans.** Tuning a gate parameter —
  ``regime_n_states`` 3→2, or the ml feature set — makes a FIFTH distinct hash, because
  ``_gate_trial_config`` hashes the actual params (``regime_n_states`` /
  ``ml_feature_set_sha`` …), not two flags.
* **D5 must-beat-baseline.** A gated ``ValidationReport`` carries a ``baseline`` whose
  DSR is the blend-only trial's; a gated variant whose ``dsr <= baseline.dsr`` OR
  ``sr_ann <= baseline.sr_ann`` (we construct an exact tie) has
  ``clears_baseline_gate is False`` and is reported NOT live-eligible.
* **Round-trip.** ``validation.variant`` / ``clears_baseline_gate`` / nested
  ``baseline`` survive ``to_json_obj`` and reload byte-for-byte.

Offline, ``tmp_path`` lake only, deterministic (seeded rng), no network. The daily-BTC
window is far shorter than ``MIN_FIT_DAYS`` (730), so ``--regime`` rides the documented
IdentityRegime cold-start fallback (D3) — the real HMM fit is pinned elsewhere — keeping
the whole module well under the fast-test budget.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.analytics.walkforward import (
    ValidationReport,
    WalkForwardRunner,
    compare_to_baseline,
    compute_validation,
)
from alphaforge.config.settings import Settings, SignalsCfg
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.costs import TransactionCostModel
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.registry import default_registry
from alphaforge.signals.service import SignalService
from alphaforge.validation.experiments import ExperimentLog

if TYPE_CHECKING:
    from collections.abc import Iterator

    from alphaforge.core.time import Ms
    from alphaforge.validation.dsr import DSRReport

HOUR = 3_600_000
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z (1h-aligned)
# 44 days of 1h bars; the 31-day train warms all three real gates the OOS curve needs
# (the 30-day-median ADV, the 240-bar covariance window, the 169-bar momentum lookback).
# With train=744/test=96 the splitter tiles three OOS legs — mirrors test_cli_gated_flags.
N_BARS = 1056
_TRAIN_BARS = 31 * 24  # 744 bars
_TEST_BARS = 4 * 24  # 96 bars OOS per leg
_END = T0 + N_BARS * HOUR

BTC = "BINANCE:PERP:BTCUSDT"
MEMBERS = (BTC, *(f"BINANCE:PERP:{b}USDT" for b in ("ETH", "SOL", "ADA", "DOGE")))
ALL_IDS = list(MEMBERS)
_DRIFTS = (0.002, -0.002, 0.0015, -0.0015, 0.001)
# ONE pure-price directional alpha that warms inside the train window (lookback 169 < 744).
_ALPHA = "mom_xs_168_24"
_ALPHAS = [_ALPHA]
_INITIAL_CASH = 100_000.0
_NOW_MS = 1_700_000_000_000

# Ledger-hygiene FORWARD tripwire (the owner's integrity mandate). The real dedicated
# ledger var/experiments.jsonl holds 77 honest distinct records TODAY; this ceiling is
# set ABOVE that real count so it catches FUTURE inflation of the trial count N (which
# would silently flatter the DSR deflation) without ever forcing a retroactive "pass".
# It is NEVER set below the real count and records are NEVER purged — shrinking N to
# flatter DSR is exactly the dishonesty this tripwire exists to prevent.
HONEST_N_BUDGET = 80

# The dedicated experiments ledger, resolved from the repo root (…/tests/integration/… ->
# repo root is parents[2]). This is the REAL committed ledger, not a tmp_path fixture.
_REAL_LEDGER = Path(__file__).resolve().parents[2] / "var" / "experiments.jsonl"


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
        listed_ts=T0 - 365 * 24 * HOUR,
        delisted_ts=None,
    )


class _SyntheticDailyBtc:
    """A :class:`~alphaforge.analytics.walkforward.DailyBtcReader` over a synthetic daily
    BTC sine+noise series. The window is far shorter than ``MIN_FIT_DAYS`` (730), so every
    leg's expanding ``ts_open < test_start`` slice cold-starts to IdentityRegime — the
    documented D3 fallback the regime variant rides here (the real >=730-day HMM fit is
    pinned by the runner's pipeline test)."""

    def read_daily_btc(self, start: Ms, end: Ms) -> pd.DataFrame:
        day = 24 * HOUR
        ts = np.arange(int(start), int(end), day, dtype=np.int64)
        k = np.arange(ts.size, dtype=float)
        close = 30_000.0 * (1.0 + 0.05 * np.sin(k / 7.0))
        return pd.DataFrame(
            {
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
            },
            index=pd.Index(ts, dtype="int64", name="ts_open"),
        )


@dataclass(frozen=True)
class Env:
    reader: PITDataReader
    instruments: InstrumentStore
    universe: UniverseStore
    cost_model: TransactionCostModel
    settings: Settings
    service_factory: object  # callable[[], SignalService]


@pytest.fixture
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    """A tiny synthetic lake + SCD2 instruments + PIT universe, all under tmp_path."""
    tmp = tmp_path_factory.mktemp("honest_trial")
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

    instruments = InstrumentStore(tmp / "instruments.db")
    for iid in ALL_IDS:
        instruments.upsert(_instrument(iid), as_of=T0 - 365 * 24 * HOUR)

    reader = PITDataReader(paths)
    cfg = SignalsCfg()

    def make_service() -> SignalService:
        return SignalService(
            FeatureEngine(reader, instruments, universe),
            universe,
            default_registry(),
            cfg,
            alpha_names=_ALPHAS,
        )

    yield Env(
        reader=reader,
        instruments=instruments,
        universe=universe,
        cost_model=TransactionCostModel.from_settings(Settings()),
        settings=Settings(),
        service_factory=make_service,
    )
    instruments.close()


def _runner(
    env: Env,
    *,
    with_btc: bool = False,
    regime_n_states: int = 3,
) -> WalkForwardRunner:
    """A runner over the synthetic lake. ``with_btc`` injects the daily-BTC adapter the
    regime gate needs; ``regime_n_states`` tunes the HMM shape (a D6 trial-hash input)."""
    make_service = env.service_factory
    assert callable(make_service)
    return WalkForwardRunner(
        env.reader,
        env.instruments,
        env.universe,
        env.cost_model,
        make_service(),
        env.settings,
        daily_btc_reader=_SyntheticDailyBtc() if with_btc else None,
        regime_n_states=regime_n_states,
    )


class _FixedDSR:
    """A deterministic ``dsr_fn`` stub returning a FIXED :class:`DSRReport` per call.

    Records each call's args so the test can prove the variant and the baseline are each
    their own ``compute_validation`` (hence own ledger trial). Because variant and
    baseline get IDENTICAL ``dsr``/``sr_ann``, ``compare_to_baseline`` (strict ``>``)
    refuses the variant — the canonical D5 tie."""

    def __init__(self, *, dsr: float = 0.97, sr_ann: float = 1.23) -> None:
        self.calls: list[tuple[int, int, float, float]] = []
        self._dsr = dsr
        self._sr_ann = sr_ann

    def __call__(
        self,
        daily_returns: pd.Series,
        n_trials: int,
        sr_trials_variance: float,
        periods_per_year: float,
    ) -> DSRReport:
        from alphaforge.validation.dsr import DSRReport

        self.calls.append((len(daily_returns), n_trials, sr_trials_variance, periods_per_year))
        return DSRReport(
            psr=0.80,
            dsr=self._dsr,
            sr_ann=self._sr_ann,
            sr_per_period=0.064,
            skew=-0.2,
            kurtosis=4.1,
            n_obs=len(daily_returns),
            expected_max_sr=0.11,
        )


def _run(
    env: Env,
    log: ExperimentLog,
    *,
    ml: bool,
    regime: bool,
    regime_n_states: int = 3,
    alphas: list[str] | None = None,
    dsr_fn: _FixedDSR | None = None,
) -> ValidationReport | None:
    """Drive one ``runner.run`` over the tiny window, sharing ``log`` and ``dsr_fn``."""
    runner = _runner(env, with_btc=regime, regime_n_states=regime_n_states)
    result = runner.run(
        T0,
        _END,
        train_bars=_TRAIN_BARS,
        test_bars=_TEST_BARS,
        allocator="rank",
        initial_cash=_INITIAL_CASH,
        now_ms=_NOW_MS,
        alpha_names=_ALPHAS if alphas is None else alphas,
        experiment_log=log,
        dsr_fn=_FixedDSR() if dsr_fn is None else dsr_fn,
        ml=ml,
        regime=regime,
    )
    return result.validation


class TestHonestTrialCount:
    """D6 — four gate combinations are four distinct trials; gate params are in the hash."""

    def test_four_combinations_are_four_distinct_trials(self, env: Env, tmp_path: Path) -> None:
        log = ExperimentLog(tmp_path / "ledger.jsonl")
        _run(env, log, ml=False, regime=False)
        assert log.n_trials() == 1, "blend-only is one trial"
        _run(env, log, ml=True, regime=False)
        # The ml run records its own (ml) trial AND re-records the blend-only baseline
        # under the SAME gate-keyless base_trial_config (idempotent) — net +1.
        assert log.n_trials() == 2, "ml adds exactly one distinct trial (baseline is idempotent)"
        _run(env, log, ml=False, regime=True)
        assert log.n_trials() == 3, "regime adds exactly one distinct trial"
        _run(env, log, ml=True, regime=True)
        assert log.n_trials() == 4, "ml+regime adds exactly one distinct trial"

    def test_rerun_is_idempotent(self, env: Env, tmp_path: Path) -> None:
        log = ExperimentLog(tmp_path / "ledger.jsonl")
        for ml, regime in ((False, False), (True, False), (False, True), (True, True)):
            _run(env, log, ml=ml, regime=regime)
        assert log.n_trials() == 4
        # Re-run every combination: each hash already on the ledger, so N is unchanged.
        for ml, regime in ((False, False), (True, False), (False, True), (True, True)):
            _run(env, log, ml=ml, regime=regime)
        assert log.n_trials() == 4, "re-running identical configs must not inflate N (idempotent)"

    def test_tuning_regime_n_states_makes_a_fifth_hash(self, env: Env, tmp_path: Path) -> None:
        """D6: ``regime_n_states`` is hashed into ``trial_config`` — 3 vs 2 are distinct."""
        log = ExperimentLog(tmp_path / "ledger.jsonl")
        _run(env, log, ml=False, regime=True, regime_n_states=3)
        n3 = log.n_trials()  # regime(3) trial + blend baseline = 2
        assert n3 == 2
        _run(env, log, ml=False, regime=True, regime_n_states=2)
        # A different n_states is a DISTINCT trial (the baseline is still idempotent).
        assert log.n_trials() == 3, "regime_n_states 3->2 must be a fifth distinct trial (D6)"

    def test_tuning_ml_feature_set_makes_a_distinct_hash(self, env: Env) -> None:
        """D6: the ml feature set enters the hash via ``ml_feature_set_sha``.

        We assert the trial-config helper directly (the runner pins ONE v1 feature set, so
        we cannot vary it through ``run``): a different resolved feature tuple yields a
        different ``ml_feature_set_sha`` and therefore a different config hash."""
        from alphaforge.validation.experiments import config_hash

        runner = _runner(env)
        base = {"start": T0, "end": _END, "allocator": "rank"}
        tc_a = {**base, **runner._gate_trial_config(ml=True, regime=False)}
        # Same knobs but a different resolved ml feature set => different sha => different hash.
        import hashlib

        tc_b = dict(tc_a)
        tc_b["ml_feature_set_sha"] = hashlib.sha256(b'["alpha_blend","ctx_vol"]').hexdigest()[:16]
        assert tc_a["ml_feature_set_sha"] != tc_b["ml_feature_set_sha"]
        assert config_hash(tc_a) != config_hash(tc_b), (
            "a different ml feature set must hash to a distinct trial (D6)"
        )

    def test_blend_only_trial_config_has_no_gate_keys(self, env: Env) -> None:
        """D7 on the ledger: with both gates off the trial config gains NO gate keys, so
        the blend-only hash is byte-identical to today's HEAD ledger."""
        runner = _runner(env)
        assert runner._gate_trial_config(ml=False, regime=False) == {}
        on = runner._gate_trial_config(ml=True, regime=True)
        assert on["ml"] is True
        assert on["regime"] is True
        assert "ml_feature_set_sha" in on
        assert on["regime_n_states"] == 3


class TestBaselineGate:
    """D5 — the gated report carries the blend-only baseline; a tie loses."""

    def test_gated_variant_carries_blend_only_baseline_dsr(self, env: Env, tmp_path: Path) -> None:
        log = ExperimentLog(tmp_path / "ledger.jsonl")
        stub = _FixedDSR(dsr=0.97, sr_ann=1.23)
        v = _run(env, log, ml=True, regime=False, dsr_fn=stub)
        assert v is not None
        assert v.variant == "ml"
        assert v.baseline is not None, "a gated variant must carry a blend-only baseline"
        # Two compute_validation calls: the variant, then the baseline (same stub).
        assert len(stub.calls) == 2
        # The baseline DSR is the blend-only trial's (the stub's fixed value here).
        assert v.baseline.dsr == pytest.approx(0.97)
        assert v.dsr == pytest.approx(0.97)

    def test_tie_fails_baseline_gate_and_is_not_live_eligible(
        self, env: Env, tmp_path: Path
    ) -> None:
        """A variant that exactly ties the baseline on DSR and Sharpe is refused (strict >).

        Even though the variant's own DSR (0.97) clears the 0.95 gate, ``clears_baseline_gate``
        is False because ``dsr > baseline.dsr`` and ``sr_ann > baseline.sr_ann`` are both
        strict — a tie does not earn the extra trial it costs (CRITIQUE_overfit #1)."""
        log = ExperimentLog(tmp_path / "ledger.jsonl")
        v = _run(env, log, ml=True, regime=True, dsr_fn=_FixedDSR(dsr=0.97, sr_ann=1.23))
        assert v is not None
        assert v.clears_dsr_gate is True, "the variant's own DSR clears 0.95"
        assert v.baseline is not None
        assert v.dsr == pytest.approx(v.baseline.dsr)
        assert v.sr_ann == pytest.approx(v.baseline.sr_ann)
        assert v.clears_baseline_gate is False, "an exact tie must NOT clear the baseline gate"

    def test_compare_to_baseline_predicate_strict_inequalities(self) -> None:
        """``compare_to_baseline`` is the D5 predicate: a tie on EITHER DSR or Sharpe loses."""
        base = _vr(dsr=0.96, sr_ann=1.0)
        # Strictly beats on both -> clears.
        assert compare_to_baseline(_vr(dsr=0.97, sr_ann=1.1), base) is True
        # Ties DSR -> loses.
        assert compare_to_baseline(_vr(dsr=0.96, sr_ann=1.1), base) is False
        # Ties Sharpe -> loses.
        assert compare_to_baseline(_vr(dsr=0.97, sr_ann=1.0), base) is False
        # Beats baseline but own DSR below the 0.95 gate -> loses.
        assert compare_to_baseline(_vr(dsr=0.94, sr_ann=1.1, clears=False), base) is False

    def test_losing_variant_round_trips_as_not_eligible_through_evaluate_logic(
        self, env: Env, tmp_path: Path
    ) -> None:
        """The same predicate the CLI ``evaluate`` reads: a gated, baseline-carrying report
        with ``clears_baseline_gate=False`` is NOT live-eligible on the baseline ground."""
        log = ExperimentLog(tmp_path / "ledger.jsonl")
        v = _run(env, log, ml=True, regime=False, dsr_fn=_FixedDSR(dsr=0.97, sr_ann=1.23))
        assert v is not None
        obj = v.to_json_obj()
        is_gated_variant = obj.get("baseline") is not None
        baseline_ok = (not is_gated_variant) or bool(obj.get("clears_baseline_gate"))
        assert is_gated_variant is True
        assert baseline_ok is False, "the tie is reported NOT live-eligible (D5)"


class TestValidationRoundTrip:
    """D5/3b — variant / clears_baseline_gate / nested baseline survive to_json_obj."""

    def test_gated_validation_round_trips(self, env: Env, tmp_path: Path) -> None:
        log = ExperimentLog(tmp_path / "ledger.jsonl")
        v = _run(env, log, ml=True, regime=True, dsr_fn=_FixedDSR(dsr=0.97, sr_ann=1.23))
        assert v is not None
        obj = v.to_json_obj()
        # The Phase-12 gate keys are present on a gated report.
        assert obj["variant"] == "ml+regime"
        assert obj["clears_baseline_gate"] is False
        assert isinstance(obj["baseline"], dict)
        assert "gate_inactive_frac" in obj
        # The nested baseline is itself a blend-only report (the nine pre-Phase-12 keys,
        # NO recursive gate keys).
        baseline_obj = obj["baseline"]
        assert isinstance(baseline_obj, dict)
        assert "variant" not in baseline_obj
        assert "baseline" not in baseline_obj
        assert baseline_obj["dsr"] == pytest.approx(0.97)
        # Survives a JSON serialize/parse cycle unchanged (the persisted walkforward.json).
        reparsed = json.loads(json.dumps(obj, sort_keys=True))
        assert reparsed == obj

    def test_blend_only_validation_omits_gate_keys(self, env: Env, tmp_path: Path) -> None:
        """D7: the blend-only report emits EXACTLY the nine pre-Phase-12 keys."""
        log = ExperimentLog(tmp_path / "ledger.jsonl")
        v = _run(env, log, ml=False, regime=False, dsr_fn=_FixedDSR())
        assert v is not None
        obj = v.to_json_obj()
        assert "variant" not in obj
        assert "baseline" not in obj
        assert "clears_baseline_gate" not in obj
        assert "gate_inactive_frac" not in obj


# --------------------------------------------------------------------------- helpers


def _vr(*, dsr: float, sr_ann: float, clears: bool = True) -> ValidationReport:
    """A minimal :class:`ValidationReport` for the pure-predicate assertions."""
    return ValidationReport(
        psr=0.8,
        dsr=dsr,
        sr_ann=sr_ann,
        n_trials=2,
        n_trials_used=2,
        expected_max_sr=0.1,
        sr_trials_variance=1.0,
        n_obs=30,
        clears_dsr_gate=clears,
    )


def _synthetic_equity(seed: int, *, n_days: int = 120, mu: float = 0.0004) -> pd.Series:
    """A deterministic hourly equity curve spanning ``n_days`` UTC days (for the
    provenance / re-deflation tests, which need a real >=2-UTC-day OOS curve)."""
    rng = np.random.default_rng(seed)
    n = n_days * 24
    rets = rng.normal(mu, 0.008, n)
    vals = 100_000.0 * np.exp(np.cumsum(rets))
    idx = np.array([T0 + k * HOUR for k in range(n)], dtype=np.int64)
    return pd.Series(vals, index=pd.Index(idx, name="ts"), name="equity")


# =========================================================================== PART B
# Ledger hygiene: the FORWARD trial-count tripwire + re-deflation + provenance.


class TestLedgerHygiene:
    """B6 — the real ledger is idempotent and below the FORWARD budget tripwire."""

    def test_ledger_distinct_hash_vs_budget(self) -> None:
        """Parse the REAL ``var/experiments.jsonl``: every record is a distinct hash
        (idempotency) AND the distinct count is within ``HONEST_N_BUDGET`` (forward
        tripwire). The budget is set ABOVE the real count to catch FUTURE inflation;
        the assertion must NEVER be made to pass by shrinking N (integrity mandate)."""
        if not _REAL_LEDGER.exists():
            pytest.skip(f"real ledger {_REAL_LEDGER} absent in this checkout")
        log = ExperimentLog(_REAL_LEDGER)
        records = log.all()
        n_records = len(records)
        n_distinct = log.n_trials()  # len of the deduplicated hash set
        # Idempotency: no duplicate hashes were ever appended (re-runs are no-ops).
        assert n_distinct == n_records, (
            f"ledger has {n_records} records but only {n_distinct} distinct hashes — "
            "a duplicate hash means record() idempotency was bypassed"
        )
        # Forward tripwire: catches FUTURE inflation, never shrinks the honest count.
        assert n_distinct <= HONEST_N_BUDGET, (
            f"distinct trial count {n_distinct} exceeds the HONEST_N_BUDGET "
            f"({HONEST_N_BUDGET}) forward tripwire — N inflated; investigate before "
            "trusting any DSR deflated against it (do NOT raise the budget to silence this)"
        )

    def test_budget_is_a_forward_tripwire_above_the_real_count(self) -> None:
        """The budget is documented to sit ABOVE today's real count (never below it),
        so it is a forward tripwire and cannot retroactively force a pass by shrinking N."""
        if not _REAL_LEDGER.exists():
            pytest.skip(f"real ledger {_REAL_LEDGER} absent in this checkout")
        n_distinct = ExperimentLog(_REAL_LEDGER).n_trials()
        assert n_distinct <= HONEST_N_BUDGET, (
            "HONEST_N_BUDGET must be >= the real distinct count (a forward tripwire); "
            "a budget below the real N would be a dishonest retroactive pass"
        )


class TestReDeflationFromLedgerN:
    """B7 — compute_validation deflates against the LEDGER N at verdict time, not a
    stale runtime N snapshot taken before the trial was recorded."""

    def test_deployable_verdicts_use_re_deflated_dsr(self, tmp_path: Path) -> None:
        """``compute_validation`` reads ``n_trials`` / ``V[SR]`` AFTER recording, so the
        DSR's ``n_trials`` is the post-record verdict-time N (this trial counted), and
        it RISES as more distinct configs land on the SAME ledger — proving the
        deflation tracks the ledger, not a frozen runtime value."""
        log = ExperimentLog(tmp_path / "ledger.jsonl")
        seen_n: list[int] = []

        def _capturing_dsr(
            daily_returns: pd.Series,
            n_trials: int,
            sr_trials_variance: float,
            periods_per_year: float,
        ) -> DSRReport:
            from alphaforge.validation.dsr import DSRReport

            seen_n.append(n_trials)
            return DSRReport(
                psr=0.8,
                dsr=0.97,
                sr_ann=1.23,
                sr_per_period=0.064,
                skew=-0.2,
                kurtosis=4.1,
                n_obs=len(daily_returns),
                expected_max_sr=0.11,
            )

        r1 = compute_validation(
            _synthetic_equity(1), {"cfg": "a"}, log, now_ms=1, dsr_fn=_capturing_dsr
        )
        assert r1 is not None
        # One distinct trial recorded; the maths is fed max(2, 1) = 2 but the report's
        # honest n_trials is 1 — and it is the POST-record value (the trial is counted).
        assert r1.n_trials == 1
        assert seen_n[-1] == 2

        r2 = compute_validation(
            _synthetic_equity(2), {"cfg": "b"}, log, now_ms=2, dsr_fn=_capturing_dsr
        )
        assert r2 is not None
        # A second distinct config lands on the SAME ledger -> the deflation N the DSR
        # sees rises to 2 (verdict-time, post-record), proving it re-reads the ledger.
        assert r2.n_trials == 2
        assert seen_n[-1] == 2

        # Re-running config "a" is idempotent: N does NOT inflate (still 2), and the DSR
        # is re-deflated against the SAME ledger N, never a stale larger runtime value.
        r1b = compute_validation(
            _synthetic_equity(1), {"cfg": "a"}, log, now_ms=3, dsr_fn=_capturing_dsr
        )
        assert r1b is not None
        assert r1b.n_trials == 2
        assert log.n_trials() == 2


class TestValidationProvenance:
    """B8 — the report carries an audit ``_provenance`` block (opt-in, byte-safe OFF)."""

    def test_provenance_block_records_ledger_n_and_hash(self, tmp_path: Path) -> None:
        from alphaforge.validation.experiments import config_hash

        ledger = tmp_path / "ledger.jsonl"
        log = ExperimentLog(ledger)
        cfg = {"cfg": "a", "allocator": "rank"}
        report = compute_validation(
            _synthetic_equity(9), cfg, log, now_ms=1, with_provenance=True
        )
        assert report is not None
        obj = report.to_json_obj()
        prov = obj["_provenance"]
        assert isinstance(prov, dict)
        assert prov["ledger_path"] == str(ledger)
        assert prov["n_trials_at_verdict_time"] == log.n_trials() == 1
        assert prov["trial_config_hash_this_run"] == config_hash(cfg)
        # Survives a JSON round-trip unchanged.
        assert json.loads(json.dumps(obj, sort_keys=True)) == obj

    def test_provenance_omitted_by_default_preserves_byte_identity(self, tmp_path: Path) -> None:
        """Without ``with_provenance`` the report emits NO ``_provenance`` key, so the
        OFF-path walkforward.json stays byte-identical to today's HEAD (D7)."""
        log = ExperimentLog(tmp_path / "ledger.jsonl")
        report = compute_validation(_synthetic_equity(9), {"cfg": "a"}, log, now_ms=1)
        assert report is not None
        assert "_provenance" not in report.to_json_obj()


class TestPreSealHashedHoldoutFreshSlice:
    """B9 — pre-seal a hashed holdout on a FRESH synthetic slice (never retro-seal a
    window already fit). The seal is the config-hash of the held-out trial config; it
    must be reproducible from the same config and must NOT collide with the in-sample
    config's hash."""

    def test_pre_seal_hashed_holdout_fresh_slice(self, tmp_path: Path) -> None:
        from alphaforge.validation.experiments import config_hash

        # A FRESH synthetic out-of-time slice that has never been fit (NOT the real
        # 2023-2026 history). Pre-sealing here is honest: we hash the holdout's defining
        # config BEFORE looking at any result on it.
        holdout_window = {"start": T0 + 999 * HOUR, "end": T0 + 1999 * HOUR}
        holdout_config = {
            "allocator": "rank",
            "alpha_names": [_ALPHA],
            "rebalance_bars": 72,
            "no_trade_band": 0.0030,
            **holdout_window,
        }
        seal = config_hash(holdout_config)

        # The seal is deterministic and reproducible from the same config (key order
        # does not matter — config_hash canonicalizes).
        reordered = {k: holdout_config[k] for k in sorted(holdout_config)}
        assert config_hash(reordered) == seal

        # The holdout is a DISTINCT trial from the in-sample window (no accidental reuse).
        in_sample_config = {**holdout_config, "start": T0, "end": T0 + 998 * HOUR}
        assert config_hash(in_sample_config) != seal

        # Record the holdout AS its own pre-sealed trial on a fresh ledger and confirm the
        # ledger's stored hash equals the pre-computed seal (the seal is what gets counted).
        log = ExperimentLog(tmp_path / "holdout_ledger.jsonl")
        rec = log.record(
            holdout_config,
            sharpe_ann=1.1,
            sharpe_per_period=0.058,
            n_obs=40,
            skew=-0.1,
            kurtosis=3.5,
            now_ms=_NOW_MS,
        )
        assert rec.config_hash == seal
        assert log.n_trials() == 1
        # Re-recording the SAME pre-sealed holdout is idempotent (no N inflation).
        log.record(
            holdout_config,
            sharpe_ann=2.2,
            sharpe_per_period=0.099,
            n_obs=40,
            skew=0.0,
            kurtosis=3.0,
            now_ms=_NOW_MS + 1,
        )
        assert log.n_trials() == 1, "re-sealing the identical holdout must not inflate N"
