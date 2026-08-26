"""Fail-closed construction of Foundry artifacts safe for public publication."""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from collections.abc import Iterable, Mapping
from typing import Any, Final

from alphaforge.foundry.contract import FoundryContract, canonical_sha256

PUBLIC_ID: Final[re.Pattern[str]] = re.compile(r"^ft_[0-9a-f]{16}$")
DIGEST: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
SENSITIVE_KEY: Final[re.Pattern[str]] = re.compile(
    r"(?:api[_-]?key|secret|token|password|credential|private[_-]?key|broker[_-]?key)",
    re.IGNORECASE,
)
SENSITIVE_VALUE: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:sk|pk)_(?:live|test)_[0-9A-Za-z]{16,}\b"),
)


class SanitizationError(ValueError):
    """Private, malformed, or unsupported data reached the public boundary."""


def _utc(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise SanitizationError(f"{field} must be an ISO-8601 UTC timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SanitizationError(f"{field} must be an ISO-8601 UTC timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
        raise SanitizationError(f"{field} must include UTC timezone information")
    return parsed.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _scan(value: object, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise SanitizationError(f"public object key is not a string at {path}")
            if SENSITIVE_KEY.search(key):
                raise SanitizationError(f"sensitive field reached public output at {path}.{key}")
            _scan(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _scan(nested, f"{path}[{index}]")
    elif isinstance(value, str):
        if any(pattern.search(value) for pattern in SENSITIVE_VALUE):
            raise SanitizationError(f"secret-like value reached public output at {path}")
    elif isinstance(value, float) and not math.isfinite(value):
        raise SanitizationError(f"non-finite number reached public output at {path}")


def sanitize_public_trial(
    record: dict[str, Any], contract: FoundryContract
) -> dict[str, Any]:
    projected = contract.public_trial(record)
    identifier = projected.get("public_trial_id")
    if not isinstance(identifier, str) or PUBLIC_ID.fullmatch(identifier) is None:
        raise SanitizationError("public trial identifier is malformed")
    for field in ("reserved_at", "updated_at"):
        value = projected.get(field)
        if value is not None:
            projected[field] = _utc(value, field)
    artifact_hash = projected.get("artifact_hash")
    if artifact_hash is not None and (
        not isinstance(artifact_hash, str) or DIGEST.fullmatch(artifact_hash) is None
    ):
        raise SanitizationError("artifact hash is malformed")
    replay_status = projected.get("replay_status")
    if replay_status is not None and replay_status not in {
        "NOT_RUN",
        "PENDING",
        "PASS",
        "FAIL",
    }:
        raise SanitizationError("replay status is not public-safe")
    _scan(projected)
    return dict(sorted(projected.items()))


def sanitize_public_status(
    *,
    trials: Iterable[dict[str, Any]],
    contract: FoundryContract,
    generated_at: str,
    queue_depth: int,
    compute_seconds: int,
    successful_jobs: int,
    failed_jobs: int,
    quota_breaches: int,
    restore_status: str,
) -> dict[str, Any]:
    """Build the only public Foundry status shape accepted by the publisher."""
    integers = {
        "queue_depth": queue_depth,
        "compute_seconds": compute_seconds,
        "successful_jobs": successful_jobs,
        "failed_jobs": failed_jobs,
        "quota_breaches": quota_breaches,
    }
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in integers.values()
    ):
        raise SanitizationError("public counters must be non-negative integers")
    if restore_status not in {"NOT_TESTED", "PASS", "FAIL", "STALE"}:
        raise SanitizationError("restore status is not public-safe")
    public_trials = [sanitize_public_trial(record, contract) for record in trials]
    public_trials.sort(key=lambda item: str(item["public_trial_id"]))
    counts = dict.fromkeys(contract.state_names, 0)
    for trial in public_trials:
        counts[str(trial["state"])] += 1
    latest = max(
        (trial for trial in public_trials if trial.get("updated_at")),
        key=lambda item: str(item["updated_at"]),
        default=None,
    )
    document: dict[str, Any] = {
        "schema": "canli.foundry-public-status.v1",
        "deployment_status": contract.status,
        "claim_boundary": contract.claim_boundary,
        "generated_at": _utc(generated_at, "generated_at"),
        "queue_depth": queue_depth,
        "compute_seconds": compute_seconds,
        "successful_jobs": successful_jobs,
        "failed_jobs": failed_jobs,
        "quota_breaches": quota_breaches,
        "restore_status": restore_status,
        "identity_counts": {
            "spent": sum(bool(trial["identity_spent"]) for trial in public_trials),
            "admitted": counts["ADMITTED"],
            "killed": counts["KILLED"],
            "data_gated": counts["DATA_GATED"],
        },
        "latest_run": (
            None
            if latest is None
            else {
                key: latest[key]
                for key in (
                    "public_trial_id",
                    "state",
                    "artifact_hash",
                    "replay_status",
                    "updated_at",
                )
                if key in latest
            }
        ),
        "trials": public_trials,
    }
    document["content_hash"] = canonical_sha256(document)
    _scan(document)
    json.dumps(document, allow_nan=False)
    return document
