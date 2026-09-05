#!/usr/bin/env python3
"""Measure current-composition drawdown under a frozen two-model protocol."""

from __future__ import annotations

import datetime as dt
import glob
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
PROTOCOL: Final[Path] = REPO / "docs/design/CURRENT_BOOK_DRAWDOWN_STUDY_PROTOCOL.md"
LIVE_CONTRACT: Final[Path] = REPO / "config/live_change_contract.json"
ADMISSION_CONTRACT: Final[Path] = REPO / "config/sleeve_admission_contract.json"
PAPER_STATE_SCRIPT: Final[Path] = REPO / "scripts/paper_trading_state.py"
BOOK_IMPLEMENTATION: Final[Path] = REPO / "src/alphaforge/portfolio/book.py"
MARKET_FACTOR_IMPLEMENTATION: Final[Path] = (
    REPO / "src/alphaforge/portfolio/market_factor.py"
)
OUTPUT: Final[Path] = REPO / "artifacts/analysis/current_book_drawdown/result.json"

PATHS: Final = 10_000
HORIZON_DAYS: Final = 730
BOOTSTRAP_SEED: Final = 20260823
REGIME_SEED: Final = 20260824
PRIMARY_BLOCK_DAYS: Final = 63
BLOCK_DAYS: Final = (21, PRIMARY_BLOCK_DAYS, 126)
STRESS_SHARE: Final = 0.12
MEAN_STRESS_RUN_DAYS: Final = 40.0
BATCH_SIZE: Final = 500
EPOCH: Final = dt.date(1970, 1, 1)

FloatArray = npt.NDArray[np.float64]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _max_drawdowns(returns: FloatArray) -> FloatArray:
    wealth = np.cumprod(1.0 + returns, axis=1)
    peaks = np.maximum.accumulate(
        np.concatenate([np.ones((returns.shape[0], 1)), wealth], axis=1), axis=1
    )[:, :-1]
    return np.max(1.0 - wealth / peaks, axis=1)


def _summarize(max_drawdowns: FloatArray) -> dict[str, float]:
    return {
        "expected_max_drawdown": float(np.mean(max_drawdowns)),
        "median_max_drawdown": float(np.median(max_drawdowns)),
        "p95_max_drawdown": float(np.quantile(max_drawdowns, 0.95)),
        "max_drawdown_stderr": float(
            np.std(max_drawdowns, ddof=1) / math.sqrt(max_drawdowns.size)
        ),
    }


def circular_block_bootstrap(
    source: FloatArray,
    *,
    paths: int,
    horizon_days: int,
    block_days: int,
    seed: int,
) -> dict[str, float]:
    if source.ndim != 1 or source.size < block_days:
        raise ValueError("bootstrap source must be one-dimensional and at least one block long")
    if not np.all(np.isfinite(source)) or np.any(source <= -1.0):
        raise ValueError("bootstrap source contains invalid simple returns")
    if paths < 2 or horizon_days < 2 or block_days < 1:
        raise ValueError("bootstrap dimensions are invalid")
    rng = np.random.default_rng(seed)
    blocks = math.ceil(horizon_days / block_days)
    offsets = np.arange(block_days, dtype=np.int64)
    output = np.empty(paths, dtype=np.float64)
    for first in range(0, paths, BATCH_SIZE):
        size = min(BATCH_SIZE, paths - first)
        starts = rng.integers(0, source.size, size=(size, blocks))
        indices = (starts[:, :, None] + offsets[None, None, :]) % source.size
        sampled = source[indices.reshape(size, -1)[:, :horizon_days]]
        output[first : first + size] = _max_drawdowns(sampled)
    return _summarize(output)


def _nearest_correlation(matrix: FloatArray) -> FloatArray:
    symmetric = 0.5 * (matrix + matrix.T)
    values, vectors = np.linalg.eigh(symmetric)
    repaired = (vectors * np.maximum(values, 1e-10)[None, :]) @ vectors.T
    scale = np.sqrt(np.diag(repaired))
    correlation = repaired / np.outer(scale, scale)
    np.fill_diagonal(correlation, 1.0)
    return np.asarray(0.5 * (correlation + correlation.T), dtype=np.float64)


def correlation_regime_drawdown(
    contributions: FloatArray,
    *,
    paths: int,
    horizon_days: int,
    stress_correlation: float,
    stress_share: float,
    mean_stress_run_days: float,
    seed: int,
) -> tuple[dict[str, float], dict[str, Any]]:
    if contributions.ndim != 2 or contributions.shape[1] < 2:
        raise ValueError("regime calibration requires a TxN contribution matrix")
    if not np.all(np.isfinite(contributions)):
        raise ValueError("regime calibration contains non-finite contributions")
    if not 0.0 <= stress_correlation < 1.0:
        raise ValueError("stress correlation must be in [0, 1)")
    centered = contributions - np.mean(contributions, axis=0)
    vol = np.std(centered, axis=0, ddof=1)
    if np.any(vol <= 0.0):
        raise ValueError("every regime component must have positive observed volatility")
    calm_corr = _nearest_correlation(np.corrcoef(centered, rowvar=False))
    stress_corr = np.full_like(calm_corr, stress_correlation)
    np.fill_diagonal(stress_corr, 1.0)
    calm_chol = np.linalg.cholesky(calm_corr)
    stress_chol = np.linalg.cholesky(stress_corr)
    p_exit = 1.0 / mean_stress_run_days
    p_enter = p_exit * stress_share / (1.0 - stress_share)
    rng = np.random.default_rng(seed)
    output = np.empty(paths, dtype=np.float64)
    stress_days = 0
    for first in range(0, paths, BATCH_SIZE):
        size = min(BATCH_SIZE, paths - first)
        state = rng.random(size) < stress_share
        regimes = np.empty((size, horizon_days), dtype=bool)
        for day in range(horizon_days):
            draw = rng.random(size)
            state = np.where(state, draw >= p_exit, draw < p_enter)
            regimes[:, day] = state
        stress_days += int(np.sum(regimes))
        z = rng.standard_normal((size, horizon_days, contributions.shape[1]))
        calm = np.einsum("ij,ptj->pti", calm_chol, z)
        stressed = np.einsum("ij,ptj->pti", stress_chol, z)
        innovations = np.where(regimes[:, :, None], stressed, calm) * vol
        book_returns = np.sum(innovations, axis=2)
        output[first : first + size] = _max_drawdowns(book_returns)
    diagnostics = {
        "component_daily_volatility": vol.tolist(),
        "calm_correlation": calm_corr.tolist(),
        "stress_correlation": stress_corr.tolist(),
        "simulated_stress_day_fraction": stress_days / float(paths * horizon_days),
    }
    return _summarize(output), diagnostics


def _corpus_binding(patterns: list[str]) -> dict[str, Any]:
    files = sorted({path for pattern in patterns for path in glob.glob(pattern, recursive=True)})
    if not files:
        raise FileNotFoundError("market-factor source corpus is empty")
    rows = [
        {"path": str(Path(path).relative_to(REPO)), "sha256": _sha256(Path(path))}
        for path in files
    ]
    digest = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {"files": len(rows), "manifest_sha256": digest}


def build() -> dict[str, Any]:
    paper = _load_script("current_book_drawdown_paper_state", PAPER_STATE_SCRIPT)
    market_module = _load_script(
        "current_book_drawdown_market_factor", MARKET_FACTOR_IMPLEMENTATION
    )
    live_contract = json.loads(LIVE_CONTRACT.read_text(encoding="utf-8"))
    admission = json.loads(ADMISSION_CONTRACT.read_text(encoding="utf-8"))
    aggregation = live_contract["declared_surface"]["book_aggregation_settings"]
    if aggregation != paper.book_aggregation_metadata():
        raise ValueError("declared aggregation does not match the running combine path")
    if live_contract["declared_fingerprint"] != (
        "sha256:fe82c4eeed742289bfcfee5d39856ee2bb8ca9cfe209bcc7e34abff98553706d"
    ):
        raise ValueError("current-book drawdown protocol is bound to a different live fingerprint")

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
    if book.vol_target_ann is not None or book.strategic_tilt_pct != 0.10:
        raise ValueError("constructed research book does not match the declared flagship policy")
    names = list(book.names)
    contributions = np.column_stack(
        [book.weights[name] * book.sleeve_returns[name] for name in names]
        + [book.overlay_returns]
    )
    if not np.allclose(np.sum(contributions, axis=1), book.book_returns, atol=1e-15):
        raise ValueError("component contributions do not reconstruct the exact book")
    centered_book = book.book_returns - float(np.mean(book.book_returns))
    bootstrap = {
        str(block): circular_block_bootstrap(
            centered_book,
            paths=PATHS,
            horizon_days=HORIZON_DAYS,
            block_days=block,
            seed=BOOTSTRAP_SEED,
        )
        for block in BLOCK_DAYS
    }
    stress_correlation = float(
        admission["thresholds"]["stressed_pairwise_correlation_max"]
    )
    regime, regime_diagnostics = correlation_regime_drawdown(
        contributions,
        paths=PATHS,
        horizon_days=HORIZON_DAYS,
        stress_correlation=stress_correlation,
        stress_share=STRESS_SHARE,
        mean_stress_run_days=MEAN_STRESS_RUN_DAYS,
        seed=REGIME_SEED,
    )
    primary = bootstrap[str(PRIMARY_BLOCK_DAYS)]
    conservative_expected = max(
        primary["expected_max_drawdown"], regime["expected_max_drawdown"]
    )
    conservative_p95 = max(
        primary["p95_max_drawdown"], regime["p95_max_drawdown"]
    )
    target = float(admission["thresholds"]["book_expected_max_drawdown_max"])
    start = EPOCH + dt.timedelta(days=int(book.window[0]))
    end = EPOCH + dt.timedelta(days=int(book.window[1]))
    source_files = [
        REPO / "artifacts/walkforward/k30_dn_63/equity.parquet",
        REPO / "artifacts/walkforward/crypto_carry_wk/equity.parquet",
        REPO / "artifacts/walkforward/managed_futures/equity.parquet",
        REPO / "artifacts/probe/cpi_surprise_size/equity.parquet",
    ]
    market_patterns = [str(REPO / pattern) for _, _, pattern in market_module.DEFAULT_MIX]
    payload: dict[str, Any] = {
        "schema": "canli.alphac-current-book-drawdown-study.v1",
        "author": "Arhan Canli",
        "capital_kind": "RESEARCH_SIMULATION_OVER_PAPER_SPECIFICATION",
        "status": (
            "CURRENT_COMPOSITION_EXPECTED_WITHIN_OBJECTIVE_"
            "HISTORICAL_TAIL_COVERAGE_INCOMPLETE"
            if conservative_expected <= target
            else "CURRENT_COMPOSITION_EXPECTED_EXCEEDS_OBJECTIVE_"
            "HISTORICAL_TAIL_COVERAGE_INCOMPLETE"
        ),
        "trial_accounting": {
            "hypothesis_identities_spent": 0,
            "return_data_opened": False,
            "classification": "EXISTING_RETURN_RISK_REMEASUREMENT",
        },
        "configuration": {
            "live_fingerprint": live_contract["declared_fingerprint"],
            "sleeves": names,
            "weights": {name: float(book.weights[name][0]) for name in names},
            "strategic_tilt_pct": book.strategic_tilt_pct,
            "strategic_tilt_mix": paper.TILT_MIX,
            "aggregation": aggregation,
        },
        "calibration": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "calendar_days": book.n_days,
            "observed_book_annualized_volatility": book.vol,
            "observed_book_max_drawdown": abs(book.maxdd),
            "observed_book_sharpe_simulation_not_forward_evidence": book.sharpe,
            "sample_mean_removed_before_modeling": True,
            "component_order": [*names, "strategic_overlay"],
            "exact_component_reconstruction_max_abs_error": float(
                np.max(np.abs(np.sum(contributions, axis=1) - book.book_returns))
            ),
        },
        "design": {
            "paths_per_model": PATHS,
            "horizon_calendar_days": HORIZON_DAYS,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_primary_block_days": PRIMARY_BLOCK_DAYS,
            "bootstrap_sensitivity_block_days": list(BLOCK_DAYS),
            "regime_seed": REGIME_SEED,
            "regime_stress_share": STRESS_SHARE,
            "regime_mean_stress_run_days": MEAN_STRESS_RUN_DAYS,
            "regime_stress_correlation": stress_correlation,
            "regime_component_means": "ZERO",
        },
        "models": {
            "circular_moving_block_bootstrap": bootstrap,
            "correlation_regime": {**regime, "diagnostics": regime_diagnostics},
        },
        "objective": {
            "expected_max_drawdown_target": target,
            "conservative_modeled_expected_max_drawdown": conservative_expected,
            "conservative_modeled_p95_max_drawdown": conservative_p95,
            "conservative_modeled_expected_within_target": conservative_expected <= target,
            "conservative_modeled_p95_within_target": conservative_p95 <= target,
            "live_expected_max_drawdown_established": False,
        },
        "failed_establishment_dimensions": [
            "COMMON_WINDOW_BEGINS_AFTER_COVID_AND_2022",
            "ABSENT_CRISIS_CANNOT_APPEAR_IN_BLOCK_BOOTSTRAP",
            "REGIME_MODEL_HAS_NO_STRESS_VOLATILITY_MULTIPLIER",
            "CONSTITUENT_INSTRUMENT_AND_LADDER_STATE_NOT_REPLAYED",
            "EXECUTION_GAPS_AND_LIQUIDITY_FEEDBACK_NOT_MODELED",
        ],
        "source_bindings": {
            "protocol": {"path": str(PROTOCOL.relative_to(REPO)), "sha256": _sha256(PROTOCOL)},
            "live_contract": {
                "path": str(LIVE_CONTRACT.relative_to(REPO)),
                "sha256": _sha256(LIVE_CONTRACT),
            },
            "admission_contract": {
                "path": str(ADMISSION_CONTRACT.relative_to(REPO)),
                "sha256": _sha256(ADMISSION_CONTRACT),
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
            "market_factor_source_corpus": _corpus_binding(market_patterns),
        },
        "claim_boundary": (
            "This is a zero-drift two-year risk simulation of the exact current four-sleeve "
            "fixed-weight research composition and strategic overlay. It is stronger mapping "
            "evidence than the fourteen-sleeve frontier cell, but it is not a funded result, a "
            "loss limit, a guarantee, or an established live expected-drawdown estimate. The "
            "common window begins after COVID and 2022, and neither model replays constituent "
            "instrument, execution-gap or ladder state."
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
                "objective": payload["objective"],
                "content_hash": payload["content_hash"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
