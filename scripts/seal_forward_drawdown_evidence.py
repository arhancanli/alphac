#!/usr/bin/env python3
"""Seal the drawdown study and expose its exact live-equivalence boundary."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
from pathlib import Path
from typing import Any, Final

from alphaforge.portfolio.strategy import BlendStrategy

REPO: Final[Path] = Path(__file__).resolve().parents[1]
MODEL: Final[Path] = REPO / "artifacts/analysis/drawdown_live_estimator/result.json"
CURRENT_BOOK_MODEL: Final[Path] = (
    REPO / "artifacts/analysis/current_book_drawdown/result.json"
)
FORWARD_CONTRACT: Final[Path] = REPO / "config/forward_evidence_contract.json"
ADMISSION_CONTRACT: Final[Path] = REPO / "config/sleeve_admission_contract.json"
LIVE_CHANGE_CONTRACT: Final[Path] = REPO / "config/live_change_contract.json"
ANALYZER: Final[Path] = REPO / "scripts/analyze_drawdown_live_estimator.py"
STRATEGY: Final[Path] = REPO / "src/alphaforge/portfolio/strategy.py"
COVARIANCE: Final[Path] = REPO / "src/alphaforge/portfolio/covariance.py"
OUTPUT: Final[Path] = REPO / "artifacts/engineering/forward_drawdown_evidence.json"

EXPECTED_PARAMETERS: Final[dict[str, Any]] = {
    "mean_run_days": 40.0,
    "min_periods_fraction": 1.0 / 3.0,
    "paths": 96,
    "rho_calm": -0.02,
    "rho_stress": 0.5,
    "s_bar": 0.469,
    "seed": 20260822,
    "sleeves": 14,
    "stress_share": 0.12,
    "vol_target": 0.1,
    "years": 2,
}
PRODUCTION_CELL: Final[dict[str, int]] = {
    "window_bars": 720,
    "seed_rows": 240,
    "halflife_bars": 720,
}
REQUIRED_MODEL_ROW_FIELDS: Final[tuple[str, ...]] = (
    "expected_max_drawdown",
    "median_max_drawdown",
    "p95_max_drawdown",
    "max_drawdown_stderr",
    "realized_book_sharpe",
    "realized_book_vol",
    "overlay_gross_turnover_per_year",
)
CURRENT_BOOK_FAILED_DIMENSIONS: Final[tuple[str, ...]] = (
    "COMMON_WINDOW_BEGINS_AFTER_COVID_AND_2022",
    "ABSENT_CRISIS_CANNOT_APPEAR_IN_BLOCK_BOOTSTRAP",
    "REGIME_MODEL_HAS_NO_STRESS_VOLATILITY_MULTIPLIER",
    "CONSTITUENT_INSTRUMENT_AND_LADDER_STATE_NOT_REPLAYED",
    "EXECUTION_GAPS_AND_LIQUIDITY_FEEDBACK_NOT_MODELED",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    body = {name: value for name, value in payload.items() if name != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _same_row(left: dict[str, Any], right: dict[str, Any]) -> bool:
    fields = (*PRODUCTION_CELL, *REQUIRED_MODEL_ROW_FIELDS)
    return all(left.get(name) == right.get(name) for name in fields)


def _validate_model(model: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if model.get("schema") != "canli.alphac-drawdown-live-estimator.v1":
        raise ValueError("unexpected drawdown model schema")
    if model.get("parameters") != EXPECTED_PARAMETERS:
        raise ValueError("drawdown simulation design drifted")
    grid = model.get("grid")
    if not isinstance(grid, list) or len(grid) != 11:
        raise ValueError("drawdown grid must contain the eleven sealed configurations")
    identities = {
        (row.get("window_bars"), row.get("seed_rows"), row.get("halflife_bars"))
        for row in grid
    }
    if len(identities) != len(grid):
        raise ValueError("drawdown grid contains duplicate configuration identities")
    for row in grid:
        values = [row.get(name) for name in REQUIRED_MODEL_ROW_FIELDS]
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
            raise ValueError("drawdown grid contains non-finite model output")
        if not (
            0.0 <= row["median_max_drawdown"]
            <= row["expected_max_drawdown"]
            <= row["p95_max_drawdown"]
            < 1.0
        ):
            raise ValueError("drawdown quantiles are unordered or outside [0, 1)")
        if row["max_drawdown_stderr"] <= 0.0 or row["realized_book_vol"] <= 0.0:
            raise ValueError("drawdown uncertainty and volatility must be positive")

    production_matches = [
        row
        for row in grid
        if all(row.get(name) == value for name, value in PRODUCTION_CELL.items())
    ]
    if len(production_matches) != 1 or not _same_row(
        production_matches[0], model.get("production_setting", {})
    ):
        raise ValueError("production-labelled drawdown cell is not uniquely bound to the grid")
    best = min(grid, key=lambda row: row["expected_max_drawdown"])
    if not _same_row(best, model.get("best_expected_max_drawdown", {})):
        raise ValueError("best drawdown cell does not reconcile to the grid")
    if not math.isclose(
        model.get("improvement_vs_production", math.nan),
        production_matches[0]["expected_max_drawdown"] - best["expected_max_drawdown"],
        rel_tol=0.0,
        abs_tol=1e-15,
    ):
        raise ValueError("drawdown improvement arithmetic does not reconcile")

    twin = model.get("twin_verification")
    if not isinstance(twin, list) or len(twin) != len(grid):
        raise ValueError("estimator twin coverage does not match the grid")
    twin_ids = {
        (row.get("window"), row.get("seed"), row.get("halflife")) for row in twin
    }
    if twin_ids != identities or any(
        not isinstance(row.get("max_abs_error"), (int, float))
        or not math.isfinite(row["max_abs_error"])
        or row["max_abs_error"] > 1e-12
        for row in twin
    ):
        raise ValueError("vectorized estimator twin is not proved across every grid cell")
    return production_matches[0], best


def _validate_current_book_model(
    model: dict[str, Any], live_change_contract: dict[str, Any], objective: float
) -> tuple[float, float]:
    if model.get("schema") != "canli.alphac-current-book-drawdown-study.v1":
        raise ValueError("unexpected current-book drawdown model schema")
    if model.get("content_hash") != _content_hash(model):
        raise ValueError("current-book drawdown model content hash is invalid")
    declared_fingerprint = live_change_contract["declared_fingerprint"]
    declared_aggregation = live_change_contract["declared_surface"][
        "book_aggregation_settings"
    ]
    if (
        model.get("configuration", {}).get("live_fingerprint")
        != declared_fingerprint
        or model.get("configuration", {}).get("aggregation")
        != declared_aggregation
    ):
        raise ValueError("current-book drawdown model does not bind the live specification")
    design = model.get("design", {})
    if design != {
        "paths_per_model": 10_000,
        "horizon_calendar_days": 730,
        "bootstrap_seed": 20260823,
        "bootstrap_primary_block_days": 63,
        "bootstrap_sensitivity_block_days": [21, 63, 126],
        "regime_seed": 20260824,
        "regime_stress_share": 0.12,
        "regime_mean_stress_run_days": 40.0,
        "regime_stress_correlation": 0.5,
        "regime_component_means": "ZERO",
    }:
        raise ValueError("current-book drawdown protocol drifted")
    model_objective = model.get("objective", {})
    expected = model_objective.get("conservative_modeled_expected_max_drawdown")
    p95 = model_objective.get("conservative_modeled_p95_max_drawdown")
    if (
        model_objective.get("expected_max_drawdown_target") != objective
        or not isinstance(expected, (int, float))
        or not isinstance(p95, (int, float))
        or not math.isfinite(expected)
        or not math.isfinite(p95)
        or not 0.0 < expected <= p95 < 1.0
        or model_objective.get("live_expected_max_drawdown_established") is not False
    ):
        raise ValueError("current-book drawdown objective is invalid")
    if model.get("failed_establishment_dimensions") != list(
        CURRENT_BOOK_FAILED_DIMENSIONS
    ):
        raise ValueError("current-book failed establishment dimensions drifted")
    source_bindings = model.get("source_bindings", {})
    for key, path in (
        ("live_contract", LIVE_CHANGE_CONTRACT),
        ("admission_contract", ADMISSION_CONTRACT),
        ("paper_state_builder", REPO / "scripts/paper_trading_state.py"),
        ("book_implementation", REPO / "src/alphaforge/portfolio/book.py"),
    ):
        if source_bindings.get(key, {}).get("sha256") != _sha256(path):
            raise ValueError(f"current-book drawdown source drift: {key}")
    return float(expected), float(p95)


def build(
    *,
    model: dict[str, Any] | None = None,
    forward_contract: dict[str, Any] | None = None,
    admission_contract: dict[str, Any] | None = None,
    live_change_contract: dict[str, Any] | None = None,
    current_book_model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model = model or json.loads(MODEL.read_text(encoding="utf-8"))
    forward_contract = forward_contract or json.loads(
        FORWARD_CONTRACT.read_text(encoding="utf-8")
    )
    admission_contract = admission_contract or json.loads(
        ADMISSION_CONTRACT.read_text(encoding="utf-8")
    )
    live_change_contract = live_change_contract or json.loads(
        LIVE_CHANGE_CONTRACT.read_text(encoding="utf-8")
    )
    current_book_model = current_book_model or json.loads(
        CURRENT_BOOK_MODEL.read_text(encoding="utf-8")
    )
    production, best = _validate_model(model)
    objective = float(forward_contract["expected_max_drawdown_target"])
    admission_objective = admission_contract["objective"]
    if (
        objective != float(admission_objective["portfolio_max_drawdown_target"])
        or objective
        != float(admission_contract["thresholds"]["book_expected_max_drawdown_max"])
        or admission_objective["portfolio_max_drawdown_statistic"]
        != "expected_maximum_drawdown"
        or admission_objective["portfolio_p95_max_drawdown_must_be_published"] is not True
        or admission_objective["portfolio_p95_max_drawdown_is_gated"] is not False
    ):
        raise ValueError("drawdown objective or p95 disclosure policy drifted")
    current_expected, current_p95 = _validate_current_book_model(
        current_book_model, live_change_contract, objective
    )

    live = live_change_contract["declared_surface"]
    live_strategy = live["strategy_settings"]
    signature = inspect.signature(BlendStrategy.__init__).parameters
    code_defaults = {
        "cov_window_bars": signature["cov_window_bars"].default,
        "cov_halflife_days": signature["cov_halflife_days"].default,
        "cov_min_periods": signature["cov_min_periods"].default,
        "realized_vol_halflife_bars": signature[
            "realized_vol_halflife_bars"
        ].default,
    }
    declared_defaults = {name: live_strategy[name] for name in code_defaults}
    if code_defaults != declared_defaults or code_defaults != {
        "cov_window_bars": 720,
        "cov_halflife_days": None,
        "cov_min_periods": 240,
        "realized_vol_halflife_bars": 240,
    }:
        raise ValueError("declared live covariance defaults do not match production code")
    live_sleeves = live["book_composition"]["sleeves"]
    constituent_vol_target = float(live["risk_path_settings"]["vol_target_ann"])
    aggregation = live["book_aggregation_settings"]
    if (
        aggregation.get("scheme") != "fixed"
        or aggregation.get("book_level_vol_target_ann") is not None
        or aggregation.get("book_level_drawdown_ladder") is not None
        or aggregation.get("strategic_overlay_is_book_vol_scaled") is not False
        or aggregation.get("missing_mark_policy")
        != "ZERO_CONTRIBUTION_ON_MISSING_DAILY_SLEEVE_MARK"
    ):
        raise ValueError("declared live flagship aggregation policy drifted")
    model_equivalence_checks = {
        "sleeve_count_matches_live_book": model["parameters"]["sleeves"]
        == len(live_sleeves),
        "book_level_volatility_target_matches_live_composite": False,
        "book_level_risk_overlay_matches_live_composite": False,
        "single_daily_timebase_matches_mixed_live_timebases": False,
        "covariance_halflife_has_one_duration_across_live_sleeves": False,
        "production_shrinkage_is_inside_simulation": False,
    }
    production_equivalent = all(model_equivalence_checks.values())
    if production_equivalent:
        raise ValueError("known live-equivalence gaps unexpectedly disappeared")

    expected_within = production["expected_max_drawdown"] <= objective
    tail_within = production["p95_max_drawdown"] <= objective
    payload: dict[str, Any] = {
        "schema": "canli.alphac-forward-drawdown-evidence.v1",
        "author": "Arhan Canli",
        "capital_kind": "PAPER_ONLY",
        "integrity_passes": True,
        "status": (
            "CURRENT_COMPOSITION_EXPECTED_WITHIN_OBJECTIVE_LIVE_NOT_ESTABLISHED"
            if current_expected <= objective
            else "CURRENT_COMPOSITION_EXPECTED_EXCEEDS_OBJECTIVE_LIVE_NOT_ESTABLISHED"
        ),
        "objective": {
            "expected_max_drawdown_target": objective,
            "study_production_labelled_expected_max_drawdown": production[
                "expected_max_drawdown"
            ],
            "study_production_labelled_p95_max_drawdown": production[
                "p95_max_drawdown"
            ],
            "study_expected_within_objective": expected_within,
            "study_p95_within_objective": tail_within,
            "current_composition_conservative_expected_max_drawdown": current_expected,
            "current_composition_conservative_p95_max_drawdown": current_p95,
            "current_composition_expected_within_objective": current_expected <= objective,
            "current_composition_p95_within_objective": current_p95 <= objective,
            "live_expected_max_drawdown_established": False,
            "live_p95_max_drawdown_established": False,
        },
        "study_design": model["parameters"],
        "study_production_labelled_cell": production,
        "study_best_cell_not_live_authorized": best,
        "current_book_study": {
            "status": current_book_model["status"],
            "calibration": current_book_model["calibration"],
            "design": current_book_model["design"],
            "failed_establishment_dimensions": current_book_model[
                "failed_establishment_dimensions"
            ],
            "content_hash": current_book_model["content_hash"],
        },
        "production_equivalence": {
            "passes": production_equivalent,
            "checks": model_equivalence_checks,
            "failed_checks": [
                name for name, passes in model_equivalence_checks.items() if not passes
            ],
            "declared_live_sleeves": len(live_sleeves),
            "declared_constituent_blend_strategy_volatility_target": (
                constituent_vol_target
            ),
            "declared_live_book_level_volatility_target": aggregation[
                "book_level_vol_target_ann"
            ],
            "declared_live_book_level_drawdown_ladder": aggregation[
                "book_level_drawdown_ladder"
            ],
            "declared_live_book_aggregation": aggregation,
            "declared_live_strategy_defaults": declared_defaults,
        },
        "source_bindings": {
            "current_book_drawdown_model": {
                "path": str(CURRENT_BOOK_MODEL.relative_to(REPO)),
                "sha256": _sha256(CURRENT_BOOK_MODEL),
            },
            "drawdown_model": {
                "path": str(MODEL.relative_to(REPO)),
                "sha256": _sha256(MODEL),
            },
            "forward_contract": {
                "path": str(FORWARD_CONTRACT.relative_to(REPO)),
                "sha256": _sha256(FORWARD_CONTRACT),
            },
            "admission_contract": {
                "path": str(ADMISSION_CONTRACT.relative_to(REPO)),
                "sha256": _sha256(ADMISSION_CONTRACT),
            },
            "live_change_contract": {
                "path": str(LIVE_CHANGE_CONTRACT.relative_to(REPO)),
                "sha256": _sha256(LIVE_CHANGE_CONTRACT),
            },
            "analyzer": {
                "path": str(ANALYZER.relative_to(REPO)),
                "sha256": _sha256(ANALYZER),
            },
            "strategy": {
                "path": str(STRATEGY.relative_to(REPO)),
                "sha256": _sha256(STRATEGY),
            },
            "covariance_estimator": {
                "path": str(COVARIANCE.relative_to(REPO)),
                "sha256": _sha256(COVARIANCE),
            },
        },
        "claim_boundary": (
            "The sealed study cell is a 96-path, two-year, fourteen-sleeve, daily simulation at "
            "a 10% book-level volatility target. It is not an estimate of today's four-sleeve, "
            "mixed-timebase, fixed-weight live paper composite, which applies no second "
            "book-level volatility target or drawdown ladder after constituent sizing. The "
            "10.25% study expectation and 18.76% study p95 remain published. A separate "
            "zero-drift current-composition study maps the exact fixed weights and overlay at "
            "9.32% conservative expected and 16.45% p95 maximum drawdown. That stronger model "
            "still does not establish live expected or tail maximum drawdown because its common "
            "history begins after COVID and 2022 and it does not replay constituent instrument, "
            "execution-gap or ladder state."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "content_hash": payload["content_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
