#!/usr/bin/env python3
"""Seal the narrow, fail-closed authorization for one corrected operating-margin replay."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Final

REPO: Final[Path] = Path(__file__).resolve().parents[1]
BUILD: Final[Path] = REPO / "artifacts/audit/sharadar_corporate_action_corrected_lake.json"
VALIDATION: Final[Path] = (
    REPO / "artifacts/audit/sharadar_corrected_corporate_action_validation.json"
)
LIFECYCLE: Final[Path] = REPO / "artifacts/audit/sharadar_split_lifecycle_scope.json"
EXPOSURE: Final[Path] = (
    REPO / "artifacts/audit/operating_margin_unresolved_split_exposure.json"
)
VERIFICATION: Final[Path] = (
    REPO / "artifacts/audit/operating_margin_exposed_split_issuer_resolution.json"
)
ENGINE: Final[Path] = REPO / "src/alphaforge/backtest/engine.py"
WALKFORWARD: Final[Path] = REPO / "src/alphaforge/analytics/walkforward.py"
OUTPUT: Final[Path] = (
    REPO / "artifacts/audit/operating_margin_corrected_replay_authorization.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _load_sealed(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    declared = payload.pop("content_hash", None)
    actual = _content_hash(payload)
    payload["content_hash"] = declared
    if declared != actual:
        raise ValueError(f"content hash mismatch: {path.relative_to(REPO)}")
    return payload


def build(*, sealed_at: str) -> dict[str, Any]:
    lake = _load_sealed(BUILD)
    validation = _load_sealed(VALIDATION)
    lifecycle = _load_sealed(LIFECYCLE)
    exposure = _load_sealed(EXPOSURE)
    verification = _load_sealed(VERIFICATION)

    if lake["decision"] != "VERSIONED_CORPORATE_ACTION_LAKE_BUILT_VALIDATION_PENDING":
        raise ValueError("corrected lake build decision changed")
    if not validation["dividend_gate"]["passed"]:
        raise ValueError("corrected lake dividend gate is not green")
    if lifecycle["summary"] != {
        "failed_or_unverifiable_events": 473,
        "before_first_price_non_executable": 332,
        "first_price_boundary_no_preexisting_exposure": 23,
        "after_last_price_non_executable": 5,
        "within_price_lifecycle_requires_resolution": 112,
        "no_frozen_ticker_lifecycle": 1,
    }:
        raise ValueError("split lifecycle accounting changed")
    expected_exposure = {
        "post_2005_in_lifecycle_failed_events": 71,
        "independent_provider_confirmed_events": 51,
        "unresolved_events": 20,
        "observed_held_pre_boundary": 2,
        "observed_queued_pre_boundary": 0,
        "no_observed_pre_boundary_exposure": 69,
        "outside_sealed_replay_window": 0,
    }
    if exposure["summary"] != expected_exposure:
        raise ValueError("operating-margin split exposure accounting changed")
    verified_events = verification["verified_events"]
    if verification["decision"] != (
        "EXACT_EXPOSED_SPLIT_VERIFICATION_AUTHORIZED_FOR_FAIL_CLOSED_REPLAY"
    ) or {(row["instrument_id"], row["ex_date_ms"], row["ratio"]) for row in verified_events} != {
        ("XUSE:CASH:ADTXUSD", 1663113600000, 0.02),
        ("XUSE:CASH:SPCEUSD", 1718582400000, 0.05),
    }:
        raise ValueError("exact issuer verification set changed")

    lineage_paths = (BUILD, VALIDATION, LIFECYCLE, EXPOSURE, VERIFICATION)
    payload: dict[str, Any] = {
        "schema": "canli.alphac-operating-margin-corrected-replay-authorization.v1",
        "author": "Arhan Canli",
        "sealed_at": sealed_at,
        "decision": "OPERATING_MARGIN_CORRECTED_REPLAY_AUTHORIZED_FAIL_CLOSED",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "run_name": "single_operating_margin",
        "hypothesis_key": "e5f48adc25065ce9",
        "corrected_lake": lake["corrected_lake"],
        "verified_split_events": [
            {
                "instrument_id": row["instrument_id"],
                "ex_date_ms": row["ex_date_ms"],
                "ratio": row["ratio"],
            }
            for row in verified_events
        ],
        "accounting": {
            "dividend_gate_passed": True,
            "global_split_gate_passed": False,
            "global_split_failures": 473,
            "within_lifecycle_requires_resolution": 112,
            "post_2005_in_lifecycle_failed_events": 71,
            "historically_exposed_events": 2,
            "exact_issuer_verified_exposed_events": 2,
            "no_observed_pre_boundary_exposure": 69,
        },
        "lineage": {
            str(path.relative_to(REPO)): {
                "sha256": _sha256(path),
                "content_hash": _load_sealed(path)["content_hash"],
            }
            for path in lineage_paths
        },
        "execution_code": {
            str(ENGINE.relative_to(REPO)): _sha256(ENGINE),
            str(WALKFORWARD.relative_to(REPO)): _sha256(WALKFORWARD),
        },
        "required_runtime_behavior": (
            "Only the two exact issuer-verified tuples may bypass the split price-gap heuristic. "
            "Any other exposed split without a valid price boundary must abort the replay."
        ),
        "claim_boundary": (
            "This authorizes one zero-trial corrected-data reproduction of the immutable "
            "single_operating_margin identity. The global lake split gate remains failed. This "
            "receipt does not predict or validate Sharpe, drawdown, admission, or live performance."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build(sealed_at=dt.datetime.now(dt.UTC).isoformat())
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": payload["decision"], "content_hash": payload["content_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
