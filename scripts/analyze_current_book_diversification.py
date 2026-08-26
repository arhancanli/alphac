#!/usr/bin/env python3
"""Measure exact current-book diversification under the frozen retrospective protocol."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import numpy as np
import numpy.typing as npt

REPO: Final[Path] = Path(__file__).resolve().parents[1]
PROTOCOL: Final[Path] = REPO / "docs/design/CURRENT_BOOK_DIVERSIFICATION_STUDY_PROTOCOL.md"
ADMISSION_CONTRACT: Final[Path] = REPO / "config/sleeve_admission_contract.json"
LEGACY_V6_CONTRACT: Final[Path] = (
    REPO / "config/archive/sleeve_admission_contract_v6_superseded.json"
)
LIVE_CONTRACT: Final[Path] = REPO / "config/live_change_contract.json"
DRAWDOWN_SCRIPT: Final[Path] = REPO / "scripts/analyze_current_book_drawdown.py"
DRAWDOWN_RESULT: Final[Path] = REPO / "artifacts/analysis/current_book_drawdown/result.json"
PAPER_STATE_SCRIPT: Final[Path] = REPO / "scripts/paper_trading_state.py"
BOOK_IMPLEMENTATION: Final[Path] = REPO / "src/alphaforge/portfolio/book.py"
MARKET_FACTOR_IMPLEMENTATION: Final[Path] = REPO / "src/alphaforge/portfolio/market_factor.py"
OUTPUT: Final[Path] = REPO / "artifacts/analysis/current_book_diversification/result.json"

BOOTSTRAP_SAMPLES: Final = 10_000
BOOTSTRAP_SEED: Final = 20260825
PRIMARY_BLOCK_DAYS: Final = 63
BLOCK_DAYS: Final = (21, PRIMARY_BLOCK_DAYS, 126)
BATCH_SIZE: Final = 250
EPOCH: Final = dt.date(1970, 1, 1)

FloatArray = npt.NDArray[np.float64]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _annualized_sharpe(returns: FloatArray) -> float:
    volatility = float(np.std(returns, ddof=1))
    if volatility <= 0.0:
        raise ValueError("Sharpe diagnostic requires non-zero return variance")
    return float(np.mean(returns) / volatility * math.sqrt(365.0))


def _mc_quantile_standard_error(values: FloatArray, probability: float = 0.95) -> float:
    rank_se = math.sqrt(probability * (1.0 - probability) / values.size)
    lower_probability = max(0.0, probability - 1.96 * rank_se)
    upper_probability = min(1.0, probability + 1.96 * rank_se)
    lower, upper = np.quantile(values, [lower_probability, upper_probability])
    return float((upper - lower) / (2.0 * 1.96))


def circular_block_correlation_bootstrap(
    returns: FloatArray,
    *,
    samples: int,
    block_days: int,
    seed: int,
) -> dict[str, Any]:
    if returns.ndim != 2 or returns.shape[1] < 2 or returns.shape[0] < block_days:
        raise ValueError("correlation bootstrap requires a TxN matrix and a feasible block")
    if not np.all(np.isfinite(returns)):
        raise ValueError("correlation bootstrap input contains non-finite values")
    if samples < 2:
        raise ValueError("correlation bootstrap requires at least two samples")
    rows, columns = returns.shape
    pairs = [(left, right) for left in range(columns) for right in range(left + 1, columns)]
    blocks = math.ceil(rows / block_days)
    offsets = np.arange(block_days, dtype=np.int64)
    pair_values = np.empty((samples, len(pairs)), dtype=np.float64)
    rng = np.random.default_rng(seed)
    for first in range(0, samples, BATCH_SIZE):
        size = min(BATCH_SIZE, samples - first)
        starts = rng.integers(0, rows, size=(size, blocks))
        indices = (starts[:, :, None] + offsets[None, None, :]) % rows
        sampled = returns[indices.reshape(size, -1)[:, :rows]]
        centered = sampled - np.mean(sampled, axis=1, keepdims=True)
        covariance = np.einsum("bti,btj->bij", centered, centered) / float(rows - 1)
        volatility = np.sqrt(np.diagonal(covariance, axis1=1, axis2=2))
        correlation = covariance / (volatility[:, :, None] * volatility[:, None, :])
        pair_values[first : first + size] = np.column_stack(
            [correlation[:, left, right] for left, right in pairs]
        )
    average = np.mean(pair_values, axis=1)
    pair_summaries = [
        {
            "indices": [left, right],
            "mean": float(np.mean(pair_values[:, index])),
            "upper_95": float(np.quantile(pair_values[:, index], 0.95)),
            "mean_monte_carlo_standard_error": float(
                np.std(pair_values[:, index], ddof=1) / math.sqrt(samples)
            ),
            "upper_95_monte_carlo_standard_error": _mc_quantile_standard_error(
                pair_values[:, index]
            ),
        }
        for index, (left, right) in enumerate(pairs)
    ]
    return {
        "samples": samples,
        "block_days": block_days,
        "average_pairwise_correlation": {
            "mean": float(np.mean(average)),
            "upper_95": float(np.quantile(average, 0.95)),
            "mean_monte_carlo_standard_error": float(
                np.std(average, ddof=1) / math.sqrt(samples)
            ),
            "upper_95_monte_carlo_standard_error": _mc_quantile_standard_error(average),
        },
        "pairs": pair_summaries,
        "maximum_pairwise_upper_95": max(row["upper_95"] for row in pair_summaries),
    }


def build() -> dict[str, Any]:
    paper = _load_script("current_book_diversification_paper_state", PAPER_STATE_SCRIPT)
    market = _load_script(
        "current_book_diversification_market_factor", MARKET_FACTOR_IMPLEMENTATION
    )
    drawdown_module = _load_script("current_book_diversification_drawdown", DRAWDOWN_SCRIPT)
    admission = json.loads(ADMISSION_CONTRACT.read_text(encoding="utf-8"))
    legacy_v6 = json.loads(LEGACY_V6_CONTRACT.read_text(encoding="utf-8"))
    live_contract = json.loads(LIVE_CONTRACT.read_text(encoding="utf-8"))
    drawdown_result = json.loads(DRAWDOWN_RESULT.read_text(encoding="utf-8"))
    if drawdown_result.get("content_hash") != drawdown_module._content_hash(drawdown_result):
        raise ValueError("current-book drawdown source binding is invalid")
    if live_contract["declared_surface"]["book_aggregation_settings"] != (
        paper.book_aggregation_metadata()
    ):
        raise ValueError("declared aggregation does not match the running combine path")

    sleeves = [
        paper.load_wf(paper.EQUITY_WF),
        paper.load_wf(paper.CRYPTO_WF),
        paper.load_wf(paper.MF_WF),
        paper.load_probe_curve(
            paper.VINTAGE_WF, "artifacts/probe/cpi_surprise_size/equity.parquet"
        ),
    ]
    book = paper.combine_book(
        sleeves,
        scheme=paper.BOOK_AGGREGATION_SCHEME,
        fixed_weights=paper.BOOK_WEIGHTS,
        vol_target_ann=paper.BOOK_LEVEL_VOL_TARGET_ANN,
        trading_days=365,
        strategic_tilt_pct=paper.STRATEGIC_TILT_PCT,
        strategic_tilt_market=paper.market_factor_by_epochday(),
    )
    names = list(book.names)
    sleeve_returns = np.column_stack([book.sleeve_returns[name] for name in names])
    sleeve_contributions = np.column_stack(
        [book.weights[name] * book.sleeve_returns[name] for name in names]
    )
    exact = np.sum(sleeve_contributions, axis=1) + book.overlay_returns
    reconstruction_error = float(np.max(np.abs(exact - book.book_returns)))
    if reconstruction_error > 1e-15:
        raise ValueError("component contributions do not reconstruct the exact book")
    if drawdown_result["configuration"]["sleeves"] != names:
        raise ValueError("sleeve order differs from the sealed current-book drawdown study")
    if drawdown_result["configuration"]["live_fingerprint"] != live_contract[
        "declared_fingerprint"
    ]:
        raise ValueError("live fingerprint differs from the sealed current-book drawdown study")

    correlation = np.corrcoef(sleeve_returns, rowvar=False)
    pair_rows = []
    pair_values = []
    for left in range(len(names)):
        for right in range(left + 1, len(names)):
            value = float(correlation[left, right])
            pair_values.append(value)
            pair_rows.append({"pair": [names[left], names[right]], "correlation": value})
    average_correlation = float(np.mean(pair_values))
    maximum_pairwise = float(np.max(pair_values))
    eigenvalues = np.linalg.eigvalsh(correlation)
    participation_ratio = float(np.sum(eigenvalues) ** 2 / np.sum(eigenvalues**2))
    sleeve_volatility = np.std(sleeve_returns, axis=0, ddof=1)
    weights = np.asarray([float(book.weights[name][0]) for name in names])
    sleeve_only_returns = np.sum(sleeve_contributions, axis=1)
    diversification_ratio = float(
        np.dot(weights, sleeve_volatility) / np.std(sleeve_only_returns, ddof=1)
    )
    bootstrap = {
        str(block): circular_block_correlation_bootstrap(
            sleeve_returns,
            samples=BOOTSTRAP_SAMPLES,
            block_days=block,
            seed=BOOTSTRAP_SEED,
        )
        for block in BLOCK_DAYS
    }
    for result in bootstrap.values():
        names_pairs = [item["pair"] for item in pair_rows]
        for row, names_pair in zip(result["pairs"], names_pairs, strict=True):
            row["pair"] = names_pair
            del row["indices"]
    primary = bootstrap[str(PRIMARY_BLOCK_DAYS)]
    average_upper_95 = float(primary["average_pairwise_correlation"]["upper_95"])
    maximum_pairwise_upper_95 = float(primary["maximum_pairwise_upper_95"])
    thresholds = admission["thresholds"]
    legacy_v6_thresholds = legacy_v6["thresholds"]
    stressed_correlation = float(
        drawdown_result["design"]["regime_stress_correlation"]
    )
    checks = {
        "minimum_correlation_observations": (
            book.n_days >= int(thresholds["minimum_correlation_observations"])
        ),
        "average_pairwise_upper_95": (
            average_upper_95
            <= float(thresholds["average_pairwise_correlation_upper_95_max"])
        ),
        "ordinary_pairwise_point": (
            maximum_pairwise <= float(thresholds["ordinary_pairwise_correlation_max"])
        ),
        "ordinary_pairwise_upper_95": (
            maximum_pairwise_upper_95
            <= float(thresholds["pairwise_correlation_upper_95_max"])
        ),
        "stressed_pairwise_design": (
            stressed_correlation <= float(thresholds["stressed_pairwise_correlation_max"])
        ),
    }
    full_sharpe = _annualized_sharpe(book.book_returns)
    marginal = {
        name: {
            "book_sharpe_with_sleeve": full_sharpe,
            "book_sharpe_with_sleeve_replaced_by_cash": _annualized_sharpe(
                book.book_returns - sleeve_contributions[:, index]
            ),
        }
        for index, name in enumerate(names)
    }
    for row in marginal.values():
        row["marginal_book_sharpe_delta"] = (
            row["book_sharpe_with_sleeve"]
            - row["book_sharpe_with_sleeve_replaced_by_cash"]
        )

    start = EPOCH + dt.timedelta(days=int(book.window[0]))
    end = EPOCH + dt.timedelta(days=int(book.window[1]))
    source_files = [
        REPO / "artifacts/walkforward/k30_dn_63/equity.parquet",
        REPO / "artifacts/walkforward/crypto_carry_wk/equity.parquet",
        REPO / "artifacts/walkforward/managed_futures/equity.parquet",
        REPO / "artifacts/probe/cpi_surprise_size/equity.parquet",
    ]
    market_patterns = [str(REPO / pattern) for _, _, pattern in market.DEFAULT_MIX]
    objective = admission["objective"]
    objective_met = average_correlation <= float(
        objective["average_pairwise_correlation_objective"]
    )
    payload: dict[str, Any] = {
        "schema": "canli.alphac-current-book-diversification-study.v1",
        "author": "Arhan Canli",
        "capital_kind": "RESEARCH_SIMULATION_OVER_PAPER_SPECIFICATION",
        "status": (
            "CURRENT_COMPOSITION_DIVERSIFICATION_OBJECTIVE_MET_RESEARCH_ONLY"
            if objective_met
            else "CURRENT_COMPOSITION_DIVERSIFICATION_OBJECTIVE_GAP_RESEARCH_ONLY"
        ),
        "trial_accounting": {
            "hypothesis_identities_spent": 0,
            "return_data_were_known_before_protocol": True,
            "classification": "RETROSPECTIVE_EXISTING_RETURN_RISK_REMEASUREMENT",
        },
        "configuration": {
            "live_fingerprint": live_contract["declared_fingerprint"],
            "sleeves": names,
            "weights": {name: float(book.weights[name][0]) for name in names},
            "strategic_tilt_pct": book.strategic_tilt_pct,
            "strategic_tilt_mix": paper.TILT_MIX,
            "aggregation": paper.book_aggregation_metadata(),
        },
        "window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "calendar_rows": book.n_days,
        },
        "observed": {
            "correlation_matrix": correlation.tolist(),
            "pairwise_correlations": pair_rows,
            "average_pairwise_correlation": average_correlation,
            "maximum_pairwise_correlation": maximum_pairwise,
            "diversification_ratio_sleeves_only": diversification_ratio,
            "effective_independent_sleeves_participation_ratio": participation_ratio,
            "full_book_sharpe_research_simulation_not_forward_evidence": full_sharpe,
            "marginal_book_sharpe_research_diagnostics": marginal,
            "exact_component_reconstruction_max_abs_error": reconstruction_error,
        },
        "bootstrap": {
            "seed": BOOTSTRAP_SEED,
            "samples": BOOTSTRAP_SAMPLES,
            "primary_block_days": PRIMARY_BLOCK_DAYS,
            "sensitivity_block_days": list(BLOCK_DAYS),
            "results": bootstrap,
        },
        "governing_comparison": {
            "target_total_sleeves": int(objective["target_total_sleeves"]),
            "current_sleeves": len(names),
            "minimum_new_sleeves": int(objective["minimum_new_sleeves"]),
            "average_pairwise_correlation_objective": float(
                objective["average_pairwise_correlation_objective"]
            ),
            "active_v7_has_no_global_average_correlation_point_gate": True,
            "active_v7_candidate_average_correlation_gate": float(
                thresholds["candidate_average_correlation_to_existing_book_max"]
            ),
            "active_v7_book_average_correlation_delta_gate_exclusive": float(
                thresholds["book_average_pairwise_correlation_delta_max_exclusive"]
            ),
            "historical_v6_global_average_correlation_point_gate": float(
                legacy_v6_thresholds["average_pairwise_correlation_max"]
            ),
            "historical_v6_global_average_correlation_point_check": (
                average_correlation
                <= float(legacy_v6_thresholds["average_pairwise_correlation_max"])
            ),
            "average_pairwise_correlation_upper_95_gate": float(
                thresholds["average_pairwise_correlation_upper_95_max"]
            ),
            "ordinary_pairwise_correlation_point_gate": float(
                thresholds["ordinary_pairwise_correlation_max"]
            ),
            "ordinary_pairwise_correlation_upper_95_gate": float(
                thresholds["pairwise_correlation_upper_95_max"]
            ),
            "stressed_pairwise_correlation_gate": float(
                thresholds["stressed_pairwise_correlation_max"]
            ),
            "average_pairwise_upper_95": average_upper_95,
            "maximum_pairwise_upper_95": maximum_pairwise_upper_95,
            "stressed_pairwise_design_value_not_observed": stressed_correlation,
            "distance_from_average_correlation_objective": (
                average_correlation - float(objective["average_pairwise_correlation_objective"])
            ),
            "checks": checks,
            "passes_all_active_v7_risk_comparisons": all(checks.values()),
            "meets_active_correlation_objective": objective_met,
            "existing_sleeves_are_not_retroactively_adjudicated": True,
            "live_forward_diversification_established": False,
        },
        "failed_establishment_dimensions": [
            "RESEARCH_CURVES_END_BEFORE_BROKER_RECONCILED_FORWARD_RECORD",
            "RETURN_DATA_WERE_KNOWN_BEFORE_PROTOCOL",
            "NO_HUMAN_INDEPENDENT_REPLICATION",
            "NO_CRISIS_COMPLETE_FORWARD_CORRELATION_WINDOW",
        ],
        "source_bindings": {
            "protocol": {"path": str(PROTOCOL.relative_to(REPO)), "sha256": _sha256(PROTOCOL)},
            "admission_contract": {
                "path": str(ADMISSION_CONTRACT.relative_to(REPO)),
                "sha256": _sha256(ADMISSION_CONTRACT),
            },
            "legacy_v6_admission_contract": {
                "path": str(LEGACY_V6_CONTRACT.relative_to(REPO)),
                "sha256": _sha256(LEGACY_V6_CONTRACT),
            },
            "live_contract": {
                "path": str(LIVE_CONTRACT.relative_to(REPO)),
                "sha256": _sha256(LIVE_CONTRACT),
            },
            "current_book_drawdown": {
                "path": str(DRAWDOWN_RESULT.relative_to(REPO)),
                "sha256": _sha256(DRAWDOWN_RESULT),
                "content_hash": drawdown_result["content_hash"],
            },
            "study_implementation": {
                "path": "scripts/analyze_current_book_diversification.py",
                "sha256": _sha256(Path(__file__)),
            },
            "drawdown_implementation": {
                "path": str(DRAWDOWN_SCRIPT.relative_to(REPO)),
                "sha256": _sha256(DRAWDOWN_SCRIPT),
            },
            "paper_state_builder": {
                "path": str(PAPER_STATE_SCRIPT.relative_to(REPO)),
                "sha256": _sha256(PAPER_STATE_SCRIPT),
            },
            "book_implementation": {
                "path": str(BOOK_IMPLEMENTATION.relative_to(REPO)),
                "sha256": _sha256(BOOK_IMPLEMENTATION),
            },
            "market_factor_implementation": {
                "path": str(MARKET_FACTOR_IMPLEMENTATION.relative_to(REPO)),
                "sha256": _sha256(MARKET_FACTOR_IMPLEMENTATION),
            },
            "sleeve_equity_inputs": {
                str(path.relative_to(REPO)): _sha256(path) for path in source_files
            },
            "market_factor_source_corpus": drawdown_module._corpus_binding(market_patterns),
        },
        "claim_boundary": (
            "Retrospective diversification measurement of the exact current four-sleeve research "
            "specification and strategic overlay. It does not establish live-forward correlation, "
            "alpha, the 1.5 Sharpe objective, a reweighting decision, or retroactive admission. "
            "The return data were known before this protocol and the research window ends before "
            "the broker-reconciled forward record begins."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": payload["status"],
                "observed": payload["observed"],
                "governing_comparison": payload["governing_comparison"],
                "content_hash": payload["content_hash"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
