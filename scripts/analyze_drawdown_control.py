#!/usr/bin/env python3
"""Measure the declared book-level drawdown ladder on the published drawdown study's own paths.

WHY. The owner's goal is a HARD maximum drawdown on the combined book (11 percent when v1.0 was
frozen; 10 percent since the 2026-09-14 restatement, read from config/owner_goals.json), and a
backtest
cannot promise one: the published current-composition study puts the two-year 95th percentile at
16.5 percent under the admission contract's permitted stressed correlation. A bound that holds in
the tail is a brake. This study measures the brake declared in
`config/drawdown_control_contract.json` (half gross at 5.5 percent, flat at 11 percent, absorbing
until an owner review) on exactly the paths the published study drew, with and without the ladder,
under zero drift (the published basis) and with the research-window drift added back (the only
basis on which the brake's cost is visible), and applies the acceptance rule the protocol declared
before any number was seen. It spends no hypothesis identity and changes no live setting.

GUARD. Before reporting anything the study regenerates the published study's no-ladder baseline
from the same seeds and asserts it reproduces the published expected and 95th-percentile maximum
drawdowns to 1e-12. If the two studies ever describe different paths, this one fails closed.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import math
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import numpy as np
import numpy.typing as npt

from alphaforge.research.owner_goals import load_owner_goals
from alphaforge.risk.ladder_paths import simulate_book_ladder

REPO: Final[Path] = Path(__file__).resolve().parents[1]
CONTRACT: Final[Path] = REPO / "config/drawdown_control_contract.json"
PROTOCOL: Final[Path] = REPO / "docs/design/DRAWDOWN_CONTROL_V1_PROTOCOL.md"
STUDY_SCRIPT: Final[Path] = REPO / "scripts/analyze_current_book_drawdown.py"
STUDY_RESULT: Final[Path] = REPO / "artifacts/analysis/current_book_drawdown/result.json"
ADMISSION_CONTRACT: Final[Path] = REPO / "config/sleeve_admission_contract.json"
OUTPUT: Final[Path] = REPO / "artifacts/analysis/drawdown_control_v1/result.json"
BASELINE_TOLERANCE: Final[float] = 1e-12
FloatArray = npt.NDArray[np.float64]


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


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


def bootstrap_batches(
    source: FloatArray,
    *,
    paths: int,
    horizon_days: int,
    block_days: int,
    seed: int,
    batch_size: int,
) -> Iterator[FloatArray]:
    """The published study's circular moving-block draws, yielded as return matrices.

    Same generator, same seed, same call order as ``circular_block_bootstrap``; the study
    summarises each batch, this yields it so the ladder can run over the identical paths."""
    rng = np.random.default_rng(seed)
    blocks = math.ceil(horizon_days / block_days)
    offsets = np.arange(block_days, dtype=np.int64)
    for first in range(0, paths, batch_size):
        size = min(batch_size, paths - first)
        starts = rng.integers(0, source.size, size=(size, blocks))
        indices = (starts[:, :, None] + offsets[None, None, :]) % source.size
        yield np.asarray(source[indices.reshape(size, -1)[:, :horizon_days]], dtype=np.float64)


def regime_batches(
    contributions: FloatArray,
    *,
    paths: int,
    horizon_days: int,
    stress_correlation: float,
    stress_share: float,
    mean_stress_run_days: float,
    seed: int,
    batch_size: int,
    nearest_correlation: Any,
) -> Iterator[FloatArray]:
    """The published study's correlation-regime draws, yielded as book-return matrices."""
    centered = contributions - np.mean(contributions, axis=0)
    vol = np.std(centered, axis=0, ddof=1)
    calm_corr = nearest_correlation(np.corrcoef(centered, rowvar=False))
    stress_corr = np.full_like(calm_corr, stress_correlation)
    np.fill_diagonal(stress_corr, 1.0)
    calm_chol = np.linalg.cholesky(calm_corr)
    stress_chol = np.linalg.cholesky(stress_corr)
    p_exit = 1.0 / mean_stress_run_days
    p_enter = p_exit * stress_share / (1.0 - stress_share)
    rng = np.random.default_rng(seed)
    for first in range(0, paths, batch_size):
        size = min(batch_size, paths - first)
        state = rng.random(size) < stress_share
        regimes = np.empty((size, horizon_days), dtype=bool)
        for day in range(horizon_days):
            draw = rng.random(size)
            state = np.where(state, draw >= p_exit, draw < p_enter)
            regimes[:, day] = state
        z = rng.standard_normal((size, horizon_days, contributions.shape[1]))
        calm = np.einsum("ij,ptj->pti", calm_chol, z)
        stressed = np.einsum("ij,ptj->pti", stress_chol, z)
        innovations = np.where(regimes[:, :, None], stressed, calm) * vol
        yield np.asarray(np.sum(innovations, axis=2), dtype=np.float64)


def _quantiles(values: FloatArray) -> dict[str, float]:
    return {
        "expected": float(np.mean(values)),
        "median": float(np.median(values)),
        "p95": float(np.quantile(values, 0.95)),
        "p99": float(np.quantile(values, 0.99)),
        "max": float(np.max(values)),
        "stderr": float(np.std(values, ddof=1) / math.sqrt(values.size)),
    }


def ladder_specs(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    ladder = contract["ladder"]
    return {
        "absorbing": {
            "dd_half_frac": float(ladder["dd_half_frac"]),
            "dd_flat_frac": float(ladder["dd_flat_frac"]),
            "release_frac": float(ladder["release_frac_of_half"]),
            "flat_cooldown_bars": None,
        },
        "auto_rearm": {
            "dd_half_frac": float(ladder["dd_half_frac"]),
            "dd_flat_frac": float(ladder["dd_flat_frac"]),
            "release_frac": float(ladder["release_frac_of_half"]),
            "flat_cooldown_bars": int(ladder["secondary_scenario_flat_cooldown_days"]),
        },
    }


def evaluate(
    batches: Iterator[FloatArray],
    *,
    drift: float,
    specs: dict[str, dict[str, Any]],
    bound: float,
    max_drawdowns_fn: Any,
) -> dict[str, Any]:
    """Run baseline and every ladder over the batches (with ``drift`` added to each day)."""
    baseline_dd: list[FloatArray] = []
    baseline_wealth: list[FloatArray] = []
    per_spec: dict[str, dict[str, list[Any]]] = {
        name: {"dd": [], "wealth": [], "halted": [], "first": [], "reduced": [], "rearms": []}
        for name in specs
    }
    days = 0
    total_paths = 0
    for batch in batches:
        returns = batch + drift
        days = returns.shape[1]
        total_paths += returns.shape[0]
        baseline_dd.append(max_drawdowns_fn(returns))
        baseline_wealth.append(np.prod(1.0 + returns, axis=1))
        for name, spec in specs.items():
            run = simulate_book_ladder(
                returns,
                dd_half_frac=spec["dd_half_frac"],
                dd_flat_frac=spec["dd_flat_frac"],
                flat_cooldown_bars=spec["flat_cooldown_bars"],
                release_frac=spec["release_frac"],
            )
            store = per_spec[name]
            store["dd"].append(run.max_drawdowns)
            store["wealth"].append(np.prod(1.0 + run.realized_returns, axis=1))
            store["halted"].append(run.halted)
            store["first"].append(run.first_halt_day)
            store["reduced"].append(run.days_reduced)
            store["rearms"].append(run.auto_rearms)
    base_dd = np.concatenate(baseline_dd)
    base_wealth = np.concatenate(baseline_wealth)
    result: dict[str, Any] = {
        "paths": total_paths,
        "horizon_days": days,
        "drift_per_day": drift,
        "no_ladder": {
            "max_drawdown": _quantiles(base_dd),
            "mean_terminal_wealth": float(np.mean(base_wealth)),
            "mean_horizon_return": float(np.mean(base_wealth) - 1.0),
        },
    }
    for name, store in per_spec.items():
        dd = np.concatenate(store["dd"])
        wealth = np.concatenate(store["wealth"])
        halted = np.concatenate(store["halted"])
        first = np.concatenate(store["first"])
        reduced = np.concatenate(store["reduced"])
        rearms = np.concatenate(store["rearms"])
        overshoot = dd[halted] - bound if np.any(halted) else np.zeros(0)
        result[name] = {
            "max_drawdown": _quantiles(dd),
            "halt_probability": float(np.mean(halted)),
            "mean_first_halt_day_among_halted": (
                float(np.mean(first[halted])) if np.any(halted) else None
            ),
            "mean_fraction_of_days_reduced": float(np.mean(reduced) / days),
            "mean_auto_rearms_per_path": float(np.mean(rearms)),
            "mean_terminal_wealth": float(np.mean(wealth)),
            "mean_horizon_return": float(np.mean(wealth) - 1.0),
            "mean_horizon_return_cost_vs_no_ladder": float(np.mean(base_wealth) - np.mean(wealth)),
            "overshoot_beyond_bound_on_halted_paths": (
                _quantiles(overshoot) if overshoot.size > 1 else None
            ),
        }
    return result


def check_baseline(
    computed: dict[str, Any], published: dict[str, float], *, label: str
) -> dict[str, Any]:
    """The no-ladder, zero-drift baseline must be the published study's, or nothing is reported."""
    checks = {
        "expected_max_drawdown": (
            computed["expected"],
            published["expected_max_drawdown"],
        ),
        "p95_max_drawdown": (computed["p95"], published["p95_max_drawdown"]),
    }
    for key, (mine, theirs) in checks.items():
        if not math.isclose(mine, theirs, rel_tol=0.0, abs_tol=BASELINE_TOLERANCE):
            raise ValueError(
                f"{label}: regenerated baseline {key}={mine!r} does not reproduce the published "
                f"study's {theirs!r}; the two studies describe different paths"
            )
    return {key: {"regenerated": m, "published": t} for key, (m, t) in checks.items()}


def acceptance(results: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    rule = contract["acceptance_rule"]
    models = ["circular_moving_block_bootstrap_63", "correlation_regime"]
    p95 = max(results[m]["zero_drift"]["absorbing"]["max_drawdown"]["p95"] for m in models)
    p99 = max(results[m]["zero_drift"]["absorbing"]["max_drawdown"]["p99"] for m in models)
    p95_ok = p95 <= float(rule["p95_max_drawdown_with_absorbing_ladder_max"])
    p99_ok = p99 <= float(rule["p99_max_drawdown_with_absorbing_ladder_max"])
    return {
        "rule": rule,
        "conservative_p95_with_absorbing_ladder": p95,
        "conservative_p99_with_absorbing_ladder": p99,
        "p95_within_rule": p95_ok,
        "p99_within_rule": p99_ok,
        "accepted_as_bound_mechanism": p95_ok and p99_ok,
    }


def build() -> dict[str, Any]:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    study = _load_script("drawdown_control_current_book_study", STUDY_SCRIPT)
    published = json.loads(STUDY_RESULT.read_text(encoding="utf-8"))
    admission = json.loads(ADMISSION_CONTRACT.read_text(encoding="utf-8"))
    paper = study._load_script("drawdown_control_paper_state", study.PAPER_STATE_SCRIPT)
    market_module = study._load_script(
        "drawdown_control_market_factor", study.MARKET_FACTOR_IMPLEMENTATION
    )
    live_contract = json.loads(study.LIVE_CONTRACT.read_text(encoding="utf-8"))
    if live_contract["declared_fingerprint"] != published["configuration"]["live_fingerprint"]:
        raise ValueError("published drawdown study is bound to a different live fingerprint")

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
    del market_module  # loaded, as the published study loads it, to bind the same source set
    names = list(book.names)
    contributions = np.column_stack(
        [book.weights[name] * book.sleeve_returns[name] for name in names] + [book.overlay_returns]
    )
    if not np.allclose(np.sum(contributions, axis=1), book.book_returns, atol=1e-15):
        raise ValueError("component contributions do not reconstruct the exact book")
    drift = float(np.mean(book.book_returns))
    centered_book = book.book_returns - drift
    bound = float(contract["bound"])
    # The bound is the owner's (config/owner_goals.json), a bound on REALIZED maximum drawdown.
    # The admission contract's book_expected_max_drawdown_max is the sealed MODELED objective;
    # since 2026-09-14 the two differ (0.10 against 0.11) and are published side by side.
    owner_bound = float(load_owner_goals()["goals"]["combined_max_drawdown"]["bound"])
    if bound != owner_bound:
        raise ValueError("contract bound does not equal the owner's maximum-drawdown bound")
    specs = ladder_specs(contract)
    stress_correlation = float(admission["thresholds"]["stressed_pairwise_correlation_max"])

    def bootstrap() -> Iterator[FloatArray]:
        return bootstrap_batches(
            centered_book,
            paths=study.PATHS,
            horizon_days=study.HORIZON_DAYS,
            block_days=study.PRIMARY_BLOCK_DAYS,
            seed=study.BOOTSTRAP_SEED,
            batch_size=study.BATCH_SIZE,
        )

    def regime() -> Iterator[FloatArray]:
        return regime_batches(
            contributions,
            paths=study.PATHS,
            horizon_days=study.HORIZON_DAYS,
            stress_correlation=stress_correlation,
            stress_share=study.STRESS_SHARE,
            mean_stress_run_days=study.MEAN_STRESS_RUN_DAYS,
            seed=study.REGIME_SEED,
            batch_size=study.BATCH_SIZE,
            nearest_correlation=study._nearest_correlation,
        )

    results: dict[str, Any] = {}
    baseline_checks: dict[str, Any] = {}
    for model, batches, published_model in (
        (
            "circular_moving_block_bootstrap_63",
            bootstrap,
            published["models"]["circular_moving_block_bootstrap"][str(study.PRIMARY_BLOCK_DAYS)],
        ),
        ("correlation_regime", regime, published["models"]["correlation_regime"]),
    ):
        zero = evaluate(
            batches(), drift=0.0, specs=specs, bound=bound, max_drawdowns_fn=study._max_drawdowns
        )
        baseline_checks[model] = check_baseline(
            zero["no_ladder"]["max_drawdown"], published_model, label=model
        )
        with_drift = evaluate(
            batches(), drift=drift, specs=specs, bound=bound, max_drawdowns_fn=study._max_drawdowns
        )
        results[model] = {"zero_drift": zero, "research_window_drift_added_back": with_drift}

    verdict = acceptance(results, contract)
    maturity = json.loads(
        (REPO / "artifacts/engineering/forward_evidence_maturity.json").read_text(encoding="utf-8")
    )
    payload: dict[str, Any] = {
        "schema": "canli.alphac-drawdown-control-study.v1",
        "author": "Arhan Canli",
        "capital_kind": "RESEARCH_SIMULATION_OVER_PAPER_SPECIFICATION",
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "status": (
            "LADDER_ACCEPTED_AS_BOUND_MECHANISM_NOT_LIVE"
            if verdict["accepted_as_bound_mechanism"]
            else "LADDER_DOES_NOT_HOLD_THE_BOUND_AT_THIS_VOLATILITY"
        ),
        "trial_accounting": contract["trial_accounting"],
        "bindings": {
            "contract": {"path": str(CONTRACT.relative_to(REPO)), "sha256": _sha256(CONTRACT)},
            "protocol": {"path": str(PROTOCOL.relative_to(REPO)), "sha256": _sha256(PROTOCOL)},
            "published_study_content_hash": published["content_hash"],
            "live_fingerprint": live_contract["declared_fingerprint"],
            "ladder_implementation_sha256": _sha256(REPO / "src/alphaforge/risk/ladder_paths.py"),
        },
        "ladder": contract["ladder"],
        "bound": bound,
        "calibration": {
            "research_window_daily_mean_return": drift,
            "research_window_annualized_drift": drift * 365.0,
            "observed_book_max_drawdown_research_window": published["calibration"][
                "observed_book_max_drawdown"
            ],
            "window": [published["calibration"]["start"], published["calibration"]["end"]],
        },
        "baseline_reproduction": baseline_checks,
        "results": results,
        "acceptance": verdict,
        "published_measures_separately": {
            "realized_forward_max_drawdown": maturity["drawdown_evidence"][
                "realized_live_max_drawdown"
            ],
            "realized_forward_source": (
                "artifacts/engineering/forward_evidence_maturity.json "
                "drawdown_evidence.realized_live_max_drawdown"
            ),
            "historical_scenario_max_drawdown": published["calibration"][
                "observed_book_max_drawdown"
            ],
            "simulated_expected_no_ladder_conservative": max(
                results[m]["zero_drift"]["no_ladder"]["max_drawdown"]["expected"] for m in results
            ),
            "simulated_p95_no_ladder_conservative": max(
                results[m]["zero_drift"]["no_ladder"]["max_drawdown"]["p95"] for m in results
            ),
            "simulated_expected_with_ladder_conservative": max(
                results[m]["zero_drift"]["absorbing"]["max_drawdown"]["expected"] for m in results
            ),
            "simulated_p95_with_ladder_conservative": verdict[
                "conservative_p95_with_absorbing_ladder"
            ],
        },
        "claim_boundary": (
            "A research simulation over the paper specification, on the published drawdown "
            "study's own paths. It establishes nothing about the live book, which runs no "
            "book-level ladder today; it measures what the declared ladder would do on those "
            "paths and what it would cost. The 11 percent bound holds per drawdown episode up "
            "to a one-day overshoot at half gross; it is a brake, not a guarantee."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verdict = payload["acceptance"]
    print(payload["status"])
    for model, cell in payload["results"].items():
        zero = cell["zero_drift"]
        print(
            f"  {model}: no ladder p95 {zero['no_ladder']['max_drawdown']['p95']:.4f} -> "
            f"absorbing p95 {zero['absorbing']['max_drawdown']['p95']:.4f} "
            f"(p99 {zero['absorbing']['max_drawdown']['p99']:.4f}, halt prob "
            f"{zero['absorbing']['halt_probability']:.3f}); drift-added return cost "
            f"{cell['research_window_drift_added_back']['absorbing']['mean_horizon_return_cost_vs_no_ladder']:.4f}"
        )
    print(
        f"  conservative p95 {verdict['conservative_p95_with_absorbing_ladder']:.4f} / p99 "
        f"{verdict['conservative_p99_with_absorbing_ladder']:.4f}; accepted: "
        f"{verdict['accepted_as_bound_mechanism']}"
    )
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
