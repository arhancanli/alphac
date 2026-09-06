"""Evaluate the ALPHAC paper record against a frozen forward-evidence contract.

The evaluator deliberately separates four ideas that are easy to blur on a website:
an immature record, an estimate, an observed point target, and a statistically
established target. It also keeps realized drawdown separate from modeled expected
maximum drawdown.

Run: ``uv run python scripts/evaluate_forward_evidence_maturity.py``
"""

from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any, Final

import numpy as np
from scipy.stats import kurtosis as scipy_kurtosis
from scipy.stats import skew as scipy_skew

from alphaforge.validation.dsr import probabilistic_sharpe_ratio
from alphaforge.validation.transparency import validate_transparency_document

REPO: Final[Path] = Path(__file__).resolve().parent.parent
CONTRACT_JSON: Final[Path] = REPO / "config" / "forward_evidence_contract.json"
STATE_JSON: Final[Path] = REPO / "data" / "paper" / "state.json"
CONTINUITY_JSON: Final[Path] = REPO / "artifacts" / "engineering" / "record_continuity.json"
BROKER_JSON: Final[Path] = REPO / "artifacts" / "engineering" / "alpaca_broker_reconciliation.json"
DRAWDOWN_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "drawdown_live_estimator" / "result.json"
)
CURRENT_BOOK_DRAWDOWN_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "current_book_drawdown" / "result.json"
)
CURRENT_BOOK_DIVERSIFICATION_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "current_book_diversification" / "result.json"
)
DRAWDOWN_EVIDENCE_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "forward_drawdown_evidence.json"
)
METHODOLOGY_PAPER: Final[Path] = REPO / "docs" / "research" / "FORWARD_SHARPE_EVIDENCE_STANDARD.md"
TRANSPARENCY_JSON: Final[Path] = (
    REPO.parent / "meridian" / "public" / "glassbox" / "transparency_log.json"
)
CRYPTO_ATTRIBUTION_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "crypto_position_attribution.json"
)
CRYPTO_ATTRIBUTION_ROLLOUT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "crypto_position_attribution_rollout_verification.json"
)
OUTPUT_JSON: Final[Path] = REPO / "artifacts" / "engineering" / "forward_evidence_maturity.json"


def _canonical_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must be timezone-aware: {value}")
    return parsed.astimezone(dt.UTC)


def _verified_embedded_hash(payload: dict[str, Any]) -> bool:
    claimed = payload.get("content_hash")
    return isinstance(claimed, str) and claimed == _canonical_hash(payload)


def _curve_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    matches = [row for row in state["algorithms"] if row.get("flagship") is True]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one flagship algorithm; got {len(matches)}")
    curve = matches[0].get("live_curve")
    if not isinstance(curve, list) or len(curve) < 2:
        raise ValueError("flagship live curve needs at least two marks")
    return curve


def _curve_metrics(curve: list[dict[str, Any]]) -> tuple[np.ndarray, float, str, str]:
    dates = [dt.date.fromisoformat(str(point["date"])) for point in curve]
    if any(right <= left for left, right in itertools.pairwise(dates)):
        raise ValueError("flagship curve dates must be unique and strictly increasing")
    equity = np.asarray([float(point["equity"]) for point in curve], dtype=np.float64)
    if not np.all(np.isfinite(equity)) or np.any(equity <= 0.0):
        raise ValueError("flagship equity must be finite and strictly positive")
    returns = equity[1:] / equity[:-1] - 1.0
    running_peak = np.maximum.accumulate(equity)
    realized_max_drawdown = float(np.max(1.0 - equity / running_peak))
    return returns, realized_max_drawdown, dates[0].isoformat(), dates[-1].isoformat()


def _sharpe_evidence(returns: np.ndarray, contract: dict[str, Any]) -> dict[str, Any]:
    n_obs = int(returns.size)
    estimate_min = int(contract["minimum_daily_returns_for_estimate"])
    establish_min = int(contract["minimum_daily_returns_for_establishment"])
    annualization = float(contract["annualization_days"])
    target = float(contract["forward_sharpe_target"])
    probability_min = float(contract["target_exceedance_probability_min"])
    base: dict[str, Any] = {
        "daily_return_observations": n_obs,
        "estimate_minimum": estimate_min,
        "establishment_minimum": establish_min,
        "observations_to_estimate": max(0, estimate_min - n_obs),
        "observations_to_establishment": max(0, establish_min - n_obs),
        "annualization_days": annualization,
        "target": target,
        "target_exceedance_probability_min": probability_min,
        "annualized_point_estimate": None,
        "probability_true_sharpe_exceeds_target": None,
        "target_observed": False,
        "target_statistically_established": False,
    }
    if n_obs < estimate_min:
        base["status"] = "IMMATURE_RECORD_TOO_SHORT"
        return base
    if float(np.ptp(returns)) == 0.0:
        base["status"] = "ESTIMATE_UNAVAILABLE_ZERO_VARIANCE"
        return base

    per_period_sr = float(np.mean(returns) / np.std(returns, ddof=1))
    annualized_sr = per_period_sr * math.sqrt(annualization)
    sample_skew = float(scipy_skew(returns, bias=True))
    sample_kurtosis = float(scipy_kurtosis(returns, fisher=False, bias=True))
    probability = probabilistic_sharpe_ratio(
        sr=per_period_sr,
        n_obs=n_obs,
        skew=sample_skew,
        kurtosis=sample_kurtosis,
        sr_benchmark=target / math.sqrt(annualization),
    )
    observed = annualized_sr >= target
    established = n_obs >= establish_min and observed and probability >= probability_min
    base.update(
        {
            "annualized_point_estimate": annualized_sr,
            "per_period_sharpe": per_period_sr,
            "sample_skew": sample_skew,
            "sample_non_excess_kurtosis": sample_kurtosis,
            "probability_true_sharpe_exceeds_target": probability,
            "target_observed": observed,
            "target_statistically_established": established,
            "status": (
                "TARGET_STATISTICALLY_ESTABLISHED"
                if established
                else "TARGET_OBSERVED_NOT_ESTABLISHED"
                if observed
                else "ESTIMATE_ELIGIBLE_TARGET_NOT_OBSERVED"
            ),
        }
    )
    return base


def evaluate(
    *,
    state: dict[str, Any],
    continuity: dict[str, Any],
    broker: dict[str, Any],
    drawdown: dict[str, Any],
    current_book_drawdown: dict[str, Any],
    current_book_diversification: dict[str, Any],
    drawdown_evidence: dict[str, Any],
    transparency: dict[str, Any],
    crypto_attribution: dict[str, Any],
    crypto_attribution_rollout: dict[str, Any],
    contract: dict[str, Any],
    evaluated_at: dt.datetime,
) -> dict[str, Any]:
    """Return a content-hashed, fail-closed evidence-maturity report."""
    evaluated_at = evaluated_at.astimezone(dt.UTC)
    curve = _curve_from_state(state)
    returns, realized_max_dd, first_mark, last_mark = _curve_metrics(curve)
    live_config = state.get("live_config", {})
    broker_time = _parse_time(str(broker["generated_at"]))
    state_time = _parse_time(str(state["generated_at"]))
    max_age = dt.timedelta(hours=float(contract["broker_reconciliation_max_age_hours"]))
    lag_tolerance = dt.timedelta(hours=float(contract["broker_state_lag_tolerance_hours"]))

    transparency_chain_error: str | None = None
    try:
        transparency_validation = validate_transparency_document(transparency)
    except (KeyError, TypeError, ValueError) as error:
        transparency_validation = None
        transparency_chain_error = str(error)
    transparency_state_error: str | None = None
    try:
        transparency_state_validation = validate_transparency_document(
            transparency, expected_state=state
        )
    except (KeyError, TypeError, ValueError) as error:
        transparency_state_validation = None
        transparency_state_error = str(error)
    crypto_cycle = crypto_attribution.get("latest_cycle") or {}
    crypto_cycle_ts = crypto_cycle.get("cycle_ts")
    crypto_cycle_date = (
        None
        if crypto_cycle_ts is None
        else dt.datetime.fromtimestamp(float(crypto_cycle_ts) / 1000.0, tz=dt.UTC)
        .date()
        .isoformat()
    )

    checks = {
        "paper_capital_only": all(
            row.get("execution", {}).get("capital_kind") == contract["capital_kind"]
            for row in state["algorithms"]
        ),
        "live_config_matches_declaration": live_config.get("matches_declaration") is True,
        "live_config_matches_frozen_evidence_epoch": (
            live_config.get("fingerprint") == contract["required_live_config_fingerprint"]
            and live_config.get("declared_fingerprint")
            == contract["required_live_config_fingerprint"]
        ),
        "continuity_schema": continuity.get("schema") == contract["required_continuity_schema"],
        "continuity_content_hash": _verified_embedded_hash(continuity),
        "continuity_passes": continuity.get("passes") is True,
        "continuity_covers_last_mark": str(continuity.get("as_of")) >= last_mark,
        "broker_schema": broker.get("schema") == contract["required_broker_reconciliation_schema"],
        "broker_content_hash": _verified_embedded_hash(broker),
        "broker_passes": broker.get("summary", {}).get("status") == "PASS"
        and broker.get("summary", {}).get("passes") is True,
        "broker_accounts_are_unique": broker.get("summary", {}).get("unique_dedicated_accounts")
        is True,
        "broker_reconciliation_fresh": dt.timedelta(0) <= evaluated_at - broker_time <= max_age,
        "broker_reconciliation_covers_state": broker_time + lag_tolerance >= state_time,
        "drawdown_model_schema": drawdown.get("schema")
        == contract["required_drawdown_model_schema"],
        "current_book_drawdown_schema": current_book_drawdown.get("schema")
        == contract["required_current_book_drawdown_study_schema"],
        "current_book_drawdown_content_hash": _verified_embedded_hash(
            current_book_drawdown
        ),
        "current_book_drawdown_binds_live_configuration": (
            current_book_drawdown.get("configuration", {}).get("live_fingerprint")
            == contract["required_live_config_fingerprint"]
        ),
        "current_book_drawdown_remains_non_establishing": (
            current_book_drawdown.get("objective", {}).get(
                "live_expected_max_drawdown_established"
            )
            is False
            and bool(current_book_drawdown.get("failed_establishment_dimensions"))
        ),
        "current_book_diversification_schema": (
            current_book_diversification.get("schema")
            == contract["required_current_book_diversification_study_schema"]
        ),
        "current_book_diversification_content_hash": _verified_embedded_hash(
            current_book_diversification
        ),
        "current_book_diversification_binds_live_configuration": (
            current_book_diversification.get("configuration", {}).get("live_fingerprint")
            == contract["required_live_config_fingerprint"]
        ),
        "current_book_diversification_binds_drawdown_bytes": (
            current_book_diversification.get("source_bindings", {})
            .get("current_book_drawdown", {})
            .get("sha256")
            == hashlib.sha256(CURRENT_BOOK_DRAWDOWN_JSON.read_bytes()).hexdigest()
        ),
        "current_book_diversification_remains_non_establishing": (
            current_book_diversification.get("governing_comparison", {}).get(
                "live_forward_diversification_established"
            )
            is False
            and bool(current_book_diversification.get("failed_establishment_dimensions"))
        ),
        "drawdown_evidence_schema": drawdown_evidence.get("schema")
        == contract["required_drawdown_evidence_schema"],
        "drawdown_evidence_content_hash": _verified_embedded_hash(drawdown_evidence),
        "drawdown_evidence_integrity_passes": drawdown_evidence.get("integrity_passes")
        is True,
        "drawdown_evidence_binds_model_bytes": (
            drawdown_evidence.get("source_bindings", {})
            .get("drawdown_model", {})
            .get("sha256")
            == hashlib.sha256(DRAWDOWN_JSON.read_bytes()).hexdigest()
        ),
        "drawdown_evidence_binds_current_book_model_bytes": (
            drawdown_evidence.get("source_bindings", {})
            .get("current_book_drawdown_model", {})
            .get("sha256")
            == hashlib.sha256(CURRENT_BOOK_DRAWDOWN_JSON.read_bytes()).hexdigest()
        ),
        "drawdown_evidence_binds_contract_bytes": (
            drawdown_evidence.get("source_bindings", {})
            .get("forward_contract", {})
            .get("sha256")
            == hashlib.sha256(CONTRACT_JSON.read_bytes()).hexdigest()
        ),
        "drawdown_live_non_equivalence_disclosed": (
            drawdown_evidence.get("production_equivalence", {}).get("passes") is False
            and drawdown_evidence.get("objective", {}).get(
                "live_expected_max_drawdown_established"
            )
            is False
            and drawdown_evidence.get("objective", {}).get(
                "live_p95_max_drawdown_established"
            )
            is False
        ),
        "drawdown_evidence_matches_current_book_model": (
            drawdown_evidence.get("objective", {}).get(
                "current_composition_conservative_expected_max_drawdown"
            )
            == current_book_drawdown.get("objective", {}).get(
                "conservative_modeled_expected_max_drawdown"
            )
            and drawdown_evidence.get("objective", {}).get(
                "current_composition_conservative_p95_max_drawdown"
            )
            == current_book_drawdown.get("objective", {}).get(
                "conservative_modeled_p95_max_drawdown"
            )
        ),
        "transparency_schema": transparency.get("schema")
        == contract["required_transparency_schema"],
        "transparency_payload_schema": (
            transparency.get("payload_disclosure", {}).get("payload_schema")
            == contract["required_transparency_payload_schema"]
        ),
        "transparency_chain_and_signatures_valid": transparency_validation is not None,
        "transparency_head_payload_matches_state": bool(
            transparency_state_validation
            and transparency_state_validation["head_payload_matches_state"] is True
        ),
        "crypto_position_attribution_schema": (
            crypto_attribution.get("schema")
            == contract["required_crypto_position_attribution_schema"]
        ),
        "crypto_position_attribution_content_hash": _verified_embedded_hash(crypto_attribution),
        "crypto_position_attribution_complete": (
            crypto_attribution.get("status") == "COMPLETE"
            and crypto_attribution.get("passes") is True
        ),
        "crypto_position_attribution_reconciles_equity": (
            crypto_cycle.get("reconciliation_passes") is True
        ),
        "crypto_position_attribution_reproduces_position_arithmetic": (
            crypto_cycle.get("position_arithmetic_passes") is True
        ),
        "crypto_position_attribution_covers_last_mark": (
            crypto_cycle_date is not None and crypto_cycle_date >= last_mark
        ),
        "crypto_position_attribution_rollout_schema": (
            crypto_attribution_rollout.get("schema")
            == contract["required_crypto_position_attribution_rollout_schema"]
        ),
        "crypto_position_attribution_rollout_content_hash": _verified_embedded_hash(
            crypto_attribution_rollout
        ),
        "crypto_position_attribution_rollout_verified": (
            crypto_attribution_rollout.get("status") == "VERIFIED_FIRST_NATURAL_MARKED_CYCLE"
            and crypto_attribution_rollout.get("passes") is True
            and crypto_attribution_rollout.get("natural_cycle_after_deployment") is True
            and crypto_attribution_rollout.get("remote_query_performed") is True
            and (crypto_attribution_rollout.get("attribution") or {}).get("status") == "COMPLETE"
            and (crypto_attribution_rollout.get("attribution") or {}).get("passes") is True
        ),
    }
    provenance_passes = all(checks.values())
    sharpe = _sharpe_evidence(returns, contract)
    if not provenance_passes:
        sharpe["underlying_status"] = sharpe["status"]
        sharpe["status"] = "FAIL_CLOSED_PROVENANCE"
        sharpe["target_statistically_established"] = False

    drawdown_objective = drawdown_evidence["objective"]
    expected_dd = float(
        drawdown_objective["study_production_labelled_expected_max_drawdown"]
    )
    p95_dd = float(drawdown_objective["study_production_labelled_p95_max_drawdown"])
    current_expected_dd = float(
        drawdown_objective["current_composition_conservative_expected_max_drawdown"]
    )
    current_p95_dd = float(
        drawdown_objective["current_composition_conservative_p95_max_drawdown"]
    )
    dd_target = float(contract["expected_max_drawdown_target"])
    if float(drawdown_objective["expected_max_drawdown_target"]) != dd_target:
        raise ValueError("sealed drawdown target differs from the forward contract")
    diversification = current_book_diversification["governing_comparison"]
    observed_diversification = current_book_diversification["observed"]

    payload: dict[str, Any] = {
        "schema": "canli.alphac-forward-evidence-maturity.v1",
        "generated_at": evaluated_at.isoformat(),
        "author": "Arhan Canli",
        "capital_kind": contract["capital_kind"],
        "status": sharpe["status"],
        "provenance_gate": {
            "passes": provenance_passes,
            "checks": checks,
            "failed_checks": [name for name, passes in checks.items() if not passes],
            "transparency_chain_validation_error": transparency_chain_error,
            "transparency_state_validation_error": transparency_state_error,
        },
        "record": {
            "first_mark": first_mark,
            "last_mark": last_mark,
            "curve_points": len(curve),
            "daily_return_observations": int(returns.size),
            "cumulative_return": float(curve[-1]["equity"] / curve[0]["equity"] - 1.0),
            "return_frequency": contract["return_frequency"],
            "configuration_fingerprint": live_config.get("fingerprint"),
        },
        "sharpe_evidence": sharpe,
        "drawdown_evidence": {
            "realized_live_max_drawdown": realized_max_dd,
            "realized_status": "DESCRIPTIVE_TO_DATE_NOT_EXPECTED_MAX_DRAWDOWN",
            "expected_max_drawdown_target": dd_target,
            "study_production_labelled_expected_max_drawdown": expected_dd,
            "study_production_labelled_p95_max_drawdown": p95_dd,
            "current_composition_conservative_expected_max_drawdown": (
                current_expected_dd
            ),
            "current_composition_conservative_p95_max_drawdown": current_p95_dd,
            "current_composition_study_status": current_book_drawdown["status"],
            "current_composition_expected_within_objective": (
                current_expected_dd <= dd_target
            ),
            "current_composition_p95_within_objective": current_p95_dd <= dd_target,
            "current_composition_failed_establishment_dimensions": (
                current_book_drawdown["failed_establishment_dimensions"]
            ),
            "study_status": drawdown_evidence["status"],
            "production_equivalence_passes": drawdown_evidence[
                "production_equivalence"
            ]["passes"],
            "production_equivalence_failed_checks": drawdown_evidence[
                "production_equivalence"
            ]["failed_checks"],
            "objective_status": (
                "MODELED_CURRENT_COMPOSITION_WITHIN_OBJECTIVE_"
                "LIVE_EXPECTED_MAX_DRAWDOWN_NOT_ESTABLISHED"
                if current_expected_dd <= dd_target
                else "MODELED_CURRENT_COMPOSITION_EXCEEDS_OBJECTIVE_"
                "LIVE_EXPECTED_MAX_DRAWDOWN_NOT_ESTABLISHED"
            ),
        },
        "diversification_evidence": {
            "study_status": current_book_diversification["status"],
            "current_sleeves": int(diversification["current_sleeves"]),
            "target_total_sleeves": int(diversification["target_total_sleeves"]),
            "average_pairwise_correlation": float(
                observed_diversification["average_pairwise_correlation"]
            ),
            "average_pairwise_correlation_objective": float(
                diversification["average_pairwise_correlation_objective"]
            ),
            "active_v7_has_no_global_average_correlation_point_gate": bool(
                diversification["active_v7_has_no_global_average_correlation_point_gate"]
            ),
            "active_v7_candidate_average_correlation_gate": float(
                diversification["active_v7_candidate_average_correlation_gate"]
            ),
            "historical_v6_global_average_correlation_point_gate": float(
                diversification["historical_v6_global_average_correlation_point_gate"]
            ),
            "average_pairwise_upper_95": float(
                diversification["average_pairwise_upper_95"]
            ),
            "average_pairwise_upper_95_gate": float(
                diversification["average_pairwise_correlation_upper_95_gate"]
            ),
            "maximum_pairwise_correlation": float(
                observed_diversification["maximum_pairwise_correlation"]
            ),
            "maximum_pairwise_upper_95": float(
                diversification["maximum_pairwise_upper_95"]
            ),
            "stressed_pairwise_design_value_not_observed": float(
                diversification["stressed_pairwise_design_value_not_observed"]
            ),
            "diversification_ratio_sleeves_only": float(
                observed_diversification["diversification_ratio_sleeves_only"]
            ),
            "effective_independent_sleeves_participation_ratio": float(
                observed_diversification[
                    "effective_independent_sleeves_participation_ratio"
                ]
            ),
            "marginal_book_sharpe_research_diagnostics": observed_diversification[
                "marginal_book_sharpe_research_diagnostics"
            ],
            "checks": diversification["checks"],
            "passes_all_active_v7_risk_comparisons": diversification[
                "passes_all_active_v7_risk_comparisons"
            ],
            "live_forward_diversification_established": False,
            "failed_establishment_dimensions": current_book_diversification[
                "failed_establishment_dimensions"
            ],
            "objective_status": (
                "CURRENT_COMPOSITION_AVERAGE_CORRELATION_OBJECTIVE_MET_"
                "LIVE_FORWARD_NOT_ESTABLISHED"
                if diversification["meets_active_correlation_objective"]
                else "CURRENT_COMPOSITION_AVERAGE_CORRELATION_OBJECTIVE_GAP_"
                "LIVE_FORWARD_NOT_ESTABLISHED"
            ),
        },
        "source_bindings": {
            "contract": {"path": str(CONTRACT_JSON.relative_to(REPO))},
            "paper_state": {"path": str(STATE_JSON.relative_to(REPO))},
            "record_continuity": {"path": str(CONTINUITY_JSON.relative_to(REPO))},
            "broker_reconciliation": {"path": str(BROKER_JSON.relative_to(REPO))},
            "drawdown_model": {"path": str(DRAWDOWN_JSON.relative_to(REPO))},
            "current_book_drawdown": {
                "path": str(CURRENT_BOOK_DRAWDOWN_JSON.relative_to(REPO))
            },
            "current_book_diversification": {
                "path": str(CURRENT_BOOK_DIVERSIFICATION_JSON.relative_to(REPO))
            },
            "drawdown_evidence": {
                "path": str(DRAWDOWN_EVIDENCE_JSON.relative_to(REPO))
            },
            "methodology_paper": {"path": str(METHODOLOGY_PAPER.relative_to(REPO))},
            "transparency_chain": {"path": str(TRANSPARENCY_JSON.relative_to(REPO.parent))},
            "crypto_position_attribution": {"path": str(CRYPTO_ATTRIBUTION_JSON.relative_to(REPO))},
            "crypto_position_attribution_rollout": {
                "path": str(CRYPTO_ATTRIBUTION_ROLLOUT_JSON.relative_to(REPO))
            },
        },
        "claim_boundary": (
            "Paper-only, self-published evidence. An immature or observed Sharpe is not an "
            "established Sharpe. Realized maximum drawdown is not expected maximum drawdown, "
            "and the modeled expectation is not a live guarantee."
        ),
    }
    for binding, path in (
        ("contract", CONTRACT_JSON),
        ("paper_state", STATE_JSON),
        ("record_continuity", CONTINUITY_JSON),
        ("broker_reconciliation", BROKER_JSON),
        ("drawdown_model", DRAWDOWN_JSON),
        ("current_book_drawdown", CURRENT_BOOK_DRAWDOWN_JSON),
        ("current_book_diversification", CURRENT_BOOK_DIVERSIFICATION_JSON),
        ("drawdown_evidence", DRAWDOWN_EVIDENCE_JSON),
        ("methodology_paper", METHODOLOGY_PAPER),
        ("transparency_chain", TRANSPARENCY_JSON),
        ("crypto_position_attribution", CRYPTO_ATTRIBUTION_JSON),
        ("crypto_position_attribution_rollout", CRYPTO_ATTRIBUTION_ROLLOUT_JSON),
    ):
        payload["source_bindings"][binding]["sha256"] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    payload["content_hash"] = _canonical_hash(payload)
    return payload


def main(output: Path = OUTPUT_JSON, *, evaluated_at: dt.datetime | None = None) -> Path:
    payload = evaluate(
        state=json.loads(STATE_JSON.read_text()),
        continuity=json.loads(CONTINUITY_JSON.read_text()),
        broker=json.loads(BROKER_JSON.read_text()),
        drawdown=json.loads(DRAWDOWN_JSON.read_text()),
        current_book_drawdown=json.loads(CURRENT_BOOK_DRAWDOWN_JSON.read_text()),
        current_book_diversification=json.loads(
            CURRENT_BOOK_DIVERSIFICATION_JSON.read_text()
        ),
        drawdown_evidence=json.loads(DRAWDOWN_EVIDENCE_JSON.read_text()),
        transparency=json.loads(TRANSPARENCY_JSON.read_text()),
        crypto_attribution=json.loads(CRYPTO_ATTRIBUTION_JSON.read_text()),
        crypto_attribution_rollout=json.loads(CRYPTO_ATTRIBUTION_ROLLOUT_JSON.read_text()),
        contract=json.loads(CONTRACT_JSON.read_text()),
        evaluated_at=evaluated_at or dt.datetime.now(tz=dt.UTC),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    return output


if __name__ == "__main__":
    print(main())
