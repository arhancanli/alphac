#!/usr/bin/env python3
"""Build uncertainty and canonical diversification evidence for one preserved factor curve."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from alphaforge.analytics.curve_store import read_curve
from alphaforge.validation.diversification import diversification_report
from alphaforge.validation.dsr import dsr_from_returns
from alphaforge.validation.legacy_epoch import legacy_selection_context

REPO: Final[Path] = Path(__file__).resolve().parent.parent
IDENTITY: Final[str] = "1d2924f28fe31a9a"
RUN_NAME: Final[str] = "single_gross_profitability"
CURVE: Final[Path] = REPO / "artifacts" / "walkforward" / RUN_NAME / "equity.parquet"
WALKFORWARD: Final[Path] = CURVE.parent / "walkforward.json"
OUT: Final[Path] = REPO / "artifacts" / "probe" / "fundamental_single_replays" / IDENTITY
SLEEVE_CURVES: Final[dict[str, Path]] = {
    "AlphaForge": REPO / "artifacts/walkforward/crypto_carry_wk/equity.parquet",
    "AlphaMax": REPO / "artifacts/walkforward/k30_dn_63/equity.parquet",
    "AlphaTrend": REPO / "artifacts/walkforward/managed_futures/equity.parquet",
    "AlphaVintage": REPO / "artifacts/probe/cpi_surprise_size/equity.parquet",
}
BOOTSTRAP_SAMPLES: Final[int] = 2_000
BOOTSTRAP_BLOCK_SIZE: Final[int] = 21
BOOTSTRAP_SEED: Final[int] = 20260816
LEDGER_ANNUALIZATION: Final[int] = 365
CANDIDATES: Final[dict[str, str]] = {
    "single_gross_profitability": "1d2924f28fe31a9a",
    "single_book_to_price": "a238c1a5ecc5d1e3",
    "single_earnings_yield": "e86109044ab18734",
    "single_sales_to_price": "2d966892fb5db520",
    "single_operating_margin": "e5f48adc25065ce9",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _sharpe(returns: pd.Series) -> float:
    return float(returns.mean() / returns.std(ddof=1) * math.sqrt(LEDGER_ANNUALIZATION))


def _newey_west_t(returns: pd.Series, lags: int = 10) -> float:
    values = returns.to_numpy(dtype=float)
    residual = values - values.mean()
    variance = float(residual @ residual) / len(values)
    for lag in range(1, lags + 1):
        covariance = float(residual[lag:] @ residual[:-lag]) / len(values)
        variance += 2.0 * (1.0 - lag / (lags + 1.0)) * covariance
    return float(values.mean() / math.sqrt(max(variance, 1e-18) / len(values)))


def _max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def build_evidence(
    run_name: str = RUN_NAME,
    identity: str = IDENTITY,
) -> tuple[dict[str, Any], dict[str, Any]]:
    curve = REPO / "artifacts" / "walkforward" / run_name / "equity.parquet"
    walkforward = curve.parent / "walkforward.json"
    out = REPO / "artifacts" / "probe" / "fundamental_single_replays" / identity
    artifact = json.loads(walkforward.read_text(encoding="utf-8"))
    candidate_log = read_curve(curve)
    candidate = np.expm1(candidate_log)
    if len(candidate) != artifact["validation"]["n_obs"]:
        raise ValueError("preserved curve observation count does not match walkforward.json")
    if not math.isclose(
        _sharpe(candidate), artifact["validation"]["sr_ann"], rel_tol=0.0, abs_tol=1e-12
    ):
        raise ValueError("preserved curve Sharpe does not match walkforward.json")

    sleeve_logs = {name: read_curve(path) for name, path in SLEEVE_CURVES.items()}
    starts = [
        candidate_log.first_valid_index(),
        *(series.first_valid_index() for series in sleeve_logs.values()),
    ]
    ends = [
        candidate_log.last_valid_index(),
        *(series.last_valid_index() for series in sleeve_logs.values()),
    ]
    if any(value is None for value in (*starts, *ends)):
        raise ValueError("candidate or sleeve curve is empty")
    common_start = max(pd.Timestamp(value) for value in starts)
    common_end = min(pd.Timestamp(value) for value in ends)
    common_index = candidate_log.loc[common_start:common_end].index
    joined = pd.DataFrame(
        {
            "candidate": candidate_log.reindex(common_index),
            **{name: series.reindex(common_index) for name, series in sleeve_logs.items()},
        },
        index=common_index,
    )
    missing = {name: int(joined[name].isna().sum()) for name in joined if joined[name].isna().any()}
    if missing:
        raise ValueError(f"canonical alignment has internal missing dates: {missing}")
    simple = np.expm1(joined)
    base = simple[list(sleeve_logs)].mean(axis=1)
    stress_mask = (base <= base.quantile(0.10)).to_numpy(dtype=bool)
    report = diversification_report(
        simple["candidate"].to_numpy(),
        {name: simple[name].to_numpy() for name in sleeve_logs},
        base.to_numpy(),
        stress_mask=stress_mask,
        period_labels=[str(year) for year in simple.index.year],
        candidate_weight=0.10,
        bootstrap_samples=BOOTSTRAP_SAMPLES,
        bootstrap_block_size=BOOTSTRAP_BLOCK_SIZE,
        bootstrap_seed=BOOTSTRAP_SEED,
    )
    diversification: dict[str, Any] = {
        "schema": "canli.alphac-canonical-diversification.v1",
        "family_trial_account": "equity_fundamental_quality",
        "return_identity_id": identity,
        "alignment": {
            "common_start": str(common_index.min().date()),
            "common_end": str(common_index.max().date()),
            "common_days": len(common_index),
            "candidate_days_before_common_start": int((candidate.index < common_start).sum()),
            "candidate_days_after_common_end": int((candidate.index > common_end).sum()),
            "internal_missing_by_series": {},
            "stress_rule": "bottom decile of pre-existing equal-weight ALPHAC book returns",
            "stress_threshold": float(base.quantile(0.10)),
        },
        "report": report.to_dict(),
    }
    diversification["content_hash"] = _content_hash(diversification)

    n_trials, variance, _ = legacy_selection_context(REPO)
    dsr = dsr_from_returns(
        candidate,
        n_trials=n_trials,
        sr_trials_variance=variance,
        periods_per_year=LEDGER_ANNUALIZATION,
    )
    evidence: dict[str, Any] = {
        "schema": "canli.alphac-fundamental-single-curve-evidence.v1",
        "evidence_date": "2026-08-22",
        "author": "Arhan Canli",
        "hypothesis_key": identity,
        "run_name": run_name,
        "verdict": "KILL",
        "determinative_reason": "The preregistered net Sharpe is negative.",
        "metrics": {
            "observations": len(candidate),
            "ledger_annualization_periods_per_year": LEDGER_ANNUALIZATION,
            "annualized_sharpe": _sharpe(candidate),
            "newey_west_t_lags_10": _newey_west_t(candidate),
            "maximum_drawdown": _max_drawdown(candidate),
            "skew": float(candidate.skew()),
            "artifact_era_dsr": artifact["validation"]["dsr"],
            "artifact_era_trials": artifact["validation"]["n_trials"],
            "current_union_dsr": dsr.dsr,
            "current_union_psr": dsr.psr,
            "current_union_trials": n_trials,
            "current_union_sr_variance": variance,
        },
        "diversification": {
            "artifact": str((out / "diversification.json").relative_to(REPO)),
            "ordinary_by_sleeve": report.pairwise_correlations,
            "average": report.average_pairwise_correlation,
            "max_pair": report.max_pairwise_correlation,
            "ordinary_upper_95_by_sleeve": report.pairwise_correlation_upper_95,
            "max_pair_upper_95": report.max_pairwise_correlation_upper_95,
            "stressed_by_sleeve": report.stressed_pairwise_correlations,
            "max_stressed": report.max_stressed_pairwise_correlation,
            "stressed_upper_95_by_sleeve": report.stressed_pairwise_correlation_upper_95,
            "max_stressed_upper_95": report.max_stressed_pairwise_correlation_upper_95,
            "book_sharpe_delta_at_10pct": report.book_sharpe_delta,
            "minimum_leave_one_year_out_delta": (
                report.minimum_leave_one_period_out_book_sharpe_delta
            ),
        },
        "lineage": {
            "walkforward_sha256": _sha256(walkforward),
            "curve_sha256": _sha256(curve),
            "diversification_content_hash": diversification["content_hash"],
        },
        "claim_boundary": (
            "This artifact proves curve-derived uncertainty and diversification only. Exact "
            "current-code replay, input partition lineage, execution-cost stress, and capacity "
            "remain separate required evidence."
        ),
    }
    evidence["content_hash"] = _content_hash(evidence)
    return evidence, diversification


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_name", nargs="?", default=RUN_NAME, choices=CANDIDATES)
    args = parser.parse_args()
    identity = CANDIDATES[args.run_name]
    evidence, diversification = build_evidence(args.run_name, identity)
    out = REPO / "artifacts" / "probe" / "fundamental_single_replays" / identity
    out.mkdir(parents=True, exist_ok=True)
    (out / "curve_evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "diversification.json").write_text(
        json.dumps(diversification, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence["metrics"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
