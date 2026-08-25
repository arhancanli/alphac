#!/usr/bin/env python3
"""Promote the audited v7 admission contract and staged trial budget atomically.

The migration preserves v6 and trial-accounting v1 byte-for-byte in ``config/archive``. The
promoted policy applies only to identity reservations numbered after the 228-identity retired
legacy epoch; no historical result is regraded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
ACTIVE_CONTRACT: Final = ROOT / "config/sleeve_admission_contract.json"
PROPOSAL_CONTRACT: Final = ROOT / "config/sleeve_admission_contract_v7_proposed.json"
ARCHIVE_CONTRACT: Final = ROOT / "config/archive/sleeve_admission_contract_v6_superseded.json"
ACTIVE_TRIAL_POLICY: Final = ROOT / "config/trial_accounting.json"
PROPOSAL_TRIAL_POLICY: Final = ROOT / "config/trial_accounting_v7_proposed.json"
ARCHIVE_TRIAL_POLICY: Final = ROOT / "config/archive/trial_accounting_v1_superseded.json"
POWER_AUDIT: Final = ROOT / "artifacts/analysis/admission_gate_power_audit/result.json"
RECEIPT: Final = ROOT / "config/admission_v7_promotion.json"
PROMOTED_AT: Final = "2026-08-23"
LEGACY_IDENTITIES: Final = 228


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return _canonical_sha256(body)


def _effective_contract_hash(contract: dict[str, Any]) -> str:
    normalized = json.loads(json.dumps(contract))
    normalized["prospective_scope"]["effective_contract_content_hash"] = None
    return _canonical_sha256(normalized)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def build_active_contract(proposal: dict[str, Any]) -> dict[str, Any]:
    if (
        proposal.get("schema") != "canli.alphac-sleeve-admission-contract.v7-proposed"
        or proposal.get("status") != "PROPOSED_NOT_IN_FORCE"
    ):
        raise ValueError("v7 proposal schema or status mismatch")
    contract = json.loads(json.dumps(proposal))
    contract["schema"] = "canli.alphac-sleeve-admission-contract.v7"
    contract["status"] = "IN_FORCE"
    scope = contract["prospective_scope"]
    scope["effective"] = True
    scope["effective_on_or_after_reservation_ordinal"] = LEGACY_IDENTITIES + 1
    scope["owner_promotion_record"] = "config/admission_v7_promotion.json"
    scope["effective_contract_content_hash"] = None
    contract["claim_boundary"] = (
        "This in-force contract applies only to return identities reserved at ordinal 229 or "
        "later under its exact effective hash. The 228 legacy identities remain retired under "
        "their original contracts and may not be regraded or reused. Technical eligibility does "
        "not establish alpha, future returns, the 1.5 forward Sharpe target, the 11% expected-"
        "drawdown objective, or the -0.03 diversification objective."
    )
    scope["effective_contract_content_hash"] = _effective_contract_hash(contract)
    return contract


def build_active_trial_policy(
    proposal: dict[str, Any], *, effective_contract_hash: str
) -> dict[str, Any]:
    if (
        proposal.get("schema") != "alphac.trial-accounting-policy.v2-proposed"
        or proposal.get("research_status") != "PROPOSED_NOT_IN_FORCE"
    ):
        raise ValueError("v7 trial-accounting proposal schema or status mismatch")
    policy = json.loads(json.dumps(proposal))
    policy["schema"] = "alphac.trial-accounting-policy.v2"
    policy["research_status"] = "ACTIVE_STAGED_PROSPECTIVE_BUDGET"
    review = policy["prospective_v7_review"]
    review["status"] = "IN_FORCE"
    review["admission_v7_effective_contract_hash"] = effective_contract_hash
    review["effective_on_or_after_reservation_ordinal"] = LEGACY_IDENTITIES + 1
    review["owner_promotion_record"] = "config/admission_v7_promotion.json"
    return policy


def build_receipt(
    *,
    active_contract: dict[str, Any],
    active_policy: dict[str, Any],
    proposal_contract_sha256: str,
    proposal_policy_sha256: str,
    archive_contract_sha256: str,
    archive_policy_sha256: str,
    power_audit_sha256: str,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": "canli.alphac-admission-v7-promotion.v1",
        "promoted_at": PROMOTED_AT,
        "owner": "Arhan Canli",
        "authorization": (
            "Owner directive in the active 2026-08-23 goal session: recalibrate gates where "
            "needed, preserve rigor, and proceed."
        ),
        "effective_contract_hash": active_contract["prospective_scope"][
            "effective_contract_content_hash"
        ],
        "effective_on_or_after_reservation_ordinal": LEGACY_IDENTITIES + 1,
        "legacy_identities_retired_without_regrading": LEGACY_IDENTITIES,
        "active_contract": active_contract,
        "active_trial_policy": active_policy,
        "source_bindings": {
            "contract_proposal": {
                "path": str(PROPOSAL_CONTRACT.relative_to(ROOT)),
                "sha256": proposal_contract_sha256,
            },
            "trial_policy_proposal": {
                "path": str(PROPOSAL_TRIAL_POLICY.relative_to(ROOT)),
                "sha256": proposal_policy_sha256,
            },
            "v6_archive": {
                "path": str(ARCHIVE_CONTRACT.relative_to(ROOT)),
                "sha256": archive_contract_sha256,
            },
            "trial_policy_v1_archive": {
                "path": str(ARCHIVE_TRIAL_POLICY.relative_to(ROOT)),
                "sha256": archive_policy_sha256,
            },
            "power_audit": {
                "path": str(POWER_AUDIT.relative_to(ROOT)),
                "sha256": power_audit_sha256,
            },
        },
        "assertions": {
            "known_results_regraded": False,
            "legacy_identity_reuse_permitted": False,
            "candidate_return_artifacts_read_by_power_audit": 0,
            "trial_budget_is_permission_to_test_not_permission_to_admit": True,
            "external_performance_claim_created": False,
        },
    }
    receipt["content_hash"] = _content_hash(receipt)
    return receipt


def _archive_exact(source: Path, archive: Path, *, expected_schema: str) -> None:
    source_payload = _load(source)
    if source_payload.get("schema") != expected_schema:
        if not archive.is_file():
            raise ValueError(f"cannot create missing archive after source promotion: {archive}")
        return
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        if archive.read_bytes() != source.read_bytes():
            raise ValueError(f"existing archive differs from exact source: {archive}")
        return
    shutil.copyfile(source, archive)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def promote() -> dict[str, Any]:
    _archive_exact(
        ACTIVE_CONTRACT,
        ARCHIVE_CONTRACT,
        expected_schema="canli.alphac-sleeve-admission-contract.v6",
    )
    _archive_exact(
        ACTIVE_TRIAL_POLICY,
        ARCHIVE_TRIAL_POLICY,
        expected_schema="alphac.trial-accounting-policy.v1",
    )
    proposal_contract = _load(PROPOSAL_CONTRACT)
    proposal_policy = _load(PROPOSAL_TRIAL_POLICY)
    active_contract = build_active_contract(proposal_contract)
    active_policy = build_active_trial_policy(
        proposal_policy,
        effective_contract_hash=active_contract["prospective_scope"][
            "effective_contract_content_hash"
        ],
    )
    receipt = build_receipt(
        active_contract=active_contract,
        active_policy=active_policy,
        proposal_contract_sha256=_sha256(PROPOSAL_CONTRACT),
        proposal_policy_sha256=_sha256(PROPOSAL_TRIAL_POLICY),
        archive_contract_sha256=_sha256(ARCHIVE_CONTRACT),
        archive_policy_sha256=_sha256(ARCHIVE_TRIAL_POLICY),
        power_audit_sha256=_sha256(POWER_AUDIT),
    )
    _atomic_json(ACTIVE_CONTRACT, active_contract)
    _atomic_json(ACTIVE_TRIAL_POLICY, active_policy)
    _atomic_json(RECEIPT, receipt)
    return receipt


def verify_current() -> dict[str, Any]:
    receipt = _load(RECEIPT)
    if receipt.get("content_hash") != _content_hash(receipt):
        raise ValueError("promotion receipt content hash mismatch")
    active_contract = _load(ACTIVE_CONTRACT)
    active_policy = _load(ACTIVE_TRIAL_POLICY)
    if receipt.get("active_contract") != active_contract:
        raise ValueError("active contract differs from promotion receipt")
    if receipt.get("active_trial_policy") != active_policy:
        raise ValueError("active trial policy differs from promotion receipt")
    if active_contract["prospective_scope"]["effective_contract_content_hash"] != (
        _effective_contract_hash(active_contract)
    ):
        raise ValueError("effective contract hash mismatch")
    for binding in receipt["source_bindings"].values():
        path = ROOT / binding["path"]
        if _sha256(path) != binding["sha256"]:
            raise ValueError(f"promotion source binding mismatch: {path}")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="archive v6 and promote v7")
    args = parser.parse_args()
    receipt = promote() if args.apply else verify_current()
    print(f"v7 promotion verified: {receipt['effective_contract_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
