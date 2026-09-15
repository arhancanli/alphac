"""The batch seal derives every admission figure from sealed outputs and never invents one.

WHY. crypto_carry_portable_v1 closed INCOMPLETE because most of the contract's gates were
"not evaluated". The seal must produce a document the contract's evaluator can decide in
full, the capacity curve must reconcile to the scenarios the reservation declared, an
execution scenario passes only under the pre-registered rule, the DATA-ESCALATE rule turns a
passing result with any force-flat into INCOMPLETE rather than ADMIT, and the bootstrap lower
bound must sit at or below the point estimate. Every number in the overlay block is read from
its source, never typed.

Pure: synthetic frames and dicts; reads only the shipped contract and promotion record.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from alphaforge.validation.sleeve_admission import load_admission_contract

REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "seal_earnings_narrative_change_batch",
    REPO / "scripts" / "seal_earnings_narrative_change_batch.py",
)
assert _SPEC is not None and _SPEC.loader is not None
MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(MOD)

RULE = {"statistic": "net.annualized_sharpe", "operator": ">=", "threshold": 0.40}


def _scenario(
    scenario_id: str, sharpe: float | None, gross: float = 1.0, cost: float = 5.0
) -> dict[str, Any]:
    result = {
        "net": {"annualized_sharpe": sharpe},
        "mean_stock_gross": gross,
        "cost_drag_bps_per_turnover": cost,
    }
    assumptions = {"scenario": scenario_id, "capital_usd": 1.0}
    return {
        "scenario_id": scenario_id,
        "assumptions": assumptions,
        "assumptions_sha256": MOD.canonical_sha256(assumptions),
        "result": result,
        "result_sha256": MOD.canonical_sha256(result),
        "primary_decision_path_sha256": "0" * 64,
    }


def test_capacity_curve_reconciles_to_the_declared_scenarios() -> None:
    diagnostics = {
        "diagnostic_scenarios": {
            "capacity_scenarios": [
                {
                    **_scenario("cap_25m", 0.30, gross=0.80, cost=12.0),
                    "assumptions": {"capital_usd": 25e6},
                },
                {
                    **_scenario("cap_500k", 0.90, gross=1.00, cost=4.0),
                    "assumptions": {"capital_usd": 5e5},
                },
                {
                    **_scenario("cap_5m", 0.70, gross=0.97, cost=6.0),
                    "assumptions": {"capital_usd": 5e6},
                },
            ]
        }
    }
    curve = MOD.capacity_curve(diagnostics, baseline_gross=1.0)
    assert [p["capital_usd"] for p in curve] == [5e5, 5e6, 25e6]
    assert curve[2]["fill_ratio"] == pytest.approx(0.80)
    contract = load_admission_contract(MOD.CONTRACT)
    capacity = MOD.capacity_evidence(curve, contract["thresholds"])
    assert capacity["capacity_usd"] == 5e6  # 25m fails the 0.95 fill floor
    assert capacity["minimum_stressed_fill_ratio"] == pytest.approx(0.97)


def test_execution_scenarios_pass_only_under_the_preregistered_rule() -> None:
    diagnostics = {
        "execution_dimensions": {
            "commissions": [_scenario("c1", 0.41), _scenario("c2", 0.40), _scenario("c3", 0.39)],
            "slippage": [_scenario("s1", None), _scenario("s2", 0.9), _scenario("s3", 0.9)],
        }
    }
    reservation = {
        "full_evidence": {
            "execution_evidence": {
                "not_applicable_dimensions": {
                    "borrow_cost": {
                        "reason": "long/short equity is beta hedged with SPY",
                        "evidence_path": "x",
                        "evidence_sha256": "f" * 64,
                    }
                }
            }
        }
    }
    out = MOD.execution_evidence(diagnostics, reservation, RULE)
    assert out["commissions"]["status"] == "TESTED_FAIL"
    assert [m["status"] for m in out["commissions"]["scenario_manifest"]] == [
        "PASS",
        "PASS",
        "FAIL",
    ]
    assert out["slippage"]["status"] == "TESTED_FAIL"  # a scenario with no Sharpe cannot pass
    assert out["borrow_cost"]["status"] == "NOT_APPLICABLE"
    manifest = out["commissions"]["scenario_manifest"]
    assert out["commissions"]["evidence_sha256"] == MOD.canonical_sha256(manifest)
    for entry in manifest:
        assert entry["result"]["passed"] == (entry["status"] == "PASS")
        assert entry["result_sha256"] == MOD.canonical_sha256(entry["result"])


def test_the_bootstrap_lower_bound_sits_at_or_below_the_point_estimate() -> None:
    rng = np.random.default_rng(7)
    n = 800
    aligned = pd.DataFrame(
        {"book": rng.normal(0.0004, 0.006, n), "candidate": rng.normal(0.0006, 0.008, n)},
        index=pd.date_range("2020-01-01", periods=n, freq="D").date,
    )
    out = MOD.book_sharpe_delta_lower_95(aligned, 0.2, samples=400, block=63, seed=1)
    assert out["lower_95"] <= out["point"]
    assert out["samples"] == 400 and out["block_size"] == 63


def test_the_deployment_overlay_is_read_from_its_sources_and_names_the_gap() -> None:
    contract = load_admission_contract(MOD.CONTRACT)
    overlay = MOD.deployment_overlay(contract)
    thresholds = contract["thresholds"]
    assert overlay["covariance_halflife_days"] == thresholds["covariance_halflife_days_max"]
    assert overlay["realized_vol_halflife_days"] <= thresholds["realized_vol_halflife_days_max"]
    assert overlay["realized_vol_leg_is_unlevered"] is True
    assert overlay["production_today"]["covariance_halflife"] == 720
    assert "live-configuration change" in overlay["deployment_condition"]
    values = pd.Series(np.random.default_rng(3).normal(0.0003, 0.01, 600))
    replay = MOD.overlay_replay(values, overlay)
    assert replay["max_leverage"] <= overlay["vol_scale_max"] + 1e-12
    assert replay["sessions"] == 600


def test_the_evidence_document_is_decidable_by_the_contract_in_full() -> None:
    """Every field the evaluator reads is present: a synthetic passing document is ADMIT-shaped,
    and dropping the book-level lower bound is caught by name."""
    contract = load_admission_contract(MOD.CONTRACT)
    evidence = _passing_document(contract)
    report = MOD.evaluate_sleeve_evidence(evidence, contract)
    assert report.failures == (), report.failures
    assert report.checks_evaluated == contract["evidence_checks_per_candidate"]
    evidence["portfolio"]["book_sharpe_delta_lower_95"] = -0.01
    report = MOD.evaluate_sleeve_evidence(evidence, contract)
    assert any("book_sharpe_delta_lower_95" in f for f in report.failures)


def _passing_document(contract: dict[str, Any]) -> dict[str, Any]:
    thresholds = contract["thresholds"]
    curve = [
        {"capital_usd": 5e5, "net_sharpe": 1.0, "fill_ratio": 1.0, "stressed_cost_bps": 4.0},
        {"capital_usd": 5e6, "net_sharpe": 0.9, "fill_ratio": 0.98, "stressed_cost_bps": 6.0},
        {"capital_usd": 25e6, "net_sharpe": 0.5, "fill_ratio": 0.90, "stressed_cost_bps": 12.0},
    ]
    execution: dict[str, Any] = {}
    for dimension in contract["execution_dimensions"]:
        manifest = []
        for k in range(3):
            assumptions = {"dimension": dimension, "level": k}
            result = {"net": {"annualized_sharpe": 0.8}, "passed": True}
            manifest.append(
                {
                    "scenario_id": f"{dimension}_{k}",
                    "status": "PASS",
                    "assumptions": assumptions,
                    "assumptions_sha256": MOD.canonical_sha256(assumptions),
                    "result": result,
                    "result_sha256": MOD.canonical_sha256(result),
                }
            )
        execution[dimension] = {
            "status": "TESTED_PASS",
            "scenarios": 3,
            "scenario_manifest": manifest,
            "evidence_sha256": MOD.canonical_sha256(manifest),
        }
    return {
        "lineage": {
            "preregistration_sha256": "a" * 64,
            "data_manifest_sha256": "b" * 64,
            "diversification_report_sha256": "c" * 64,
            "code_commit": "d" * 40,
            "family_trial_account": "equity_narrative_change",
            "return_identity_id": "earnings_narrative_change_v1",
            "point_in_time_data": True,
            "survivorship_control": True,
            "corporate_action_control": True,
            "direction_locked": True,
            "parameters_locked": True,
        },
        "robustness": dict.fromkeys(contract["required_robustness"], True),
        "statistics": {
            "oos_observations": 2400,
            "stressed_oos_observations": 240,
            "net_sharpe": 1.0,
            "stressed_sharpe": 0.8,
            "newey_west_t": 3.0,
            "deflated_sharpe": 0.9,
            "book_deflated_sharpe": 0.95,
            "pbo": {"status": "MEASURED", "value": 0.1},
        },
        "diversification": {
            "absolute_beta": 0.02,
            "max_pairwise_correlation": 0.05,
            "max_stressed_pairwise_correlation": 0.10,
            "max_pairwise_correlation_upper_95": 0.10,
            "max_stressed_pairwise_correlation_upper_95": 0.20,
            "average_pairwise_correlation": -0.01,
            "average_pairwise_correlation_upper_95": 0.05,
            "candidate_average_correlation_to_existing_book": -0.02,
            "book_average_pairwise_correlation_delta": -0.001,
            "correlation_observations": 2400,
        },
        "portfolio": {
            "book_sharpe_delta": 0.05,
            "book_sharpe_delta_lower_95": 0.01,
            "minimum_leave_one_period_out_book_sharpe_delta": 0.01,
            "book_max_drawdown_delta": -0.001,
            "book_expected_shortfall_delta": -0.0001,
            "book_expected_max_drawdown": 0.09,
        },
        "capacity": MOD.capacity_evidence(curve, thresholds),
        "overlay": {
            "covariance_halflife_days": 21,
            "realized_vol_halflife_days": 240,
            "realized_vol_leg_is_unlevered": True,
        },
        "execution": execution,
    }


# ---------------------------------------------------------------- the deterministic re-run
#
# WHY. The seal once accepted --skip-rerun; the evaluator would have read the resulting False as
# not_passed:robustness.deterministic_rerun and closed the identity KILL, which is final. And a
# re-run through run() writes the curve, cohorts and manifest beside the result, so a re-run into
# the sealed directory would overwrite the record it is checking. The re-run is therefore
# mandatory, deferred, into a scratch directory, and authorized by the sealed result itself
# rather than by re-validating a reservation whose identity is already logged.


class _FakeRunner:
    def __init__(self, series: np.ndarray) -> None:
        self.series = series
        self.calls: list[dict[str, Any]] = []

    def run(self, window: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"window": window, **kwargs})
        out = kwargs["out_root"] / window
        out.mkdir(parents=True)
        (out / "curve.parquet").write_bytes(b"scratch")
        return {"net_returns": pd.Series(self.series)}


def test_the_rerun_is_deferred_into_a_scratch_directory_and_compared_by_hash(
    tmp_path: Path,
) -> None:
    series = np.array([0.001, -0.002, 0.0005])
    runner = _FakeRunner(series)
    sealed_dir = tmp_path / "sealed" / "oos"
    sealed_dir.mkdir(parents=True)
    result_path = sealed_dir / "result.json"
    result_path.write_text("{}")
    out = MOD.deterministic_rerun(
        runner,
        section="item1a",
        reservation_path=tmp_path / "reservation.json",
        result_path=result_path,
        sealed_series=series,
    )
    assert out["performed"] is True and out["reproduced"] is True
    call = runner.calls[0]
    assert call["defer_result"] is True
    assert call["rerun_of"] == result_path
    assert call["out_root"] != sealed_dir.parent and not call["out_root"].exists()  # removed
    assert (sealed_dir / "result.json").read_text() == "{}"
    # Summation-order noise (the seventeenth digit) is the same series; a real divergence is not.
    runner_noise = _FakeRunner(series * (1.0 + 1e-15))
    out = MOD.deterministic_rerun(
        runner_noise,
        section="item1a",
        reservation_path=tmp_path / "reservation.json",
        result_path=result_path,
        sealed_series=series,
    )
    assert out["reproduced"] is True and out["exact_hash_match"] is False
    assert 0.0 < out["max_abs_difference"] <= out["tolerance_abs"]
    runner_diverging = _FakeRunner(series + 1e-9)
    out = MOD.deterministic_rerun(
        runner_diverging,
        section="item1a",
        reservation_path=tmp_path / "reservation.json",
        result_path=result_path,
        sealed_series=series,
    )
    assert out["reproduced"] is False and out["max_abs_difference"] > out["tolerance_abs"]
    runner_short = _FakeRunner(series[:-1])
    out = MOD.deterministic_rerun(
        runner_short,
        section="item1a",
        reservation_path=tmp_path / "reservation.json",
        result_path=result_path,
        sealed_series=series,
    )
    assert out["reproduced"] is False and out["max_abs_difference"] is None


def test_the_seal_has_no_way_to_skip_the_rerun() -> None:
    import inspect

    assert "do_rerun" not in inspect.signature(MOD.seal_identity).parameters
    assert (
        "skip"
        not in (REPO / "scripts" / "seal_earnings_narrative_change_batch.py")
        .read_text()
        .split("def main")[1]
    )


def test_rerun_authorization_binds_the_sealed_result_and_refuses_the_sealed_directory(
    tmp_path: Path,
) -> None:
    runner_spec = importlib.util.spec_from_file_location(
        "narrative_runner_for_rerun_test", REPO / "scripts" / "run_earnings_narrative_change_v1.py"
    )
    assert runner_spec is not None and runner_spec.loader is not None
    runner = importlib.util.module_from_spec(runner_spec)
    runner_spec.loader.exec_module(runner)
    reservation = tmp_path / "return_identity_reservation.json"
    reservation.write_text('{"hypothesis_identity": "abc"}')
    sealed_dir = tmp_path / "artifacts" / "oos"
    sealed_dir.mkdir(parents=True)
    result = {
        "section": "item1a",
        "authorization": {
            "reservation_sha256": hashlib.sha256(reservation.read_bytes()).hexdigest()
        },
    }
    result["content_hash"] = runner._content_hash(result)
    result_path = sealed_dir / "result.json"
    result_path.write_text(json.dumps(result))
    scratch = tmp_path / "scratch"
    authorization = runner.rerun_authorization("item1a", reservation, result_path, out_root=scratch)
    assert authorization["rerun_of_content_hash"] == result["content_hash"]
    with pytest.raises(SystemExit, match="fresh out_root"):
        runner.rerun_authorization("item1a", reservation, result_path, out_root=sealed_dir.parent)
    with pytest.raises(SystemExit, match="fresh out_root"):
        runner.rerun_authorization("item1a", reservation, result_path, out_root=None)
    with pytest.raises(SystemExit, match="not 'item7'"):
        runner.rerun_authorization("item7", reservation, result_path, out_root=scratch)
    reservation.write_text('{"hypothesis_identity": "abc", "edited": true}')
    with pytest.raises(SystemExit, match="reservation moved"):
        runner.rerun_authorization("item1a", reservation, result_path, out_root=scratch)
    with pytest.raises(SystemExit, match="always deferred"):
        runner.run(
            "oos",
            section="item1a",
            max_cohorts=None,
            reservation=reservation,
            out_root=scratch,
            rerun_of=result_path,
        )
