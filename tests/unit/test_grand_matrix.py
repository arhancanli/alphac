"""Unit tests for the grand-backtest analysis core (:mod:`alphaforge.analytics.grand_matrix`).

Everything here runs on SYNTHETIC per-config fixtures (never the live lake): a
hand-built :class:`~alphaforge.analytics.walkforward.WalkForwardResult` (equity
Series + ``summarize`` + a :class:`~alphaforge.analytics.walkforward.ValidationReport`)
and a real :class:`~alphaforge.validation.experiments.ExperimentLog` ledger.

The load-bearing assertions are the two BLOCKING anti-overfit fixes from
``GB_CRITIQUE_*.md``:

* **B1 / GB1 — run-order invariance.** Every config's judged DSR and gate decisions
  are re-deflated against the SHARED final ``cross`` SR*, NOT the runner's
  per-config run-time ``validation.dsr``. The deflated winner and each config's
  ``clears_dsr_gate`` are IDENTICAL regardless of the order configs were recorded on
  the shared ledger.
* **B2 / GB4 — field sources.** ``sr_ann`` comes from ``validation.sr_ann`` (not the
  nonexistent ``summary.sr_ann``); ``turnover`` from ``summary.turnover_ann``;
  ``max_dd`` is the non-negative ``summary.max_dd`` depth fraction.
"""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest

from alphaforge.analytics.grand_matrix import (
    DSR_GATE,
    PBO_GATE,
    SCHEMA_VERSION,
    CapacityPoint,
    GrandConfig,
    MatrixRow,
    build_matrix_rows,
    capacity_curve,
    cross_config_dsr,
    matrix_pbo,
    oos_returns_matrix,
    reference_matrix,
    select_deflated_winner,
    write_matrix_json,
    write_verdict,
)
from alphaforge.analytics.metrics import daily_returns, summarize
from alphaforge.analytics.walkforward import ValidationReport, WalkForwardResult
from alphaforge.validation.experiments import ExperimentLog

if TYPE_CHECKING:
    from pathlib import Path

_HOUR = 3_600_000
_DAY = 24 * _HOUR
_T0 = 1_609_459_200_000  # 2021-01-01T00:00:00Z


# --------------------------------------------------------------------------- fixtures


def _equity(
    *, n_days: int, mu: float, sigma: float, seed: int, cash: float = 1_000_000.0
) -> pd.Series:
    """An hourly equity curve (>= 2 UTC days) with daily drift ``mu`` / vol ``sigma``."""
    n = n_days * 24
    rng = np.random.default_rng(seed)
    hourly = rng.normal(mu / 24.0, sigma / math.sqrt(24.0), n)
    eq = cash * np.exp(np.cumsum(hourly))
    eq = np.concatenate([[cash], eq])
    ts = _T0 + np.arange(eq.size, dtype=np.int64) * _HOUR
    return pd.Series(eq, index=pd.Index(ts, name="ts"), name="equity")


def _fills(equity: pd.Series, *, notional_per_day: float) -> pd.DataFrame:
    """A synthetic fills frame so ``summarize`` yields a finite ``turnover_ann`` (B2/GB4
    note: ``turnover_ann`` is ``nan`` unless fills carry a ``notional`` column)."""
    ts = equity.index.to_numpy(dtype=np.int64)
    day_starts = ts[::24]
    return pd.DataFrame(
        {
            "ts": day_starts.astype(np.int64),
            "notional": np.full(day_starts.size, notional_per_day, dtype=np.float64),
            "fee": np.full(day_starts.size, notional_per_day * 0.0005, dtype=np.float64),
        }
    )


def _validation(
    *, dsr: float, sr_ann: float, psr: float = 0.7, baseline: ValidationReport | None = None
) -> ValidationReport:
    """A :class:`ValidationReport` with controllable headline numbers."""
    clears = math.isfinite(dsr) and dsr >= DSR_GATE
    return ValidationReport(
        psr=psr,
        dsr=dsr,
        sr_ann=sr_ann,
        n_trials=4,
        n_trials_used=4,
        expected_max_sr=0.05,
        sr_trials_variance=1e-4,
        n_obs=90,
        clears_dsr_gate=clears,
        variant="ml" if baseline is not None else "blend",
        baseline=baseline,
        clears_baseline_gate=(baseline is not None and clears and dsr > baseline.dsr),
    )


def _result(
    *,
    n_days: int = 120,
    mu: float,
    sigma: float = 0.02,
    seed: int,
    cash: float = 1_000_000.0,
    runtime_dsr: float,
    sr_ann: float,
    psr: float = 0.7,
    baseline: ValidationReport | None = None,
    config: dict[str, object] | None = None,
) -> WalkForwardResult:
    """A fully-formed synthetic :class:`WalkForwardResult` (equity + summary + validation)."""
    eq = _equity(n_days=n_days, mu=mu, sigma=sigma, seed=seed, cash=cash)
    summary = summarize(eq, fills=_fills(eq, notional_per_day=cash * 0.1))
    return WalkForwardResult(
        equity=eq,
        legs=(),
        summary=summary,
        config=config or {},
        validation=_validation(dsr=runtime_dsr, sr_ann=sr_ann, psr=psr, baseline=baseline),
    )


def _ledger(tmp_path: Path, *, sharpes: list[float]) -> ExperimentLog:
    """A dedicated ledger seeded with ``sharpes`` per-period trial Sharpes."""
    log = ExperimentLog(tmp_path / "experiments.jsonl")
    for i, sr in enumerate(sharpes):
        log.record(
            {"trial": i},
            sharpe_ann=sr * math.sqrt(365.0),
            sharpe_per_period=sr,
            n_obs=90,
            skew=-0.1,
            kurtosis=3.5,
            now_ms=_T0,
        )
    return log


# --------------------------------------------------------------------------- GrandConfig / matrix


class TestReferenceMatrix:
    def test_blocks_a_and_c_without_best_variant(self) -> None:
        configs = reference_matrix()
        ids = [c.config_id for c in configs]
        assert ids == [
            "A_blend",
            "A_ml",
            "A_regime",
            "A_ml_regime",
            "C_rebal24",
            "C_band10",
            "C_mvo",
            "C_carry",
        ]
        # All 8 are distinct trials (no capacity rows yet).
        assert all(c.is_distinct_trial for c in configs)
        assert all(c.shares_trial_with is None for c in configs)

    def test_block_b_materialized_off_winner(self) -> None:
        winner = next(c for c in reference_matrix() if c.config_id == "A_regime")
        configs = reference_matrix(best_variant=winner)
        ids = [c.config_id for c in configs]
        assert ids == [
            "A_blend",
            "A_ml",
            "A_regime",
            "A_ml_regime",
            "B_cap_100k",
            "B_cap_1M",
            "B_cap_10M",
            "B_cap_100M",
            "C_rebal24",
            "C_band10",
            "C_mvo",
            "C_carry",
        ]
        caps = [c for c in configs if c.block == "B"]
        assert [c.initial_cash for c in caps] == [1e5, 1e6, 1e7, 1e8]
        # Capacity runs are NOT distinct trials and inherit every search knob from the winner.
        for c in caps:
            assert c.is_distinct_trial is False
            assert c.shares_trial_with == "A_regime"
            assert c.regime is True and c.ml is False
            assert c.rebalance_bars == winner.rebalance_bars
            assert c.allocator == winner.allocator

    def test_carry_knobs(self) -> None:
        carry = next(c for c in reference_matrix() if c.config_id == "C_carry")
        assert carry.alpha_names == ("carry_fund_21", "carry_fund_90", "mr_res_72")

    def test_carry_factor_names_resolve_in_registry(self) -> None:
        """Smoke the 'fail loudly on a typo'd factor' contract: all three names exist."""
        import alphaforge.features.library  # noqa: F401  (registers the factor library)
        from alphaforge.features.registry import default_registry

        registry = default_registry()
        carry = next(c for c in reference_matrix() if c.config_id == "C_carry")
        assert carry.alpha_names is not None
        for name in carry.alpha_names:
            assert name in registry, f"{name} must resolve against default_registry()"

    def test_out_dirname_is_config_id(self) -> None:
        cfg = GrandConfig(config_id="A_ml", block="A", ml=True)
        assert cfg.out_dirname() == "A_ml"

    def test_knobs_is_json_safe(self) -> None:
        cfg = GrandConfig(config_id="C_carry", block="C", alpha_names=("a", "b"))
        knobs = cfg.knobs()
        json.dumps(knobs)  # must not raise
        assert knobs["alpha_names"] == ["a", "b"]
        assert knobs["allocator"] == "rank"


# --------------------------------------------------------------------------- cross_config_dsr


class TestCrossConfigDSR:
    def test_reads_n_and_variance_off_ledger(self, tmp_path: Path) -> None:
        log = _ledger(tmp_path, sharpes=[0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08])
        cross = cross_config_dsr(log)
        assert cross.n_trials == 8
        assert cross.n_trials_used == 8
        # V[SR] is the sample variance of the per-period trial Sharpes.
        expected_var = float(np.var([0.01 * (i + 1) for i in range(8)], ddof=1))
        assert cross.sr_trials_variance == pytest.approx(expected_var)
        assert cross.expected_max_sr > 0.0

    def test_single_trial_uses_n_used_2_and_default_variance(self, tmp_path: Path) -> None:
        log = _ledger(tmp_path, sharpes=[0.03])
        cross = cross_config_dsr(log)
        assert cross.n_trials == 1
        assert cross.n_trials_used == 2  # max(2, N) for the expected-max form
        assert cross.sr_trials_variance == pytest.approx(1.0)  # DEFAULT_SR_TRIALS_VARIANCE


# ------------------------------------------------------------------- oos_returns_matrix / PBO


class TestOosReturnsMatrix:
    def test_builds_aligned_t_by_n_matrix(self) -> None:
        results = {
            "A_blend": _result(mu=0.0005, seed=1, runtime_dsr=0.3, sr_ann=0.4),
            "A_ml": _result(mu=0.0006, seed=2, runtime_dsr=0.4, sr_ann=0.5),
            "C_mvo": _result(mu=0.0004, seed=3, runtime_dsr=0.2, sr_ann=0.3),
        }
        m = oos_returns_matrix(results, ["A_blend", "A_ml", "C_mvo"])
        assert list(m.columns) == ["A_blend", "A_ml", "C_mvo"]
        assert len(m) >= 100  # ~119 daily rows from 120 days
        # Chronological (the index is the sorted epoch-ms daily grid).
        assert m.index.is_monotonic_increasing

    def test_rejects_fewer_than_two_columns(self) -> None:
        results = {"A_blend": _result(mu=0.0005, seed=1, runtime_dsr=0.3, sr_ann=0.4)}
        with pytest.raises(ValueError, match=">= 2 variant columns"):
            oos_returns_matrix(results, ["A_blend"])

    def test_rejects_missing_config(self) -> None:
        results = {"A_blend": _result(mu=0.0005, seed=1, runtime_dsr=0.3, sr_ann=0.4)}
        with pytest.raises(ValueError, match="missing from results"):
            oos_returns_matrix(results, ["A_blend", "A_ml"])

    def test_matrix_pbo_runs_at_small_even_n_splits(self) -> None:
        results = {
            f"v{i}": _result(mu=0.0003 + 0.0001 * i, seed=10 + i, runtime_dsr=0.3, sr_ann=0.4)
            for i in range(3)
        }
        pbo = matrix_pbo(results, list(results), n_splits=4, max_combinations=100, seed=42)
        assert 0.0 <= pbo.pbo <= 1.0
        assert pbo.n_configs == 3
        assert pbo.n_obs >= 4
        assert pbo.clears_pbo_gate == (pbo.pbo < PBO_GATE)

    def test_matrix_pbo_deterministic(self) -> None:
        results = {
            f"v{i}": _result(mu=0.0003 + 0.0001 * i, seed=20 + i, runtime_dsr=0.3, sr_ann=0.4)
            for i in range(4)
        }
        a = matrix_pbo(results, list(results), n_splits=4, max_combinations=50, seed=7)
        b = matrix_pbo(results, list(results), n_splits=4, max_combinations=50, seed=7)
        assert a == b

    def test_matrix_pbo_raises_diagnosably_when_too_few_rows(self) -> None:
        results = {
            "a": _result(n_days=5, mu=0.0005, seed=1, runtime_dsr=0.3, sr_ann=0.4),
            "b": _result(n_days=5, mu=0.0004, seed=2, runtime_dsr=0.2, sr_ann=0.3),
        }
        with pytest.raises(ValueError, match="aligned daily rows < n_splits"):
            matrix_pbo(results, ["a", "b"], n_splits=16)


# --------------------------------------------------------------------------- capacity_curve


class TestCapacityCurve:
    def test_ascending_with_validation_sr_ann_and_summary_fields(self, tmp_path: Path) -> None:
        cross = cross_config_dsr(_ledger(tmp_path, sharpes=[0.01, 0.02, 0.03, 0.04]))
        results = {
            "B_cap_10M": _result(mu=0.0002, seed=3, cash=1e7, runtime_dsr=0.2, sr_ann=0.20),
            "B_cap_100k": _result(mu=0.0006, seed=1, cash=1e5, runtime_dsr=0.4, sr_ann=0.60),
            "B_cap_1M": _result(mu=0.0004, seed=2, cash=1e6, runtime_dsr=0.3, sr_ann=0.40),
        }
        curve = capacity_curve(results, list(results), cross)
        # Ascending by initial_cash regardless of input order.
        assert [p.initial_cash for p in curve] == [1e5, 1e6, 1e7]
        # sr_ann is the validation.sr_ann (B2/GB4 — NOT summary, which has none).
        assert curve[0].sr_ann == pytest.approx(0.60)
        assert curve[1].sr_ann == pytest.approx(0.40)
        # turnover is finite (fills carry a notional column) and max_dd is non-negative.
        for p in curve:
            assert math.isfinite(p.turnover)
            assert p.max_dd >= 0.0
            assert math.isfinite(p.final_equity)
            # dsr is re-deflated against the SHARED cross (not a fresh per-capital N).
            assert math.isfinite(p.dsr)

    def test_missing_capacity_config_is_skipped(self, tmp_path: Path) -> None:
        cross = cross_config_dsr(_ledger(tmp_path, sharpes=[0.01, 0.02]))
        results = {"B_cap_1M": _result(mu=0.0004, seed=2, cash=1e6, runtime_dsr=0.3, sr_ann=0.4)}
        curve = capacity_curve(results, ["B_cap_100k", "B_cap_1M", "B_cap_10M"], cross)
        assert len(curve) == 1
        assert curve[0].initial_cash == pytest.approx(1e6)


# ------------------------------------------------------------------- winner / B1-GB1 invariance


def _block_a_results(
    *, blend_mu: float, ml_mu: float, regime_mu: float, ml_regime_mu: float
) -> dict[str, WalkForwardResult]:
    """Block-A results whose RE-DEFLATED DSR is what matters (the runtime_dsr is a decoy)."""
    blend = _result(mu=blend_mu, seed=100, runtime_dsr=0.10, sr_ann=blend_mu * 365 / 0.02)
    return {
        "A_blend": blend,
        "A_ml": _result(
            mu=ml_mu,
            seed=101,
            runtime_dsr=0.99,  # decoy: a flattering run-time DSR that must NOT decide the gate
            sr_ann=ml_mu * 365 / 0.02,
            baseline=blend.validation,
        ),
        "A_regime": _result(
            mu=regime_mu,
            seed=102,
            runtime_dsr=0.99,
            sr_ann=regime_mu * 365 / 0.02,
            baseline=blend.validation,
        ),
        "A_ml_regime": _result(
            mu=ml_regime_mu,
            seed=103,
            runtime_dsr=0.99,
            sr_ann=ml_regime_mu * 365 / 0.02,
            baseline=blend.validation,
        ),
    }


class TestSelectDeflatedWinner:
    def test_honest_null_when_nothing_clears(self, tmp_path: Path) -> None:
        """The expected Phase-10 outcome: weak signals, no deployable variant."""
        cross = cross_config_dsr(
            _ledger(tmp_path, sharpes=[0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08])
        )
        # Tiny daily drifts -> per-period Sharpe far below the deflated benchmark.
        results = _block_a_results(
            blend_mu=0.0001, ml_mu=0.0002, regime_mu=0.00015, ml_regime_mu=0.00018
        )
        assert select_deflated_winner(results, cross) is None

    def test_blend_is_never_eligible(self, tmp_path: Path) -> None:
        cross = cross_config_dsr(_ledger(tmp_path, sharpes=[0.01]))  # tiny N -> low SR*
        results = _block_a_results(
            blend_mu=0.02, ml_mu=0.0001, regime_mu=0.0001, ml_regime_mu=0.0001
        )
        # A_blend has the strongest curve, but it is the baseline and never wins.
        assert select_deflated_winner(results, cross) != "A_blend"

    def test_winner_when_a_variant_clears_strongly(self, tmp_path: Path) -> None:
        """A strong, low-V[SR] context where one variant beats a weak baseline + the gate."""
        # Single-trial-ish low variance so SR* stays small; strong daily drift on the winner.
        cross = cross_config_dsr(_ledger(tmp_path, sharpes=[0.001, 0.0012]))
        results = _block_a_results(
            blend_mu=0.0008, ml_mu=0.012, regime_mu=0.0009, ml_regime_mu=0.001
        )
        winner = select_deflated_winner(results, cross)
        assert winner == "A_ml"

    def test_winner_is_run_order_invariant(self, tmp_path: Path) -> None:
        """B1 / GB1: the deflated winner and per-config gates are identical no matter the
        order configs were RECORDED on the shared ledger.

        We seed the SAME final ledger contents in two different orders; ``cross`` reads
        the final N / V[SR] either way, and the winner must not move."""
        sharpes = [0.001, 0.0012, 0.0009, 0.0011, 0.0008, 0.0013, 0.0007, 0.0014]
        cross_fwd = cross_config_dsr(_ledger(tmp_path / "fwd", sharpes=sharpes))
        cross_rev = cross_config_dsr(_ledger(tmp_path / "rev", sharpes=list(reversed(sharpes))))
        # Same set of recorded Sharpes => identical N and V[SR] => identical SR*.
        assert cross_fwd.n_trials == cross_rev.n_trials
        assert cross_fwd.sr_trials_variance == pytest.approx(cross_rev.sr_trials_variance)
        assert cross_fwd.expected_max_sr == pytest.approx(cross_rev.expected_max_sr)

        results = _block_a_results(
            blend_mu=0.0008, ml_mu=0.012, regime_mu=0.0009, ml_regime_mu=0.001
        )
        winner_fwd = select_deflated_winner(results, cross_fwd)
        winner_rev = select_deflated_winner(results, cross_rev)
        assert winner_fwd == winner_rev

    def test_winner_ignores_flattering_runtime_dsr(self, tmp_path: Path) -> None:
        """The decoy ``validation.dsr=0.99`` on a weak variant must NOT make it a winner —
        only the re-deflated DSR (computed from the OOS curve vs the shared SR*) decides."""
        # Large N + meaningful V[SR] -> a high SR* that a weak curve cannot clear.
        cross = cross_config_dsr(
            _ledger(tmp_path, sharpes=[0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40])
        )
        results = _block_a_results(
            blend_mu=0.0002, ml_mu=0.0003, regime_mu=0.00025, ml_regime_mu=0.00028
        )
        # Despite runtime_dsr=0.99 on every gated variant, none clears the honest SR*.
        assert select_deflated_winner(results, cross) is None


# --------------------------------------------------------------------------- build_matrix_rows


class TestBuildMatrixRows:
    def test_rows_use_redeflated_dsr_and_correct_field_sources(self, tmp_path: Path) -> None:
        cross = cross_config_dsr(_ledger(tmp_path, sharpes=[0.01, 0.02, 0.03, 0.04]))
        configs = reference_matrix()[:4]  # Block A
        results = _block_a_results(
            blend_mu=0.0006, ml_mu=0.0009, regime_mu=0.0007, ml_regime_mu=0.0008
        )
        rows = build_matrix_rows(configs, results, cross)
        assert [r.config_id for r in rows] == ["A_blend", "A_ml", "A_regime", "A_ml_regime"]
        by_id = {r.config_id: r for r in rows}

        # runtime_dsr is preserved as an audit field; dsr is the re-deflated value (differs).
        assert by_id["A_ml"].runtime_dsr == pytest.approx(0.99)
        assert by_id["A_ml"].dsr != pytest.approx(0.99)

        # sr_ann is from validation; max_dd >= 0; turnover finite (B2/GB4 sourcing).
        for r in rows:
            assert math.isfinite(r.sr_ann)
            assert r.max_dd >= 0.0
            assert math.isfinite(r.turnover)

        # Gated A-variants carry the (re-deflated A_blend) baseline_dsr; A_blend does not.
        assert by_id["A_blend"].baseline_dsr is None
        assert by_id["A_ml"].baseline_dsr is not None
        # All four Block-A configs are distinct trials.
        assert all(r.is_distinct_trial for r in rows)

    def test_capacity_rows_are_not_distinct_trials(self, tmp_path: Path) -> None:
        cross = cross_config_dsr(_ledger(tmp_path, sharpes=[0.01, 0.02]))
        winner = next(c for c in reference_matrix() if c.config_id == "A_regime")
        cap = next(c for c in reference_matrix(best_variant=winner) if c.config_id == "B_cap_10M")
        results = {"B_cap_10M": _result(mu=0.0002, seed=5, cash=1e7, runtime_dsr=0.2, sr_ann=0.2)}
        rows = build_matrix_rows([cap], results, cross)
        assert rows[0].is_distinct_trial is False
        assert rows[0].baseline_dsr is None  # not a gated A-variant
        assert rows[0].clears_baseline_gate is False

    def test_matrix_row_json_normalizes_non_finite(self) -> None:
        row = MatrixRow(
            config_id="X",
            block="A",
            knobs={},
            psr=math.nan,
            dsr=math.inf,
            runtime_dsr=0.5,
            sr_ann=math.nan,
            max_dd=0.3,
            turnover=math.nan,
            clears_dsr_gate=False,
            clears_baseline_gate=False,
            is_distinct_trial=True,
            baseline_dsr=None,
        )
        obj = row.to_json_obj()
        assert obj["psr"] is None
        assert obj["dsr"] is None
        assert obj["sr_ann"] is None
        assert obj["turnover"] is None
        assert obj["baseline_dsr"] is None
        json.dumps(obj)  # JSON-safe


# --------------------------------------------------------------------------- writers


class TestWriters:
    def _full_artifacts(self, tmp_path: Path):  # type: ignore[no-untyped-def]
        cross = cross_config_dsr(
            _ledger(tmp_path, sharpes=[0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08])
        )
        winner_cfg = next(c for c in reference_matrix() if c.config_id == "A_regime")
        configs = reference_matrix(best_variant=winner_cfg)
        a = _block_a_results(blend_mu=0.0006, ml_mu=0.0009, regime_mu=0.0007, ml_regime_mu=0.0008)
        c = {
            "C_rebal24": _result(mu=0.0005, seed=200, runtime_dsr=0.3, sr_ann=0.4),
            "C_band10": _result(mu=0.0004, seed=201, runtime_dsr=0.2, sr_ann=0.3),
            "C_mvo": _result(mu=0.00045, seed=202, runtime_dsr=0.25, sr_ann=0.35),
            "C_carry": _result(mu=0.0003, seed=203, runtime_dsr=0.15, sr_ann=0.25),
        }
        b = {
            "B_cap_100k": _result(mu=0.0007, seed=300, cash=1e5, runtime_dsr=0.3, sr_ann=0.45),
            "B_cap_1M": _result(mu=0.0007, seed=301, cash=1e6, runtime_dsr=0.3, sr_ann=0.42),
            "B_cap_10M": _result(mu=0.0004, seed=302, cash=1e7, runtime_dsr=0.2, sr_ann=0.25),
            "B_cap_100M": _result(mu=0.0001, seed=303, cash=1e8, runtime_dsr=0.1, sr_ann=0.05),
        }
        results = {**a, **b, **c}
        variant_ids = [cfg.config_id for cfg in configs if cfg.is_distinct_trial]
        pbo = matrix_pbo(results, variant_ids, n_splits=4, max_combinations=50)
        cap = capacity_curve(results, ["B_cap_100k", "B_cap_1M", "B_cap_10M", "B_cap_100M"], cross)
        winner = select_deflated_winner(results, cross)
        rows = build_matrix_rows(configs, results, cross)
        return configs, results, cross, pbo, cap, winner, rows

    def test_write_matrix_json_schema(self, tmp_path: Path) -> None:
        _, _, cross, pbo, cap, winner, rows = self._full_artifacts(tmp_path)
        out = tmp_path / "matrix.json"
        window = (_T0, _T0 + 365 * _DAY * 5)
        write_matrix_json(
            out,
            rows=rows,
            cross=cross,
            pbo=pbo,
            capacity=cap,
            winner=winner,
            window=window,
            run_ts="20260616T000000Z",
            git_sha="abc1234",
        )
        obj = json.loads(out.read_text())
        assert obj["schema_version"] == SCHEMA_VERSION
        assert obj["run_ts"] == "20260616T000000Z"
        assert obj["git_sha"] == "abc1234"
        assert obj["window"]["start_iso"] == "2021-01-01"
        m = obj["matrix"]
        assert m["n_trials"] == 8
        assert set(m) == {
            "n_trials",
            "sr_trials_variance",
            "expected_max_sr",
            "pbo",
            "pbo_n_combinations",
            "pbo_n_configs",
            "pbo_n_obs",
            "clears_pbo_gate",
            "deflated_winner",
            "deployment_verdict",
        }
        # deployment_verdict is the strict conjunction.
        assert m["deployment_verdict"] == (
            m["deflated_winner"] is not None and m["clears_pbo_gate"]
        )
        # Per-config rows carry both the judged dsr and the audit runtime_dsr.
        a_ml = next(r for r in obj["configs"] if r["config_id"] == "A_ml")
        assert "runtime_dsr" in a_ml
        assert a_ml["is_distinct_trial"] is True
        b_cap = next(r for r in obj["configs"] if r["config_id"] == "B_cap_10M")
        assert b_cap["is_distinct_trial"] is False
        assert len(obj["capacity_curve"]) == 4

    def test_write_matrix_json_is_atomic_and_sorted(self, tmp_path: Path) -> None:
        _, _, cross, pbo, cap, winner, rows = self._full_artifacts(tmp_path)
        out = tmp_path / "matrix.json"
        write_matrix_json(
            out,
            rows=rows,
            cross=cross,
            pbo=pbo,
            capacity=cap,
            winner=winner,
            window=(_T0, _T0 + _DAY * 100),
            run_ts="ts",
        )
        # No leftover temp files in the dir.
        assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".matrix.json")] == []
        text = out.read_text()
        # sorted keys: schema_version is alphabetically late but configs/capacity_curve come first.
        assert text.index('"capacity_curve"') < text.index('"schema_version"')

    def test_write_verdict_states_full_table_and_verdict(self, tmp_path: Path) -> None:
        _, _, cross, pbo, cap, winner, rows = self._full_artifacts(tmp_path)
        out = tmp_path / "verdict.md"
        write_verdict(
            out,
            rows=rows,
            cross=cross,
            pbo=pbo,
            capacity=cap,
            winner=winner,
            window=(_T0, _T0 + 365 * _DAY * 5),
        )
        md = out.read_text()
        # Every Block-A variant is shown (no cherry-picking).
        for cid in ("A_blend", "A_ml", "A_regime", "A_ml_regime"):
            assert cid in md
        assert "Deployment verdict" in md
        assert "Capacity curve" in md
        assert "regime gate" in md.lower()
        # The deflation context is reported.
        assert f"honest N): **{cross.n_trials}**" in md

    def test_write_verdict_null_result_is_stated_plainly(self, tmp_path: Path) -> None:
        cross = cross_config_dsr(
            _ledger(tmp_path, sharpes=[0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40])
        )
        results = _block_a_results(
            blend_mu=0.0002, ml_mu=0.0003, regime_mu=0.00025, ml_regime_mu=0.00028
        )
        configs = reference_matrix()[:4]
        rows = build_matrix_rows(configs, results, cross)
        winner = select_deflated_winner(results, cross)
        assert winner is None
        pbo = matrix_pbo(
            results,
            ["A_blend", "A_ml", "A_regime", "A_ml_regime"],
            n_splits=4,
            max_combinations=50,
        )
        out = tmp_path / "verdict.md"
        write_verdict(
            out,
            rows=rows,
            cross=cross,
            pbo=pbo,
            capacity=(),
            winner=None,
            window=(_T0, _T0 + 365 * _DAY * 5),
        )
        md = out.read_text()
        assert "NO-DEPLOY (honest null)" in md
        assert "Phase-10" in md
        assert "noise" in md.lower()


class TestCapacityPointDataclass:
    def test_is_frozen(self) -> None:
        p = CapacityPoint(
            initial_cash=1e6, sr_ann=0.4, max_dd=0.3, turnover=12.0, dsr=0.2, final_equity=1.1e6
        )
        with pytest.raises((AttributeError, TypeError)):
            p.sr_ann = 0.5  # type: ignore[misc]


def test_daily_returns_empty_for_short_curve() -> None:
    """Guard the validation-None / short-curve edge (N4): a < 2-day curve -> empty rets."""
    short = _equity(n_days=1, mu=0.0, sigma=0.01, seed=1).iloc[:5]
    assert len(daily_returns(short)) < 2
