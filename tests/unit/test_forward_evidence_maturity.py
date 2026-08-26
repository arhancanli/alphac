from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from alphaforge.validation.transparency import (
    GENESIS,
    PAYLOAD_SCHEMA,
    TRANSPARENCY_SCHEMA,
    canonical_json,
    daily_track_record_payload,
    sha256_hex,
)

REPO = Path(__file__).resolve().parents[2]


def _module():
    path = REPO / "scripts" / "evaluate_forward_evidence_maturity.py"
    spec = importlib.util.spec_from_file_location("forward_evidence_maturity_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def evaluator():
    return _module()


def _curve(returns: list[float]) -> list[dict[str, Any]]:
    equity = 100_000.0
    start = dt.date(2023, 1, 1)
    points: list[dict[str, Any]] = [{"date": start.isoformat(), "equity": equity}]
    for offset, value in enumerate(returns, start=1):
        equity *= 1.0 + value
        points.append({"date": (start + dt.timedelta(days=offset)).isoformat(), "equity": equity})
    return points


def _inputs(evaluator, returns: list[float]) -> dict[str, Any]:
    contract = json.loads(evaluator.CONTRACT_JSON.read_text())
    fingerprint = contract["required_live_config_fingerprint"]
    curve = _curve(returns)
    generated = dt.datetime(2026, 1, 1, 12, tzinfo=dt.UTC)
    state = {
        "generated_at": generated.isoformat(),
        "go_live_date": curve[0]["date"],
        "live_curve": curve,
        "book": {"sleeves": [], "strategic_tilt": None},
        "live_config": {
            "fingerprint": fingerprint,
            "declared_fingerprint": fingerprint,
            "matches_declaration": True,
        },
        "algorithms": [
            {
                "key": "alphac",
                "flagship": True,
                "live_curve": curve,
                "execution": {"capital_kind": "PAPER_ONLY"},
            }
        ],
    }
    continuity = {
        "schema": contract["required_continuity_schema"],
        "as_of": curve[-1]["date"],
        "passes": True,
    }
    continuity["content_hash"] = evaluator._canonical_hash(continuity)
    broker = {
        "schema": contract["required_broker_reconciliation_schema"],
        "generated_at": generated.isoformat(),
        "summary": {
            "status": "PASS",
            "passes": True,
            "unique_dedicated_accounts": True,
        },
    }
    broker["content_hash"] = evaluator._canonical_hash(broker)
    drawdown = {
        "schema": contract["required_drawdown_model_schema"],
        "production_setting": {
            "expected_max_drawdown": 0.10,
            "p95_max_drawdown": 0.18,
        },
    }
    current_book_drawdown = {
        "schema": contract["required_current_book_drawdown_study_schema"],
        "status": (
            "CURRENT_COMPOSITION_EXPECTED_WITHIN_OBJECTIVE_"
            "HISTORICAL_TAIL_COVERAGE_INCOMPLETE"
        ),
        "configuration": {"live_fingerprint": fingerprint},
        "objective": {
            "conservative_modeled_expected_max_drawdown": 0.09,
            "conservative_modeled_p95_max_drawdown": 0.16,
            "live_expected_max_drawdown_established": False,
        },
        "failed_establishment_dimensions": ["HISTORICAL_TAIL_COVERAGE_INCOMPLETE"],
    }
    current_book_drawdown["content_hash"] = evaluator._canonical_hash(
        current_book_drawdown
    )
    current_book_diversification = {
        "schema": contract["required_current_book_diversification_study_schema"],
        "status": "CURRENT_COMPOSITION_DIVERSIFICATION_OBJECTIVE_GAP_RESEARCH_ONLY",
        "configuration": {"live_fingerprint": fingerprint},
        "observed": {
            "average_pairwise_correlation": 0.02,
            "maximum_pairwise_correlation": 0.21,
            "diversification_ratio_sleeves_only": 1.8,
            "effective_independent_sleeves_participation_ratio": 3.9,
            "marginal_book_sharpe_research_diagnostics": {},
        },
        "governing_comparison": {
            "current_sleeves": 4,
            "target_total_sleeves": 14,
            "average_pairwise_correlation_objective": -0.03,
            "active_v7_has_no_global_average_correlation_point_gate": True,
            "active_v7_candidate_average_correlation_gate": 0.0,
            "historical_v6_global_average_correlation_point_gate": 0.0,
            "historical_v6_global_average_correlation_point_check": False,
            "average_pairwise_upper_95": 0.05,
            "average_pairwise_correlation_upper_95_gate": 0.1,
            "maximum_pairwise_upper_95": 0.30,
            "stressed_pairwise_design_value_not_observed": 0.5,
            "checks": {
                "minimum_correlation_observations": True,
                "average_pairwise_upper_95": True,
                "ordinary_pairwise_point": True,
                "ordinary_pairwise_upper_95": True,
                "stressed_pairwise_design": True,
            },
            "passes_all_active_v7_risk_comparisons": True,
            "meets_active_correlation_objective": False,
            "live_forward_diversification_established": False,
        },
        "failed_establishment_dimensions": ["RESEARCH_WINDOW_NOT_FORWARD"],
        "source_bindings": {
            "current_book_drawdown": {
                "sha256": hashlib.sha256(
                    evaluator.CURRENT_BOOK_DRAWDOWN_JSON.read_bytes()
                ).hexdigest()
            }
        },
    }
    current_book_diversification["content_hash"] = evaluator._canonical_hash(
        current_book_diversification
    )
    drawdown_evidence = {
        "schema": contract["required_drawdown_evidence_schema"],
        "integrity_passes": True,
        "status": "CURRENT_COMPOSITION_EXPECTED_WITHIN_OBJECTIVE_LIVE_NOT_ESTABLISHED",
        "objective": {
            "expected_max_drawdown_target": contract["expected_max_drawdown_target"],
            "study_production_labelled_expected_max_drawdown": 0.10,
            "study_production_labelled_p95_max_drawdown": 0.18,
            "current_composition_conservative_expected_max_drawdown": 0.09,
            "current_composition_conservative_p95_max_drawdown": 0.16,
            "live_expected_max_drawdown_established": False,
            "live_p95_max_drawdown_established": False,
        },
        "production_equivalence": {
            "passes": False,
            "failed_checks": ["volatility_target_matches_live_book"],
        },
        "source_bindings": {
            "current_book_drawdown_model": {
                "sha256": hashlib.sha256(
                    evaluator.CURRENT_BOOK_DRAWDOWN_JSON.read_bytes()
                ).hexdigest()
            },
            "drawdown_model": {
                "sha256": hashlib.sha256(evaluator.DRAWDOWN_JSON.read_bytes()).hexdigest()
            },
            "forward_contract": {
                "sha256": hashlib.sha256(evaluator.CONTRACT_JSON.read_bytes()).hexdigest()
            },
        },
    }
    drawdown_evidence["content_hash"] = evaluator._canonical_hash(drawdown_evidence)
    key = Ed25519PrivateKey.generate()
    payload = daily_track_record_payload(state)
    payload_hash = sha256_hex(canonical_json(payload))
    date = curve[-1]["date"]
    chain_hash = sha256_hex(f"{GENESIS}|{payload_hash}|{date}|0".encode())
    entry = {
        "seq": 0,
        "date": date,
        "generated_at": generated.isoformat(),
        "payload_sha256": payload_hash,
        "prev_chain_hash": GENESIS,
        "chain_hash": chain_hash,
        "signature": key.sign(bytes.fromhex(chain_hash)).hex(),
        "payload_schema": PAYLOAD_SCHEMA,
        "payload": payload,
        "event": "PAYLOAD_DISCLOSURE_UPGRADE",
    }
    transparency = {
        "schema": TRANSPARENCY_SCHEMA,
        "public_key_ed25519_hex": key.public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
        .hex(),
        "entries": [entry],
        "payload_disclosure": {
            "payload_schema": PAYLOAD_SCHEMA,
            "first_disclosed_seq": 0,
            "disclosed_entries": 1,
            "opaque_historical_entries": 0,
        },
    }
    cycle_ts = int(
        dt.datetime.combine(
            dt.date.fromisoformat(curve[-1]["date"]), dt.time(), tzinfo=dt.UTC
        ).timestamp()
        * 1000
    )
    crypto_attribution = {
        "schema": contract["required_crypto_position_attribution_schema"],
        "status": "COMPLETE",
        "passes": True,
        "latest_cycle": {
            "cycle_ts": cycle_ts,
            "reconciliation_passes": True,
            "position_arithmetic_passes": True,
        },
        "positions": [],
    }
    crypto_attribution["content_hash"] = evaluator._canonical_hash(crypto_attribution)
    crypto_attribution_rollout = {
        "schema": contract["required_crypto_position_attribution_rollout_schema"],
        "status": "VERIFIED_FIRST_NATURAL_MARKED_CYCLE",
        "passes": True,
        "remote_query_performed": True,
        "natural_cycle_after_deployment": True,
        "attribution": {"status": "COMPLETE", "passes": True},
    }
    crypto_attribution_rollout["content_hash"] = evaluator._canonical_hash(
        crypto_attribution_rollout
    )
    return {
        "state": state,
        "continuity": continuity,
        "broker": broker,
        "drawdown": drawdown,
        "current_book_drawdown": current_book_drawdown,
        "current_book_diversification": current_book_diversification,
        "drawdown_evidence": drawdown_evidence,
        "transparency": transparency,
        "crypto_attribution": crypto_attribution,
        "crypto_attribution_rollout": crypto_attribution_rollout,
        "contract": contract,
        "evaluated_at": generated + dt.timedelta(hours=1),
    }


def _alternating_returns(n: int, mean: float) -> list[float]:
    return [mean + (0.006 if i % 2 else -0.006) for i in range(n)]


def test_short_record_does_not_publish_a_sharpe_estimate(evaluator) -> None:
    report = evaluator.evaluate(**_inputs(evaluator, _alternating_returns(14, -0.0005)))
    evidence = report["sharpe_evidence"]
    assert report["status"] == "IMMATURE_RECORD_TOO_SHORT"
    assert evidence["annualized_point_estimate"] is None
    assert evidence["probability_true_sharpe_exceeds_target"] is None
    assert evidence["target_statistically_established"] is False


def test_mature_estimate_below_target_is_not_observed(evaluator) -> None:
    report = evaluator.evaluate(**_inputs(evaluator, _alternating_returns(252, 0.0001)))
    evidence = report["sharpe_evidence"]
    assert report["status"] == "ESTIMATE_ELIGIBLE_TARGET_NOT_OBSERVED"
    assert evidence["annualized_point_estimate"] < 1.5
    assert evidence["target_observed"] is False


def test_point_target_before_three_year_gate_is_only_observed(evaluator) -> None:
    report = evaluator.evaluate(**_inputs(evaluator, _alternating_returns(300, 0.001)))
    evidence = report["sharpe_evidence"]
    assert report["status"] == "TARGET_OBSERVED_NOT_ESTABLISHED"
    assert evidence["annualized_point_estimate"] >= 1.5
    assert evidence["target_statistically_established"] is False


def test_target_requires_three_year_sample_and_psr_above_target(evaluator) -> None:
    report = evaluator.evaluate(**_inputs(evaluator, _alternating_returns(756, 0.001)))
    evidence = report["sharpe_evidence"]
    assert report["status"] == "TARGET_STATISTICALLY_ESTABLISHED"
    assert evidence["annualized_point_estimate"] >= 1.5
    assert evidence["probability_true_sharpe_exceeds_target"] >= 0.95
    assert evidence["target_statistically_established"] is True


@pytest.mark.parametrize(
    ("section", "mutation"),
    [
        ("state", lambda value: value["live_config"].update({"fingerprint": "sha256:drift"})),
        ("continuity", lambda value: value.update({"passes": False})),
        ("broker", lambda value: value["summary"].update({"status": "FAIL"})),
        (
            "transparency",
            lambda value: value["entries"][0].update({"signature": "00" * 64}),
        ),
        ("crypto_attribution", lambda value: value.update({"passes": False})),
        ("drawdown_evidence", lambda value: value.update({"integrity_passes": False})),
        (
            "current_book_drawdown",
            lambda value: value["objective"].update(
                {"conservative_modeled_expected_max_drawdown": 0.12}
            ),
        ),
        (
            "current_book_diversification",
            lambda value: value["governing_comparison"].update(
                {"live_forward_diversification_established": True}
            ),
        ),
        (
            "crypto_attribution_rollout",
            lambda value: value.update({"passes": False}),
        ),
    ],
)
def test_provenance_mutations_fail_closed(evaluator, section, mutation) -> None:
    inputs = _inputs(evaluator, _alternating_returns(756, 0.001))
    mutation(inputs[section])
    report = evaluator.evaluate(**inputs)
    assert report["status"] == "FAIL_CLOSED_PROVENANCE"
    assert report["sharpe_evidence"]["target_statistically_established"] is False
    assert report["provenance_gate"]["failed_checks"]


def test_chain_head_must_equal_the_exact_state_used_for_sharpe(evaluator) -> None:
    inputs = _inputs(evaluator, _alternating_returns(756, 0.001))
    inputs["state"]["live_curve"][0]["equity"] += 1
    report = evaluator.evaluate(**inputs)
    assert report["status"] == "FAIL_CLOSED_PROVENANCE"
    assert report["provenance_gate"]["checks"]["transparency_chain_and_signatures_valid"] is True
    assert report["provenance_gate"]["checks"]["transparency_head_payload_matches_state"] is False
    assert report["sharpe_evidence"]["target_statistically_established"] is False


@pytest.mark.workspace_evidence
def test_current_workspace_record_is_honestly_immature(evaluator) -> None:
    report = json.loads(evaluator.OUTPUT_JSON.read_text())
    provenance = report["provenance_gate"]
    failed_checks = [name for name, passes in provenance["checks"].items() if not passes]
    assert provenance["passes"] is (not failed_checks)
    assert provenance["failed_checks"] == failed_checks
    if provenance["passes"]:
        assert report["status"] == report["sharpe_evidence"]["status"]
    else:
        assert report["status"] == "FAIL_CLOSED_PROVENANCE"
        assert report["sharpe_evidence"]["underlying_status"] == "IMMATURE_RECORD_TOO_SHORT"
    assert report["record"]["cumulative_return"] < 0.0
    assert report["sharpe_evidence"]["annualized_point_estimate"] is None
    assert report["sharpe_evidence"]["target_statistically_established"] is False
    assert report["content_hash"] == evaluator._canonical_hash(report)
    assert (
        report["drawdown_evidence"]["study_production_labelled_p95_max_drawdown"]
        > 0.11
    )
    assert report["drawdown_evidence"]["production_equivalence_passes"] is False
    assert (
        report["drawdown_evidence"]["objective_status"]
        == "MODELED_CURRENT_COMPOSITION_WITHIN_OBJECTIVE_"
        "LIVE_EXPECTED_MAX_DRAWDOWN_NOT_ESTABLISHED"
    )
    paper_binding = report["source_bindings"]["methodology_paper"]
    assert paper_binding["path"] == "docs/research/FORWARD_SHARPE_EVIDENCE_STANDARD.md"
    assert (
        paper_binding["sha256"]
        == hashlib.sha256(evaluator.METHODOLOGY_PAPER.read_bytes()).hexdigest()
    )
    chain_binding = report["source_bindings"]["transparency_chain"]
    assert (
        chain_binding["sha256"]
        == hashlib.sha256(evaluator.TRANSPARENCY_JSON.read_bytes()).hexdigest()
    )
    attribution_binding = report["source_bindings"]["crypto_position_attribution"]
    assert (
        attribution_binding["sha256"]
        == hashlib.sha256(evaluator.CRYPTO_ATTRIBUTION_JSON.read_bytes()).hexdigest()
    )
    rollout_binding = report["source_bindings"]["crypto_position_attribution_rollout"]
    assert (
        rollout_binding["sha256"]
        == hashlib.sha256(evaluator.CRYPTO_ATTRIBUTION_ROLLOUT_JSON.read_bytes()).hexdigest()
    )
