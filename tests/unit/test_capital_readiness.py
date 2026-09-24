"""The capital-readiness gate passes only on evidence and fails closed on anything missing."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "capital_readiness_under_test", ROOT / "scripts" / "evaluate_capital_readiness.py"
)
assert _SPEC and _SPEC.loader
GATE_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(GATE_MODULE)
GATE = json.loads((ROOT / "config" / "capital_readiness_gate.json").read_text(encoding="utf-8"))
ATTESTED = {"attested_on": "2027-01-01", "attested_by": "account holder"}


def _maturity(observations: int, estimate: float | None, sleeves: int) -> dict:
    return {
        "sharpe_evidence": {
            "daily_return_observations": observations,
            "establishment_minimum": 756,
            "annualized_point_estimate": estimate,
            "target": 2.0,
        },
        "drawdown_evidence": {
            "realized_live_max_drawdown": 0.05,
            "realized_max_drawdown_bound": 0.1,
        },
        "provenance_gate": {"passes": True},
        "diversification_evidence": {"current_sleeves": sleeves},
    }


def _all_green() -> dict:
    return {
        "maturity": _maturity(800, 2.1, 14),
        "shortfall": {
            "sleeves": {"a": {"implementation_shortfall_bps_of_decision_notional": 10.0}}
        },
        "drawdown_contract": {"activation": {"live": True}},
        "attestations": {
            "attestations": {
                c["id"]: ATTESTED for c in GATE["criteria"] if c["kind"] == "attestation"
            }
        },
        "sleeve_goal": 14,
    }


def test_every_criterion_met_is_ready_and_today_is_not() -> None:
    assert GATE_MODULE.evaluate(GATE, **_all_green())["verdict"] == "READY_FOR_CAPITAL"
    today = _all_green() | {"maturity": _maturity(9, None, 4)}
    report = GATE_MODULE.evaluate(GATE, **today)
    assert report["verdict"] == "NOT_READY_PAPER_ONLY"
    assert {"E1_forward_record_length", "E2_forward_sharpe_target", "E5_qualified_sleeves"} <= set(
        report["failing"]
    )


def test_missing_evidence_fails_closed() -> None:
    for missing in ("maturity", "shortfall", "drawdown_contract", "attestations"):
        report = GATE_MODULE.evaluate(GATE, **(_all_green() | {missing: None}))
        assert report["verdict"] == "NOT_READY_PAPER_ONLY", missing
    assert GATE_MODULE.evaluate(GATE, **(_all_green() | {"sleeve_goal": None}))["verdict"] == (
        "NOT_READY_PAPER_ONLY"
    )


def test_an_attestation_needs_both_a_date_and_who_attested() -> None:
    inputs = _all_green()
    inputs["attestations"]["attestations"]["L1_legal_entity"] = {"attested_on": "2027-01-01"}
    assert GATE_MODULE.evaluate(GATE, **inputs)["failing"] == ["L1_legal_entity"]


def test_a_shortfall_over_the_limit_fails_execution() -> None:
    inputs = _all_green()
    inputs["shortfall"]["sleeves"]["b"] = {
        "implementation_shortfall_bps_of_decision_notional": 39.7
    }
    assert GATE_MODULE.evaluate(GATE, **inputs)["failing"] == ["X1_implementation_shortfall"]


def test_the_sleeve_goal_is_read_from_its_structured_field() -> None:
    goals = {"goals": {"qualified_economically_distinct_sleeves": {"minimum": 14}}}
    assert GATE_MODULE._sleeve_goal(goals) == 14
    assert GATE_MODULE._sleeve_goal({"decision": {"words": "14 plus sleeves"}}) is None
