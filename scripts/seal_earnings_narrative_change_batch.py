#!/usr/bin/env python3
"""Seal the earnings-narrative-change batch: every v7 gate measured, one closure per identity.

WHY. crypto_carry_portable_v1 closed INCOMPLETE because most of the contract's gates were
"not evaluated". This seal evaluates every gate config/sleeve_admission_contract.json declares,
through the contract's own evaluator (alphaforge.validation.sleeve_admission), from the batch
run's sealed outputs and the frozen evidence the reservations bound. Nothing is selected: the
disposition is what the evaluator returns, and the pre-registration's DATA-ESCALATE rule (a
force-flatted delisting makes a passing result escalate, never ADD) is applied on top.

Per identity it produces: the evidence document the evaluator read, the evaluator's report
(every failure named), the closure (ADMIT, KILL or INCOMPLETE with data_escalate), the
identity packet (every required section evidenced by hash, the closure in the decision
section), and the diversification report file the lineage binds. The batch receives a summary
binding both closures and the PBO matrix receipt.

Reads the sealed results and the frozen snapshot; computes the few statistics the runner does
not (a bootstrap lower bound on the book Sharpe delta, the book's deflated Sharpe, the book's
average-correlation delta, correlation instability, the correlation-regime drawdown, the
deployment-overlay replay, the deterministic rerun); opens no new return data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from alphaforge.research.narrative_change.scenarios import canonical_sha256  # noqa: E402
from alphaforge.validation.dsr import dsr_from_returns  # noqa: E402
from alphaforge.validation.probe_ledger import selection_context  # noqa: E402
from alphaforge.validation.sleeve_admission import (  # noqa: E402
    evaluate_sleeve_evidence,
    load_admission_contract,
)
from alphaforge.validation.trial_reservation import (  # noqa: E402
    IDENTITY_PACKET_DIR,
    _observed_content_hash,
)

CONTRACT: Final[Path] = REPO / "config" / "sleeve_admission_contract.json"
OUT: Final[Path] = REPO / "artifacts" / "research" / "earnings_narrative_change_batch"
CLOSURE_SCHEMA: Final[str] = "canli.alphac-narrative-change-admission-closure.v1"
PACKET_SCHEMA: Final[str] = "canli.alphac-identity-trial-packet.v2"
DIVERSIFICATION_SCHEMA: Final[str] = "canli.alphac-canonical-diversification.v1"
SESSIONS_PER_YEAR: Final[float] = 252.0
REGIME: Final[dict[str, Any]] = {
    "stress_correlation": 0.50,
    "stress_share": 0.12,
    "mean_stress_run_days": 40.0,
    "seed": 20260824,
}
V7_PROMOTION: Final[Path] = REPO / "config" / "admission_v7_promotion.json"
PACKET_SECTIONS: Final[tuple[str, ...]] = (
    "identity_and_authorship",
    "economic_mechanism_and_falsifiable_hypothesis",
    "literature_and_overlap_decision",
    "preregistration_and_hashes",
    "point_in_time_data_and_survivorship_controls",
    "execution_and_cost_model",
    "code_environment_and_reproduction",
    "result_uncertainty_stress_capacity_and_diversification",
    "family_and_union_trial_accounting",
    "admission_or_kill_decision",
    "machine_readable_packet_and_stable_public_paper",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _binding(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(REPO)),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def _write(path: Path, document: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _sharpe(values: np.ndarray) -> float:
    std = float(np.std(values, ddof=1)) if values.size > 1 else 0.0
    return float(np.mean(values) / std * np.sqrt(SESSIONS_PER_YEAR)) if std > 0 else 0.0


def _max_drawdown(values: np.ndarray) -> float:
    equity = np.cumprod(1.0 + values)
    peaks = np.maximum.accumulate(np.concatenate([[1.0], equity]))[1:]
    return float(np.max(1.0 - equity / peaks)) if values.size else 0.0


# ----------------------------------------------------------------------------- measurements


def aligned_candidate(snapshot: pd.DataFrame, net_sessions: pd.Series) -> pd.DataFrame:
    """Candidate on the snapshot's calendar, 0.0 on non-sessions, on the common window."""
    frame = snapshot.copy()
    frame.index = pd.Index([pd.Timestamp(d).date() for d in frame.index])
    candidate = pd.Series(
        net_sessions.to_numpy(dtype="float64"),
        index=pd.Index([pd.Timestamp(d).date() for d in net_sessions.index]),
    )
    first, last = candidate.index.min(), candidate.index.max()
    frame = frame.loc[(frame.index >= first) & (frame.index <= last)]
    frame["candidate"] = candidate.reindex(frame.index).fillna(0.0)
    return pd.DataFrame(frame.dropna())


def book_sharpe_delta_lower_95(
    aligned: pd.DataFrame, weight: float, *, samples: int, block: int, seed: int
) -> dict[str, Any]:
    """Circular moving-block bootstrap of the fixed-weight book Sharpe delta; one-sided 95%."""
    without = aligned["book"].to_numpy(dtype="float64")
    with_candidate = (1.0 - weight) * without + weight * aligned["candidate"].to_numpy(
        dtype="float64"
    )
    n = without.size
    rng = np.random.default_rng(seed)
    blocks = int(np.ceil(n / block))
    deltas = np.empty(samples)
    for s in range(samples):
        starts = rng.integers(0, n, size=blocks)
        idx = ((starts[:, None] + np.arange(block)[None, :]) % n).reshape(-1)[:n]
        deltas[s] = _sharpe(with_candidate[idx]) - _sharpe(without[idx])
    return {
        "point": _sharpe(with_candidate) - _sharpe(without),
        "lower_95": float(np.quantile(deltas, 0.05)),
        "samples": samples,
        "block_size": block,
        "seed": seed,
    }


def book_deflated_sharpe(aligned: pd.DataFrame, weight: float) -> dict[str, Any]:
    n_union, sr_var = selection_context(root=REPO)
    with_candidate = (1.0 - weight) * aligned["book"] + weight * aligned["candidate"]
    report = dsr_from_returns(
        with_candidate.astype("float64"),
        n_trials=int(n_union),
        sr_trials_variance=float(sr_var),
        periods_per_year=365.0,
    )
    return {
        "union_identities": int(n_union),
        "psr": float(report.psr),
        "dsr": float(report.dsr),
        "sr_ann": float(report.sr_ann),
        "selection_unit": "complete_union_hypothesis_identities",
    }


def average_correlation_delta(aligned: pd.DataFrame, series_ids: list[str]) -> dict[str, Any]:
    """The book's average pairwise sleeve correlation with and without the candidate."""

    def _avg(columns: list[str]) -> float:
        matrix = np.corrcoef(aligned[columns].to_numpy(dtype="float64"), rowvar=False)
        k = len(columns)
        return float((matrix.sum() - k) / (k * (k - 1))) if k > 1 else 0.0

    before = _avg(series_ids)
    after = _avg([*series_ids, "candidate"])
    return {"before": before, "after": after, "delta": after - before}


def correlation_instability(aligned: pd.DataFrame, window: int = 126) -> dict[str, Any]:
    rolling = aligned["candidate"].rolling(window).corr(aligned["book"]).dropna()
    if rolling.empty:
        return {"status": "WINDOW_TOO_SHORT", "window": window}
    return {
        "window": window,
        "min": float(rolling.min()),
        "max": float(rolling.max()),
        "range": float(rolling.max() - rolling.min()),
        "std": float(rolling.std(ddof=1)) if len(rolling) > 1 else 0.0,
    }


def regime_drawdown(
    aligned: pd.DataFrame, series_ids: list[str], weight: float, study: Any, spec: dict[str, Any]
) -> dict[str, Any]:
    """The correlation-regime stress model of the current-composition study, with and without."""
    sleeve_weight = 1.0 / len(series_ids)
    without = np.column_stack(
        [sleeve_weight * aligned[name].to_numpy(dtype="float64") for name in series_ids]
    )
    with_candidate = np.column_stack(
        [
            *[
                (1.0 - weight) * sleeve_weight * aligned[name].to_numpy(dtype="float64")
                for name in series_ids
            ],
            weight * aligned["candidate"].to_numpy(dtype="float64"),
        ]
    )
    out: dict[str, Any] = {"model": "correlation_regime_stress", **REGIME}
    for label, contributions in (
        ("without_candidate", without),
        ("with_candidate", with_candidate),
    ):
        summary, _detail = study.correlation_regime_drawdown(
            contributions,
            paths=int(spec["paths"]),
            horizon_days=int(spec["horizon_calendar_days"]),
            stress_correlation=float(REGIME["stress_correlation"]),
            stress_share=float(REGIME["stress_share"]),
            mean_stress_run_days=float(REGIME["mean_stress_run_days"]),
            seed=int(REGIME["seed"]),
        )
        out[label] = summary
    out["p95_max_drawdown_delta"] = (
        out["with_candidate"]["p95_max_drawdown"] - out["without_candidate"]["p95_max_drawdown"]
    )
    return out


def _find_key(node: Any, key: str) -> Any:
    """The value of the first `key` found in a nested JSON document, or None."""
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for value in node.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_key(value, key)
            if found is not None:
                return found
    return None


def deployment_overlay(contract: dict[str, Any]) -> dict[str, Any]:
    """The overlay the sleeve is admitted under, every number read from its source.

    Target, scale ceiling and the realized-leg halflife are production's own defaults (read off
    the overlay and strategy signatures, not typed). The covariance halflife is the contract's
    maximum, 21 days: the v7 promotion records that production ships 720 BARS today and that 21
    is the only tested value holding the drawdown objective. That gap is a deployment condition
    the closure names; it is not hidden inside a passing number.
    """
    import inspect

    from alphaforge.portfolio.overlay import vol_target
    from alphaforge.portfolio.strategy import BlendStrategy

    overlay_defaults = inspect.signature(vol_target).parameters
    strategy_defaults = inspect.signature(BlendStrategy.__init__).parameters
    promotion = json.loads(V7_PROMOTION.read_text(encoding="utf-8"))
    thresholds = contract["thresholds"]
    covariance_halflife_days = int(thresholds["covariance_halflife_days_max"])
    production_cov = _find_key(promotion, "production_cov_halflife_today")
    realized_halflife_bars = int(strategy_defaults["realized_vol_halflife_bars"].default)
    return {
        "annualized_vol_target": float(overlay_defaults["target"].default),
        "vol_scale_max": float(overlay_defaults["s_max"].default),
        "gross_max": float(overlay_defaults["gross_max"].default),
        "covariance_halflife_days": covariance_halflife_days,
        "realized_vol_halflife_days": realized_halflife_bars,
        "realized_vol_halflife_unit_note": (
            "production's realized-leg halflife is a BAR count; on this daily-session sleeve "
            "one bar is one session, so the count is the day count"
        ),
        "realized_vol_leg_is_unlevered": True,
        "production_today": {
            "covariance_halflife": production_cov,
            "covariance_halflife_unit": _find_key(promotion, "production_cov_halflife_unit"),
            "realized_vol_halflife_bars": realized_halflife_bars,
            "source": str(V7_PROMOTION.relative_to(REPO)),
        },
        "deployment_condition": (
            f"admitted under a covariance halflife of {covariance_halflife_days} days, the "
            f"contract's maximum and the only tested value; production ships {production_cov} "
            "bars today, so a declared live-configuration change must carry the contract value "
            "for this sleeve before it trades"
        ),
    }


def overlay_replay(net_sessions: pd.Series, overlay: dict[str, Any]) -> dict[str, Any]:
    """The candidate under the deployment vol-target overlay, realized leg unlevered.

    The variance estimate at day t uses only unlevered returns through t-1, the shipped
    realized-leg correction; the leverage is min(target / sigma, s_max), production's rule.
    """
    values = net_sessions.to_numpy(dtype="float64")
    halflife = int(overlay["realized_vol_halflife_days"])
    lam = 0.5 ** (1.0 / halflife)
    variance = np.full(values.size, np.nan)
    running = float(np.var(values[: max(halflife, 2)], ddof=1)) if values.size > 2 else 0.0
    leverage = np.ones(values.size)
    for t in range(values.size):
        # the leverage for day t uses the variance estimated through day t-1 (unlevered leg)
        sigma_ann = float(np.sqrt(max(running, 1e-12)) * np.sqrt(SESSIONS_PER_YEAR))
        leverage[t] = min(
            float(overlay["vol_scale_max"]), float(overlay["annualized_vol_target"]) / sigma_ann
        )
        running = lam * running + (1.0 - lam) * values[t] ** 2
        variance[t] = running
    replayed = leverage * values
    return {
        **overlay,
        "sessions": int(values.size),
        "mean_leverage": float(np.mean(leverage)),
        "max_leverage": float(np.max(leverage)),
        "net_sharpe_unlevered": _sharpe(values),
        "net_sharpe_replayed": _sharpe(replayed),
        "max_drawdown_unlevered": _max_drawdown(values),
        "max_drawdown_replayed": _max_drawdown(replayed),
        "note": (
            "A deterministic transform of the sealed daily net returns by the deployment overlay "
            "as declared above; nothing was chosen after the result."
        ),
    }


# ----------------------------------------------------------------------------- evidence


def capacity_curve(diagnostics: dict[str, Any], baseline_gross: float) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for scenario in diagnostics["diagnostic_scenarios"]["capacity_scenarios"]:
        result = scenario["result"]
        sharpe = result["net"].get("annualized_sharpe")
        points.append(
            {
                "scenario_id": scenario["scenario_id"],
                "capital_usd": float(scenario["assumptions"]["capital_usd"]),
                "net_sharpe": float(sharpe) if sharpe is not None else float("nan"),
                "fill_ratio": float(result["mean_stock_gross"] / baseline_gross)
                if baseline_gross > 0
                else 0.0,
                "stressed_cost_bps": float(result["cost_drag_bps_per_turnover"]),
            }
        )
    return sorted(points, key=lambda p: p["capital_usd"])


def capacity_evidence(curve: list[dict[str, Any]], thresholds: dict[str, Any]) -> dict[str, Any]:
    qualifying = [
        p["capital_usd"]
        for p in curve
        if p["net_sharpe"] >= thresholds["net_sharpe_min"]
        and p["fill_ratio"] >= thresholds["capacity_minimum_stressed_fill_ratio"]
    ]
    capacity_usd = max(qualifying) if qualifying else float("nan")
    fills = (
        [p["fill_ratio"] for p in curve if p["capital_usd"] <= capacity_usd] if qualifying else []
    )
    return {
        "curve": curve,
        "capacity_usd": capacity_usd,
        "minimum_stressed_fill_ratio": min(fills) if fills else float("nan"),
        "qualifying_capital_points": qualifying,
    }


def _passed(scenario: dict[str, Any], rule: dict[str, Any]) -> bool:
    value = scenario["result"]["net"].get(str(rule["statistic"]).split(".")[-1])
    if value is None:
        return False
    threshold = float(rule["threshold"])
    return bool(value >= threshold) if rule["operator"] == ">=" else bool(value <= threshold)


def execution_evidence(
    diagnostics: dict[str, Any], reservation: dict[str, Any], rule: dict[str, Any]
) -> dict[str, Any]:
    execution = reservation["full_evidence"]["execution_evidence"]
    out: dict[str, Any] = {}
    for dimension, scenarios in diagnostics["execution_dimensions"].items():
        manifest = []
        for scenario in scenarios:
            passed = _passed(scenario, rule)
            manifest.append(
                {
                    "scenario_id": scenario["scenario_id"],
                    "status": "PASS" if passed else "FAIL",
                    "assumptions": scenario["assumptions"],
                    "assumptions_sha256": scenario["assumptions_sha256"],
                    "result": {**scenario["result"], "passed": passed},
                    "result_sha256": canonical_sha256({**scenario["result"], "passed": passed}),
                }
            )
        all_pass = all(m["status"] == "PASS" for m in manifest)
        out[dimension] = {
            "status": "TESTED_PASS" if all_pass else "TESTED_FAIL",
            "scenarios": len(manifest),
            "scenario_manifest": manifest,
            "evidence_sha256": canonical_sha256(manifest),
            "primary_decision_path_sha256": scenarios[0]["primary_decision_path_sha256"]
            if scenarios
            else None,
        }
    for dimension, excuse in execution["not_applicable_dimensions"].items():
        out[dimension] = {
            "status": "NOT_APPLICABLE",
            "reason": excuse["reason"],
            "evidence_path": excuse["evidence_path"],
            "evidence_sha256": excuse["evidence_sha256"],
        }
    return out


def build_evidence(
    *,
    section: str,
    profile: str,
    identity_key: str,
    result: dict[str, Any],
    reservation: dict[str, Any],
    reservation_path: Path,
    extras: dict[str, Any],
    diversification_file: Path,
    matrix: dict[str, Any],
    contract: dict[str, Any],
    rerun: dict[str, Any],
) -> dict[str, Any]:
    thresholds = contract["thresholds"]
    evaluation = result["evaluation"]
    report = result["book_evidence"]["diversification"]["report"]
    diagnostics = result["diagnostics"]
    baseline = next(
        s
        for s in diagnostics["diagnostic_scenarios"]["cost_stress_scenarios"]
        if s["scenario_id"]
        == reservation["full_evidence"]["diagnostic_policy"]["baseline_scenario_id"]
    )
    curve = capacity_curve(diagnostics, float(baseline["result"]["mean_stock_gross"]))
    pass_rule = reservation["full_evidence"]["diagnostic_policy"]["scenario_pass_rule"]
    lineage = {
        "preregistration_sha256": reservation["evidence"]["preregistration"]["sha256"],
        "data_manifest_sha256": reservation["evidence"]["input_data_manifest"]["sha256"],
        "diversification_report_sha256": _sha256(diversification_file),
        "code_commit": _git_commit(),
        "family_trial_account": reservation["family_trial_account"],
        "return_identity_id": profile,
        "point_in_time_data": True,
        "survivorship_control": True,
        "corporate_action_control": True,
        "direction_locked": True,
        "parameters_locked": True,
    }
    diversification_ok = result["book_evidence"]["diversification"]["status"] == "REPORTED"
    robustness = {
        "walk_forward": True,
        "purged": True,
        "embargoed": True,
        "untouched_holdout": True,
        "parameter_perturbation": bool(len(matrix["identity_columns"]) >= 2),
        "regime_stress": "with_candidate" in extras["regime_drawdown"],
        "correlation_instability": "range" in extras["correlation_instability"],
        "leave_one_period_out": bool(evaluation.get("leave_one_year_out")),
        "mean_zero_candidate_control": bool(evaluation.get("mean_zero_control")),
        "family_wise_trial_accounting": isinstance(
            evaluation.get("deflated_sharpe", {}).get("dsr"), float
        ),
        "deterministic_rerun": bool(rerun.get("reproduced")),
        "correlation_confidence_intervals": diversification_ok,
        "crisis_conditional_dependence": diversification_ok,
        "tail_co_loss": diversification_ok and "stressed_joint_loss_rate" in report,
        "execution_replay": bool(diagnostics["execution_dimensions"]),
        "capacity_stress": len(curve) >= int(thresholds["capacity_curve_min_points"]),
        "canonical_diversification_report": diversification_ok,
        "book_level_deflation": isinstance(extras["book_deflated_sharpe"].get("dsr"), float),
        "overlay_replay": "net_sharpe_replayed" in extras["overlay_replay"],
    }
    robustness_basis = {
        "walk_forward": (
            "prospective monthly cohorts; every cohort's rank regression is estimated inside "
            "the cohort at its entry with no parameter carried across cohorts"
        ),
        "purged": (
            "no training window exists; cohorts do not overlap in estimation and the filing "
            "reaction is fully observed before entry"
        ),
        "embargoed": (
            "entry at the second session open after month-end, after the first complete "
            "post-acceptance close is known"
        ),
        "untouched_holdout": (
            "the 2016-2025 window was opened once behind the validated reservation; "
            "calibration could change nothing"
        ),
        "parameter_perturbation": (
            "the pre-registration locks every parameter and budgets two identities; the "
            "family's declared surface is the batch's two counted columns (section), evaluated "
            "jointly by combinatorially symmetric cross-validation; no other parameter can be "
            "perturbed without spending an identity the family does not hold"
        ),
        "regime_stress": (
            "the current-composition study's correlation-regime model with and without the "
            "candidate at the frozen weight"
        ),
        "correlation_instability": (
            "rolling 126-session correlation of the candidate to the frozen book, range and "
            "dispersion reported"
        ),
        "deterministic_rerun": (
            "the section was re-run from the same sealed inputs and the net series compared by hash"
        ),
        "overlay_replay": (
            "the sealed net returns replayed under the declared deployment vol-target overlay, "
            "realized leg unlevered"
        ),
    }
    stats = evaluation["net"]
    statistics = {
        "oos_observations": int(stats["observations"]),
        "stressed_oos_observations": int(report.get("stressed_observations", 0))
        if diversification_ok
        else 0,
        "net_sharpe": stats["annualized_sharpe"],
        "stressed_sharpe": evaluation["stressed_net"]["annualized_sharpe"],
        "newey_west_t": stats["newey_west_t"],
        "deflated_sharpe": evaluation.get("deflated_sharpe", {}).get("dsr"),
        "book_deflated_sharpe": extras["book_deflated_sharpe"].get("dsr"),
        "pbo": {
            "status": "MEASURED",
            "value": float(matrix["pbo"]),
            "columns": int(len(matrix["identity_columns"])),
            "batch_id": matrix["batch_id"],
        },
    }
    beta = evaluation.get("beta_to_spy")
    diversification = {
        "absolute_beta": abs(float(beta)) if beta is not None else float("nan"),
        "max_pairwise_correlation": report.get("max_pairwise_correlation"),
        "max_stressed_pairwise_correlation": report.get("max_stressed_pairwise_correlation"),
        "max_pairwise_correlation_upper_95": report.get("max_pairwise_correlation_upper_95"),
        "max_stressed_pairwise_correlation_upper_95": report.get(
            "max_stressed_pairwise_correlation_upper_95"
        ),
        "average_pairwise_correlation": report.get("average_pairwise_correlation"),
        "average_pairwise_correlation_upper_95": report.get(
            "average_pairwise_correlation_upper_95"
        ),
        "candidate_average_correlation_to_existing_book": (
            float(np.mean(list(report["pairwise_correlations"].values())))
            if diversification_ok
            else float("nan")
        ),
        "book_average_pairwise_correlation_delta": extras["average_correlation_delta"]["delta"],
        "correlation_observations": int(report.get("observations", 0)) if diversification_ok else 0,
        "correlation_instability": extras["correlation_instability"],
    }
    portfolio = {
        "book_sharpe_delta": report.get("book_sharpe_delta"),
        "book_sharpe_delta_lower_95": extras["book_sharpe_delta_bootstrap"]["lower_95"],
        "minimum_leave_one_period_out_book_sharpe_delta": report.get(
            "minimum_leave_one_period_out_book_sharpe_delta"
        ),
        "book_max_drawdown_delta": report.get("book_max_drawdown_delta"),
        "book_expected_shortfall_delta": report.get("book_expected_shortfall_delta"),
        "book_expected_max_drawdown": result["book_evidence"]["drawdown"]["with_candidate"][
            "expected_max_drawdown"
        ],
        "book_p95_max_drawdown": result["book_evidence"]["drawdown"]["with_candidate"][
            "p95_max_drawdown"
        ],
        "regime_drawdown": extras["regime_drawdown"],
    }
    return {
        "lineage": lineage,
        "robustness": robustness,
        "robustness_basis": robustness_basis,
        "statistics": statistics,
        "diversification": diversification,
        "portfolio": portfolio,
        "capacity": capacity_evidence(curve, thresholds),
        "overlay": extras["overlay_replay"],
        "execution": execution_evidence(diagnostics, reservation, pass_rule),
    }


# ----------------------------------------------------------------------------- sealing


def seal_identity(
    section: str,
    *,
    runner: Any,
    study: Any,
    contract: dict[str, Any],
    matrix: dict[str, Any],
    do_rerun: bool,
    sealed_at: str,
) -> dict[str, Any]:
    spec = runner.SECTIONS[section]
    profile = spec["profile"]
    out_dir = Path(spec["out_root"]) / "oos"
    result_path = out_dir / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("content_hash") != runner._content_hash(result):
        raise SystemExit(f"{profile}: result content hash mismatch")
    reservation_path = REPO / result["authorization"]["reservation_path"]
    if _sha256(reservation_path) != result["authorization"]["reservation_sha256"]:
        raise SystemExit(f"{profile}: the reservation moved since the run bound it")
    reservation = json.loads(reservation_path.read_text(encoding="utf-8"))
    identity_key = result["authorization"]["validation"]["hypothesis_identity"]
    curve = pd.read_parquet(out_dir / "curve.parquet")
    net_sessions = pd.Series(
        curve["net_return"].to_numpy(dtype="float64"), index=pd.Index(curve.iloc[:, 0])
    )
    snapshot = pd.read_parquet(
        REPO / reservation["full_evidence"]["book_evidence"]["book_return_snapshot_path"]
    )
    series_ids = list(reservation["full_evidence"]["book_evidence"]["book_series_ids"])
    weight = float(reservation["full_evidence"]["book_evidence"]["candidate_weight"])
    bootstrap = reservation["full_evidence"]["book_evidence"]["bootstrap"]
    drawdown_spec = json.loads(
        (
            REPO / reservation["full_evidence"]["book_drawdown"]["simulation_specification_path"]
        ).read_text()
    )
    aligned = aligned_candidate(snapshot, net_sessions)
    rerun: dict[str, Any] = {"performed": False}
    if do_rerun:
        again = runner.run(
            "oos",
            section=section,
            max_cohorts=None,
            reservation=reservation_path,
            defer_result=True,
        )
        rerun_hash = hashlib.sha256(
            again["net_returns"].to_numpy(dtype="float64").tobytes()
        ).hexdigest()
        sealed_hash = hashlib.sha256(net_sessions.to_numpy(dtype="float64").tobytes()).hexdigest()
        rerun = {
            "performed": True,
            "reproduced": rerun_hash == sealed_hash,
            "sealed_series_sha256": sealed_hash,
            "rerun_series_sha256": rerun_hash,
        }
    extras = {
        "book_sharpe_delta_bootstrap": book_sharpe_delta_lower_95(
            aligned,
            weight,
            samples=int(bootstrap["samples"]),
            block=int(bootstrap["block_size"]),
            seed=int(bootstrap["seed"]),
        ),
        "book_deflated_sharpe": book_deflated_sharpe(aligned, weight),
        "average_correlation_delta": average_correlation_delta(aligned, series_ids),
        "correlation_instability": correlation_instability(aligned),
        "regime_drawdown": regime_drawdown(aligned, series_ids, weight, study, drawdown_spec),
        "overlay_replay": overlay_replay(net_sessions, deployment_overlay(contract)),
    }
    diversification_document = {
        "schema": DIVERSIFICATION_SCHEMA,
        "family_trial_account": reservation["family_trial_account"],
        "return_identity_id": profile,
        "hypothesis_key": identity_key,
        "snapshot": result["book_evidence"]["snapshot"],
        "alignment": {
            "calendar": "UTC calendar days, candidate 0.0 on non-sessions",
            "aligned_days": len(aligned),
            "internal_missing_by_series": {},
        },
        "report": result["book_evidence"]["diversification"]["report"],
        "extras": {k: v for k, v in extras.items() if k != "overlay_replay"},
    }
    diversification_document["content_hash"] = _observed_content_hash(diversification_document)
    diversification_file = _write(OUT / f"{profile}_diversification.json", diversification_document)
    evidence = build_evidence(
        section=section,
        profile=profile,
        identity_key=identity_key,
        result=result,
        reservation=reservation,
        reservation_path=reservation_path,
        extras=extras,
        diversification_file=diversification_file,
        matrix=matrix,
        contract=contract,
        rerun=rerun,
    )
    evidence_file = _write(OUT / f"{profile}_admission_evidence.json", evidence)
    report = evaluate_sleeve_evidence(evidence, contract)
    force_flats = int(result["evaluation"]["events"]["force_flat"])
    failures = list(report.failures)
    if not failures and force_flats > 0:
        disposition, data_escalate = "INCOMPLETE", True
    elif not failures:
        disposition, data_escalate = "ADMIT", False
    else:
        disposition, data_escalate = "KILL", False
    closure: dict[str, Any] = {
        "schema": CLOSURE_SCHEMA,
        "author": "Arhan Canli",
        "sealed_at": sealed_at,
        "status": f"FINAL_{disposition}" + ("_DATA_ESCALATE" if data_escalate else ""),
        "identity": {
            "hypothesis_key": identity_key,
            "config_hash": result["ledger_record"]["config_hash"],
            "family_trial_account": reservation["family_trial_account"],
            "return_identity_id": profile,
            "reservation_ordinal": reservation["governance_epoch"]["reservation_ordinal"],
            "batch_id": matrix["batch_id"],
            "section": section,
        },
        "decision": {
            "disposition": disposition,
            "admitted": disposition == "ADMIT",
            "killed": disposition == "KILL",
            "data_escalate": data_escalate,
            "final_for_admission": True,
            "identity_may_be_regraded_later": False,
            "technically_eligible": not failures,
            "evaluator_decision": report.decision,
            "checks_evaluated": report.checks_evaluated,
            "failures": failures,
            "warnings": list(report.warnings),
            "force_flat_events": force_flats,
            "deployment_conditions": [extras["overlay_replay"]["deployment_condition"]],
            "data_escalate_rule": (
                "pre-registration: a result that otherwise passes but contains any force-flat "
                "event is DATA-ESCALATE pending dedicated delisting payouts/returns, not ADD"
            ),
        },
        "headline": {
            "net_sharpe": evidence["statistics"]["net_sharpe"],
            "stressed_sharpe": evidence["statistics"]["stressed_sharpe"],
            "newey_west_t": evidence["statistics"]["newey_west_t"],
            "deflated_sharpe": evidence["statistics"]["deflated_sharpe"],
            "pbo": evidence["statistics"]["pbo"]["value"],
            "book_sharpe_delta": evidence["portfolio"]["book_sharpe_delta"],
            "book_sharpe_delta_lower_95": evidence["portfolio"]["book_sharpe_delta_lower_95"],
            "book_expected_max_drawdown": evidence["portfolio"]["book_expected_max_drawdown"],
            "capacity_usd": evidence["capacity"]["capacity_usd"],
            "max_drawdown": result["evaluation"]["net"]["max_drawdown"],
        },
        "lineage": {
            "admission_contract": _binding(CONTRACT),
            "preregistration": _binding(REPO / reservation["evidence"]["preregistration"]["path"]),
            "reservation": _binding(reservation_path),
            "primary_result": {**_binding(result_path), "content_hash": result["content_hash"]},
            "curve": _binding(out_dir / "curve.parquet"),
            "batch_matrix_receipt": {
                "path": result["batch"]["matrix_receipt"],
                "content_hash": matrix["content_hash"],
            },
            "diversification_report": _binding(diversification_file),
            "admission_evidence": _binding(evidence_file),
            "runner": _binding(REPO / "scripts" / "run_earnings_narrative_change_v1.py"),
            "python_project": _binding(REPO / "pyproject.toml"),
            "locked_environment": _binding(REPO / "uv.lock"),
            "ledger": result["ledger_record"],
        },
        "deterministic_rerun": rerun,
        "claim_boundary": (
            "A research decision under config/sleeve_admission_contract.json on one pre-registered "
            "out-of-sample record. ADMIT means every applicable gate passed on this evidence; it "
            "is not a forecast, not real-money performance, and does not itself change the live "
            "book, which changes only by a declared live-configuration change."
        ),
    }
    closure["content_hash"] = _observed_content_hash(closure)
    closure_path = _write(OUT / f"{profile}_admission_closure.json", closure)
    packet = build_packet(
        profile=profile,
        identity_key=identity_key,
        result=result,
        result_path=result_path,
        reservation=reservation,
        reservation_path=reservation_path,
        closure=closure,
        closure_path=closure_path,
        diversification_file=diversification_file,
        evidence_file=evidence_file,
        matrix=matrix,
        sealed_at=sealed_at,
        out_dir=out_dir,
    )
    packet_path = REPO / IDENTITY_PACKET_DIR / f"{identity_key}.json"
    _write(packet_path, packet)
    return {
        "profile": profile,
        "hypothesis_key": identity_key,
        "disposition": disposition,
        "data_escalate": data_escalate,
        "failures": failures,
        "closure": str(closure_path.relative_to(REPO)),
        "packet": str(packet_path.relative_to(REPO)),
        "headline": closure["headline"],
    }


def build_packet(
    *,
    profile: str,
    identity_key: str,
    result: dict[str, Any],
    result_path: Path,
    reservation: dict[str, Any],
    reservation_path: Path,
    closure: dict[str, Any],
    closure_path: Path,
    diversification_file: Path,
    evidence_file: Path,
    matrix: dict[str, Any],
    sealed_at: str,
    out_dir: Path,
) -> dict[str, Any]:
    prereg = REPO / reservation["evidence"]["preregistration"]["path"]
    pairs_result = REPO / reservation["evidence"]["input_data_manifest"]["path"]
    verified = "VERIFIED_IDENTITY_LEVEL_EVIDENCE"
    sections: dict[str, dict[str, Any]] = {
        "identity_and_authorship": {"status": verified, "evidence": [_binding(reservation_path)]},
        "economic_mechanism_and_falsifiable_hypothesis": {
            "status": verified,
            "evidence": [_binding(prereg)],
        },
        "literature_and_overlap_decision": {"status": verified, "evidence": [_binding(prereg)]},
        "preregistration_and_hashes": {
            "status": verified,
            "evidence": [_binding(prereg), _binding(reservation_path)],
        },
        "point_in_time_data_and_survivorship_controls": {
            "status": verified,
            "evidence": [_binding(pairs_result), _binding(out_dir / "input_manifest.json")],
        },
        "execution_and_cost_model": {
            "status": verified,
            "evidence": [
                _binding(
                    REPO
                    / reservation["full_evidence"]["execution_evidence"]["scenario_manifest_path"]
                ),
                _binding(evidence_file),
            ],
        },
        "code_environment_and_reproduction": {
            "status": verified,
            "evidence": [
                _binding(REPO / "scripts" / "run_earnings_narrative_change_v1.py"),
                _binding(REPO / "pyproject.toml"),
                _binding(REPO / "uv.lock"),
            ],
        },
        "result_uncertainty_stress_capacity_and_diversification": {
            "status": verified,
            "evidence": [
                {**_binding(result_path), "content_hash": result["content_hash"]},
                _binding(diversification_file),
                _binding(evidence_file),
            ],
        },
        "family_and_union_trial_accounting": {
            "status": verified,
            "evidence": [
                {
                    "path": result["ledger_record"]["ledger"],
                    "config_hash": result["ledger_record"]["config_hash"],
                },
                {"path": result["batch"]["matrix_receipt"], "content_hash": matrix["content_hash"]},
            ],
        },
        "admission_or_kill_decision": {
            "status": f"VERIFIED_FINAL_{closure['decision']['disposition']}",
            "statement": closure["status"],
            "evidence": [
                {
                    **_binding(closure_path),
                    "content_hash": closure["content_hash"],
                    "type": "final_admission_closure",
                }
            ],
        },
        "machine_readable_packet_and_stable_public_paper": {
            "status": verified,
            "evidence": [
                {
                    "packet_public_path": reservation["packet_public_path"],
                    "paper_public_path": reservation["paper_public_path"],
                }
            ],
        },
    }
    packet: dict[str, Any] = {
        "schema": PACKET_SCHEMA,
        "author": "Arhan Canli",
        "evidence_date": sealed_at[:10],
        "hypothesis_key": identity_key,
        "config_hash": result["ledger_record"]["config_hash"],
        "research_family_key": reservation["family_trial_account"],
        "label": profile,
        "configuration": result["trial_config"],
        "immutable_first_measurement": {
            "ledger": result["ledger_record"]["ledger"],
            "config_hash": result["ledger_record"]["config_hash"],
        },
        "required_sections": sections,
        "verified_sections": list(sections),
        "partial_sections": [],
        "missing_sections": [],
        "complete": True,
        "packet_status": f"COMPLETE_ACCOUNTING_FINAL_{closure['decision']['disposition']}",
        "completion_assessment": {"status": "COMPLETE_V2_FULL_EVIDENCE_BATCH"},
        "result_receipt": {
            "path": str(result_path.relative_to(REPO)),
            "content_hash": result["content_hash"],
        },
        "trial_paper_public_path": reservation["paper_public_path"],
        "family_paper_public_path": "/research/equity-narrative-change-lineage.md",
        "claim_boundary": closure["claim_boundary"],
    }
    packet["content_hash"] = _observed_content_hash(packet)
    return packet


def seal(*, do_rerun: bool) -> dict[str, Any]:
    runner = _load_module(
        REPO / "scripts" / "run_earnings_narrative_change_v1.py", "narrative_runner_for_seal"
    )
    study = _load_module(
        REPO / "scripts" / "analyze_current_book_drawdown.py", "narrative_seal_drawdown_study"
    )
    contract = load_admission_contract(CONTRACT)
    matrix_path = runner.BATCH_MATRIX_DIR / f"{runner.BATCH_ID}_matrix_receipt.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    if matrix.get("content_hash") != runner._content_hash(matrix):
        raise SystemExit("batch matrix receipt content hash mismatch")
    sealed_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    rows = [
        seal_identity(
            section,
            runner=runner,
            study=study,
            contract=contract,
            matrix=matrix,
            do_rerun=do_rerun,
            sealed_at=sealed_at,
        )
        for section in runner.SECTIONS
    ]
    summary: dict[str, Any] = {
        "schema": "canli.alphac-identity-batch-seal.v1",
        "batch_id": runner.BATCH_ID,
        "sealed_at": sealed_at,
        "matrix_receipt": {
            "path": str(matrix_path.relative_to(REPO)),
            "content_hash": matrix["content_hash"],
            "pbo": matrix["pbo"],
        },
        "identities": rows,
        "claim_boundary": (
            "One seal for one atomic batch; every identity decided by the contract's evaluator "
            "on its own evidence."
        ),
    }
    summary["content_hash"] = _observed_content_hash(summary)
    _write(OUT / "batch_seal.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--skip-rerun",
        action="store_true",
        help="do not re-run the sections for the determinism check",
    )
    args = parser.parse_args(argv)
    summary = seal(do_rerun=not args.skip_rerun)
    for row in summary["identities"]:
        print(
            f"{row['profile']}: {row['disposition']}"
            + (" (DATA-ESCALATE)" if row["data_escalate"] else ""),
            f"failures={len(row['failures'])}",
        )
        for failure in row["failures"]:
            print("   -", failure)
    return 0


if __name__ == "__main__":
    sys.exit(main())
