#!/usr/bin/env python3
"""Seal a complete, non-mutating governance route for every failed Sharadar split event."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Final

REPO: Final[Path] = Path(__file__).resolve().parents[1]
LIFECYCLE: Final[Path] = REPO / "artifacts/audit/sharadar_split_lifecycle_scope.json"
CONTEXT: Final[Path] = REPO / "artifacts/audit/unresolved_split_event_context.json"
ISSUER_VERIFICATIONS: Final[tuple[Path, ...]] = (
    REPO / "artifacts/audit/operating_margin_exposed_split_issuer_resolution.json",
    REPO / "artifacts/audit/split_issuer_resolution_batch_v2.json",
    REPO / "artifacts/audit/split_issuer_resolution_batch_v3.json",
    REPO / "artifacts/audit/split_issuer_resolution_batch_v6.json",
    REPO / "artifacts/audit/split_issuer_resolution_batch_v7.json",
    REPO / "artifacts/audit/split_issuer_resolution_batch_v8.json",
    REPO / "artifacts/audit/split_issuer_resolution_batch_v9.json",
    REPO / "artifacts/audit/split_issuer_resolution_batch_v10.json",
    REPO / "artifacts/audit/split_issuer_resolution_batch_v11.json",
)
COMPOSITE_ACTION_VERIFICATION: Final[Path] = (
    REPO / "artifacts/audit/split_issuer_resolution_batch_v4.json"
)
ISSUER_CONFLICT_VERIFICATION: Final[Path] = (
    REPO / "artifacts/audit/split_issuer_conflict_resolution_batch_v5.json"
)
LIFECYCLE_DISCONTINUITY: Final[Path] = (
    REPO / "artifacts/audit/split_lifecycle_discontinuity_resolution.json"
)
OUTPUT: Final[Path] = REPO / "artifacts/audit/sharadar_split_governance_policy.json"


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


def _event_ms(ex_date: str) -> int:
    return int(dt.datetime.fromisoformat(ex_date).timestamp() * 1000)


def build() -> dict[str, Any]:
    lifecycle = _load_sealed(LIFECYCLE)
    context = _load_sealed(CONTEXT)
    issuers = [_load_sealed(path) for path in ISSUER_VERIFICATIONS]
    composite = _load_sealed(COMPOSITE_ACTION_VERIFICATION)
    issuer_conflict = _load_sealed(ISSUER_CONFLICT_VERIFICATION)
    discontinuity = _load_sealed(LIFECYCLE_DISCONTINUITY)
    issuer_exact: dict[tuple[str, int, float], dict[str, Any]] = {}
    for issuer in issuers:
        for row in issuer["verified_events"]:
            key = (row["instrument_id"], int(row["ex_date_ms"]), float(row["ratio"]))
            if key in issuer_exact:
                raise ValueError(f"duplicate exact issuer authorization: {key}")
            issuer_exact[key] = row
    nonexecuting_exact = {
        (row["instrument_id"], int(row["ex_date_ms"]), float(row["stored_ratio"])): row
        for row in discontinuity["resolved_events"]
    }
    composite_exact = {
        (row["instrument_id"], int(row["ex_date_ms"]), float(row["stored_ratio"])): row
        for row in composite["resolved_events"]
    }
    issuer_conflict_exact = {
        (row["instrument_id"], int(row["ex_date_ms"]), float(row["stored_ratio"])): row
        for row in issuer_conflict["resolved_events"]
    }
    if set(issuer_exact) & set(nonexecuting_exact):
        raise ValueError("event cannot be both executable and a lifecycle discontinuity")
    if (set(issuer_exact) | set(nonexecuting_exact)) & set(composite_exact):
        raise ValueError("composite action cannot have another governance authorization")
    governed_sets = (set(issuer_exact), set(nonexecuting_exact), set(composite_exact))
    if any(keys & set(issuer_conflict_exact) for keys in governed_sets):
        raise ValueError("issuer conflict cannot have another governance authorization")
    unresolved_keys = {
        (row["instrument_id"], row["ex_date"], float(row["stored_ratio"]))
        for row in context["events"]
    }

    routes: list[dict[str, Any]] = []
    seen: set[tuple[str, str, float]] = set()
    for event in lifecycle["events"]:
        key = (event["instrument_id"], event["ex_date"], float(event["stored_ratio"]))
        if key in seen:
            raise ValueError(f"duplicate lifecycle event: {key}")
        seen.add(key)
        exact_key = (event["instrument_id"], _event_ms(event["ex_date"]), key[2])
        lifecycle_class = event["lifecycle_classification"]
        provider_class = event["provider_classification"]

        if lifecycle_class == "BEFORE_FIRST_PRICE_NON_EXECUTABLE":
            route = "NON_EXECUTABLE_BEFORE_FIRST_PRICE"
            reason = "No frozen price bar or tradable pre-event state exists."
        elif lifecycle_class == "FIRST_PRICE_BOUNDARY_NO_PREEXISTING_EXPOSURE":
            route = "NON_EXECUTABLE_FIRST_PRICE_BOUNDARY"
            reason = (
                "The event coincides with the first frozen price and has no pre-event exposure."
            )
        elif lifecycle_class == "AFTER_LAST_PRICE_NON_EXECUTABLE":
            route = "NON_EXECUTABLE_AFTER_LAST_PRICE"
            reason = "The event follows the final frozen price and cannot mutate an active book."
        elif exact_key in nonexecuting_exact:
            route = "NON_EXECUTABLE_ISSUER_VERIFIED_LIFECYCLE_DISCONTINUITY"
            reason = (
                "Issuer evidence shows old equity cancellation and new equity issuance under "
                "the same ticker; the stored ratio is not an executable shareholder conversion."
            )
        elif exact_key in composite_exact:
            route = "HARD_QUARANTINE_ISSUER_VERIFIED_COMPOSITE_ACTION"
            reason = (
                "The share mutation is issuer-verified, but its companion distributed-security "
                "entitlement is not replayed by the engine; split-only execution is forbidden."
            )
        elif exact_key in issuer_conflict_exact:
            route = "HARD_QUARANTINE_ISSUER_CONFLICT_OR_DATE_MISMATCH"
            reason = (
                "Primary issuer evidence conflicts with the frozen date or ratio semantics; "
                "execution remains forbidden pending a separately sealed correction."
            )
        elif lifecycle_class == "NO_FROZEN_TICKER_LIFECYCLE":
            route = "HARD_QUARANTINE_NO_FROZEN_LIFECYCLE"
            reason = "No frozen price lifecycle exists to verify or execute the event."
        elif exact_key in issuer_exact:
            route = "EXACT_ISSUER_VERIFIED_EXECUTABLE"
            reason = "Issuer evidence authorizes only this exact instrument/date/ratio tuple."
        elif provider_class == "INDEPENDENT_PROVIDER_CONFIRMS_STORED_RATIO":
            route = "PROVIDER_CORROBORATED_PRICE_CONFLICT_FAIL_CLOSED"
            reason = (
                "One independent provider confirms the ratio, but the local price boundary still "
                "fails; issuer evidence or a passing boundary is required before execution."
            )
        else:
            route = "HARD_QUARANTINE_UNRESOLVED_IN_LIFECYCLE"
            reason = "The in-lifecycle event lacks an independently executable resolution."

        routes.append(
            {
                **event,
                "ex_date_ms": exact_key[1],
                "governance_route": route,
                "execution_authorized": route == "EXACT_ISSUER_VERIFIED_EXECUTABLE",
                "reason": reason,
                "in_unresolved_context_set": key in unresolved_keys,
            }
        )

    counts = Counter(row["governance_route"] for row in routes)
    expected = {
        "NON_EXECUTABLE_BEFORE_FIRST_PRICE": 332,
        "NON_EXECUTABLE_FIRST_PRICE_BOUNDARY": 23,
        "NON_EXECUTABLE_AFTER_LAST_PRICE": 5,
        "EXACT_ISSUER_VERIFIED_EXECUTABLE": 25,
        "NON_EXECUTABLE_ISSUER_VERIFIED_LIFECYCLE_DISCONTINUITY": 6,
        "HARD_QUARANTINE_ISSUER_VERIFIED_COMPOSITE_ACTION": 12,
        "HARD_QUARANTINE_ISSUER_CONFLICT_OR_DATE_MISMATCH": 16,
        "PROVIDER_CORROBORATED_PRICE_CONFLICT_FAIL_CLOSED": 52,
        "HARD_QUARANTINE_UNRESOLVED_IN_LIFECYCLE": 2,
    }
    if dict(counts) != expected:
        raise ValueError(f"governance partition changed: {dict(counts)}")
    if sum(row["in_unresolved_context_set"] for row in routes) != 59:
        raise ValueError("unresolved context set no longer maps to exactly 59 events")

    payload: dict[str, Any] = {
        "schema": "canli.alphac-sharadar-split-governance-policy.v2",
        "author": "Arhan Canli",
        "decision": "ALL_FAILED_SPLIT_EVENTS_ROUTED_GLOBAL_GATE_REMAINS_CLOSED",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "policy_version": "split-governance-v2",
        "summary": {
            "events_routed": len(routes),
            "routes": expected,
            "lifecycle_non_executable": 366,
            "exact_execution_authorizations": 25,
            "fail_closed_or_quarantined": 82,
            "genuinely_unresolved": 2,
            "global_split_gate_passed": False,
        },
        "execution_contract": {
            "default": "FAIL_CLOSED",
            "authorized_bypass": "EXACT_ISSUER_VERIFIED_EXECUTABLE",
            "authorized_tuple_fields": ["instrument_id", "ex_date_ms", "stored_ratio"],
            "ratio_tolerance": {"relative": 0.0, "absolute": 1e-12},
            "provider_confirmation_alone_authorizes_execution": False,
            "quarantine_mutates_source_lake": False,
            "unlisted_or_nonmatching_event_action": "ABORT_IF_EXPOSED",
        },
        "events": routes,
        "lineage": {
            "lifecycle_path": str(LIFECYCLE.relative_to(REPO)),
            "lifecycle_sha256": _sha256(LIFECYCLE),
            "lifecycle_content_hash": lifecycle["content_hash"],
            "context_path": str(CONTEXT.relative_to(REPO)),
            "context_sha256": _sha256(CONTEXT),
            "context_content_hash": context["content_hash"],
            "issuer_verifications": [
                {
                    "path": str(path.relative_to(REPO)),
                    "sha256": _sha256(path),
                    "content_hash": issuer["content_hash"],
                }
                for path, issuer in zip(ISSUER_VERIFICATIONS, issuers, strict=True)
            ],
            "lifecycle_discontinuity_path": str(LIFECYCLE_DISCONTINUITY.relative_to(REPO)),
            "lifecycle_discontinuity_sha256": _sha256(LIFECYCLE_DISCONTINUITY),
            "lifecycle_discontinuity_content_hash": discontinuity["content_hash"],
            "composite_action_verification_path": str(
                COMPOSITE_ACTION_VERIFICATION.relative_to(REPO)
            ),
            "composite_action_verification_sha256": _sha256(COMPOSITE_ACTION_VERIFICATION),
            "composite_action_verification_content_hash": composite["content_hash"],
            "issuer_conflict_verification_path": str(
                ISSUER_CONFLICT_VERIFICATION.relative_to(REPO)
            ),
            "issuer_conflict_verification_sha256": _sha256(ISSUER_CONFLICT_VERIFICATION),
            "issuer_conflict_verification_content_hash": issuer_conflict["content_hash"],
        },
        "required_next_action": (
            "Resolve the two genuinely unresolved events with issuer/regulator evidence. Until "
            "then, future trial runners may use only the 25 exact authorization tuples and must "
            "abort if any other failed split becomes exposed."
        ),
        "claim_boundary": (
            "This closes the governance-routing gap, not the global data-quality gate. It does not "
            "repair a ratio, delete an event, authorize broad replay, validate performance, or "
            "admit a sleeve."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build()
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": payload["decision"], "content_hash": payload["content_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
