from __future__ import annotations

import json

import pytest

from alphaforge.foundry.contract import FoundryContract
from alphaforge.foundry.sanitizer import SanitizationError, sanitize_public_status


def _private_trial() -> dict[str, object]:
    return {
        "public_trial_id": "ft_0123456789abcdef",
        "state": "KILLED",
        "reserved_at": "2026-08-26T10:00:00Z",
        "updated_at": "2026-08-26T11:00:00+00:00",
        "artifact_hash": "sha256:" + "a" * 64,
        "replay_status": "PASS",
        "private_hypothesis_text": "never publish this",
        "broker_credentials": {"api_key": "never publish this either"},
        "worker_network_details": "10.0.0.9",
    }


def test_status_projects_allowlisted_fields_and_preserves_not_deployed_claim() -> None:
    document = sanitize_public_status(
        trials=[_private_trial()],
        contract=FoundryContract.load(),
        generated_at="2026-08-26T12:00:00Z",
        queue_depth=0,
        compute_seconds=12,
        successful_jobs=1,
        failed_jobs=0,
        quota_breaches=0,
        restore_status="NOT_TESTED",
    )
    encoded = json.dumps(document, sort_keys=True)
    assert document["deployment_status"] == "DESIGN_FROZEN_NOT_DEPLOYED"
    assert document["identity_counts"]["killed"] == 1
    assert "private_hypothesis_text" not in encoded
    assert "broker_credentials" not in encoded
    assert "10.0.0.9" not in encoded
    assert document["content_hash"].startswith("sha256:")


def test_status_rejects_secret_like_bytes_in_an_allowed_field() -> None:
    trial = _private_trial()
    trial["artifact_hash"] = "-----BEGIN PRIVATE KEY-----"
    with pytest.raises(SanitizationError, match="artifact hash is malformed"):
        sanitize_public_status(
            trials=[trial],
            contract=FoundryContract.load(),
            generated_at="2026-08-26T12:00:00Z",
            queue_depth=0,
            compute_seconds=0,
            successful_jobs=0,
            failed_jobs=0,
            quota_breaches=0,
            restore_status="NOT_TESTED",
        )


def test_status_rejects_negative_operational_counters() -> None:
    with pytest.raises(SanitizationError, match="non-negative integers"):
        sanitize_public_status(
            trials=[],
            contract=FoundryContract.load(),
            generated_at="2026-08-26T12:00:00Z",
            queue_depth=-1,
            compute_seconds=0,
            successful_jobs=0,
            failed_jobs=0,
            quota_breaches=0,
            restore_status="NOT_TESTED",
        )
