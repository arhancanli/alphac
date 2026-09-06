from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/analyze_forward_sleeve_contribution.py"
SPEC = importlib.util.spec_from_file_location("analyze_forward_sleeve_contribution", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
attribute = MODULE.attribute
build_document = MODULE.build_document


def _algorithm(key: str, end: float) -> dict:
    return {
        "key": key,
        "live_curve": [
            {"date": "2026-01-01", "equity": 100.0},
            {"date": "2026-01-02", "equity": end},
        ],
    }


def test_attributes_with_historical_schedule_and_preserves_residual() -> None:
    state = {
        "algorithms": [
            _algorithm("alphac", 99.0),
            _algorithm("alphaforge", 92.0),
            _algorithm("alphamax", 101.0),
            _algorithm("managed_futures", 102.0),
            _algorithm("alphavintage", 100.0),
        ]
    }
    schedule = [
        (
            "2026-01-01",
            {"crypto": 0.25, "equity": 0.25, "mf": 0.25, "vintage": 0.25},
        )
    ]

    result = attribute(state, schedule)

    assert result["largest_loss_driver"]["sleeve"] == "crypto"
    assert result["largest_loss_driver"]["dominates_current_loss"] is True
    components = sum(result["sleeve_additive_contributions"].values())
    residual = result["strategic_overlay_and_rounding_residual"]
    assert abs(components + residual - result["record"]["book_additive_return"]) < 1e-12


def test_document_binds_exact_state_and_forbids_reweighting() -> None:
    state = {
        "algorithms": [
            _algorithm("alphac", 100.0),
            _algorithm("alphaforge", 100.0),
            _algorithm("alphamax", 100.0),
            _algorithm("managed_futures", 100.0),
            _algorithm("alphavintage", 100.0),
        ]
    }
    raw = json.dumps(state).encode()

    document = build_document(state, raw)

    assert document["decision"] == "MONITOR_ONLY_NO_WEIGHT_CHANGE"
    assert document["source_bindings"]["paper_state"]["sha256"] == hashlib.sha256(
        raw
    ).hexdigest()
    assert "not a Sharpe estimate" in document["claim_boundary"]


def test_current_artifact_is_bound_to_current_state() -> None:
    state_bytes = (ROOT / "data/paper/state.json").read_bytes()
    artifact = json.loads(
        (ROOT / "artifacts/engineering/forward_sleeve_contribution.json").read_text()
    )

    assert artifact["source_bindings"]["paper_state"]["sha256"] == hashlib.sha256(
        state_bytes
    ).hexdigest()
    assert artifact["record"]["daily_return_observations"] >= 1
