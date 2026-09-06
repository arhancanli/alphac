"""Machine verification for Foundry deployment acceptance receipts."""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from alphaforge.foundry.contract import FoundryContract, canonical_sha256
from alphaforge.foundry.policy import load_foundry_policy

DEFAULT_RECEIPT_CONTRACT: Final[Path] = (
    Path(__file__).resolve().parents[3] / "config" / "foundry_acceptance_receipt_contract.json"
)
DEFAULT_DEPLOYMENT_MANIFEST: Final[Path] = (
    Path(__file__).resolve().parents[3] / "config" / "foundry_deployment_manifest.json"
)
RECEIPT_SCHEMA: Final[str] = "canli.foundry-acceptance-receipt.v1"
DIGEST: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
IMAGE: Final[re.Pattern[str]] = re.compile(r"^[^\s]+@sha256:[0-9a-f]{64}$")
SENSITIVE_KEY: Final[re.Pattern[str]] = re.compile(
    r"(?:api[_-]?key|password|credential|private[_-]?key|secret[_-]?value|token[_-]?value)$",
    re.IGNORECASE,
)
SENSITIVE_VALUE: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:sk|pk)_(?:live|test)_[0-9A-Za-z]{16,}\b"),
)


class ReceiptContractError(ValueError):
    """A receipt contract or receipt is malformed, inconsistent, or unsafe."""


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReceiptContractError(f"{field} must be an object")
    return {str(key): nested for key, nested in value.items()}


def _load(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReceiptContractError(f"cannot load {field}: {path}") from error
    return _mapping(value, field)


def _timestamp(value: object, field: str) -> dt.datetime:
    if not isinstance(value, str):
        raise ReceiptContractError(f"{field} must be an ISO-8601 UTC timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReceiptContractError(f"{field} must be an ISO-8601 UTC timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
        raise ReceiptContractError(f"{field} must carry a UTC offset")
    return parsed.astimezone(dt.UTC)


def _scan(value: object, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ReceiptContractError(f"receipt key is not a string at {path}")
            if SENSITIVE_KEY.search(key):
                raise ReceiptContractError(f"sensitive field is forbidden at {path}.{key}")
            _scan(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _scan(nested, f"{path}[{index}]")
    elif isinstance(value, str) and any(pattern.search(value) for pattern in SENSITIVE_VALUE):
        raise ReceiptContractError(f"secret-like value is forbidden at {path}")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ReceiptContractError(f"non-finite receipt measurement at {path}")


def _contract_hash(path: Path) -> str:
    return canonical_sha256(_load(path, f"binding source {path.name}"))


def expected_receipt_bindings(contract: dict[str, Any], repository_root: Path) -> dict[str, str]:
    sources = _mapping(contract.get("binding_sources"), "binding_sources")
    required = {
        "deployment_manifest",
        "runtime_contract",
        "lifecycle_contract",
        "trial_policy",
    }
    if set(sources) != required:
        raise ReceiptContractError("acceptance binding source inventory drifted")
    root = repository_root.resolve()
    hashes: dict[str, str] = {}
    for name, raw_path in sources.items():
        if not isinstance(raw_path, str):
            raise ReceiptContractError(f"binding source path must be a string: {name}")
        path = (root / raw_path).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise ReceiptContractError(f"binding source escapes repository: {name}") from error
        hashes[f"{name}_hash"] = _contract_hash(path)
    lifecycle = FoundryContract.load(root / str(sources["lifecycle_contract"]))
    policy = load_foundry_policy(root / str(sources["trial_policy"]))
    if hashes["lifecycle_contract_hash"] != lifecycle.content_hash:
        raise ReceiptContractError("lifecycle binding uses inconsistent hash semantics")
    if hashes["trial_policy_hash"] != policy.content_hash:
        raise ReceiptContractError("trial policy binding uses inconsistent hash semantics")
    return hashes


def load_receipt_contract(
    path: Path = DEFAULT_RECEIPT_CONTRACT,
    *,
    deployment_manifest_path: Path = DEFAULT_DEPLOYMENT_MANIFEST,
) -> dict[str, Any]:
    contract = _load(path, "acceptance receipt contract")
    if contract.get("schema") != "canli.foundry-acceptance-receipt-contract.v1":
        raise ReceiptContractError("unexpected acceptance receipt contract schema")
    if contract.get("status") != "FROZEN_NOT_SATISFIED":
        raise ReceiptContractError("acceptance contract must not claim satisfaction")
    receipts = _mapping(contract.get("receipts"), "receipts")
    manifest = _load(deployment_manifest_path, "deployment manifest")
    expected_ids = manifest.get("acceptance_receipts_required")
    if not isinstance(expected_ids, list) or set(receipts) != set(expected_ids):
        raise ReceiptContractError("receipt inventory differs from deployment manifest")
    for receipt_id, raw_rule in receipts.items():
        rule = _mapping(raw_rule, f"receipts.{receipt_id}")
        assertions = rule.get("required_assertions")
        measurements = rule.get("required_measurements")
        if (
            not isinstance(assertions, list)
            or not assertions
            or any(not isinstance(item, str) for item in assertions)
            or len(set(assertions)) != len(assertions)
        ):
            raise ReceiptContractError(f"receipt assertion contract is malformed: {receipt_id}")
        if (
            not isinstance(measurements, list)
            or any(not isinstance(item, str) for item in measurements)
            or len(set(measurements)) != len(measurements)
        ):
            raise ReceiptContractError(f"receipt measurement contract is malformed: {receipt_id}")
    return contract


def _validate_receipt(
    receipt: dict[str, Any],
    *,
    receipt_id: str,
    rule: dict[str, Any],
    expected_bindings: dict[str, str],
) -> tuple[dt.datetime, dict[str, str]]:
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("receipt_id") != receipt_id:
        raise ReceiptContractError(f"receipt identity or schema mismatch: {receipt_id}")
    if receipt.get("result") not in {"PASS", "FAIL"}:
        raise ReceiptContractError(f"receipt result must be PASS or FAIL: {receipt_id}")
    if not isinstance(receipt.get("claim_boundary"), str) or not receipt["claim_boundary"]:
        raise ReceiptContractError(f"receipt claim boundary is absent: {receipt_id}")
    generated_at = _timestamp(receipt.get("generated_at"), f"{receipt_id}.generated_at")

    bindings = _mapping(receipt.get("bindings"), f"{receipt_id}.bindings")
    common_keys = {
        *expected_bindings,
        "source_commit",
        "infrastructure_fingerprint",
        "worker_image_digest",
    }
    if set(bindings) != common_keys:
        raise ReceiptContractError(f"receipt binding inventory drifted: {receipt_id}")
    for key, expected in expected_bindings.items():
        if bindings.get(key) != expected:
            raise ReceiptContractError(f"receipt contract binding mismatch: {receipt_id}.{key}")
    source_commit = bindings.get("source_commit")
    infrastructure = bindings.get("infrastructure_fingerprint")
    image = bindings.get("worker_image_digest")
    if not isinstance(source_commit, str) or COMMIT.fullmatch(source_commit) is None:
        raise ReceiptContractError(f"source commit is malformed: {receipt_id}")
    if not isinstance(infrastructure, str) or DIGEST.fullmatch(infrastructure) is None:
        raise ReceiptContractError(f"infrastructure fingerprint is malformed: {receipt_id}")
    if not isinstance(image, str) or IMAGE.fullmatch(image) is None:
        raise ReceiptContractError(f"worker image digest is malformed: {receipt_id}")

    required_assertions = set(rule["required_assertions"])
    assertions = _mapping(receipt.get("assertions"), f"{receipt_id}.assertions")
    if set(assertions) != required_assertions or any(
        not isinstance(value, bool) for value in assertions.values()
    ):
        raise ReceiptContractError(f"receipt assertions differ from contract: {receipt_id}")
    if receipt["result"] == "PASS" and not all(assertions.values()):
        raise ReceiptContractError(f"passing receipt contains a false assertion: {receipt_id}")

    required_measurements = set(rule["required_measurements"])
    measurements = _mapping(receipt.get("measurements"), f"{receipt_id}.measurements")
    if set(measurements) != required_measurements:
        raise ReceiptContractError(f"receipt measurements differ from contract: {receipt_id}")
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        for value in measurements.values()
    ):
        raise ReceiptContractError(f"receipt measurement is invalid: {receipt_id}")

    evidence = receipt.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ReceiptContractError(f"receipt evidence is absent: {receipt_id}")
    for index, raw_item in enumerate(evidence):
        item = _mapping(raw_item, f"{receipt_id}.evidence[{index}]")
        if set(item) != {"name", "sha256", "classification"}:
            raise ReceiptContractError(f"receipt evidence shape is invalid: {receipt_id}")
        if not isinstance(item["name"], str) or not item["name"]:
            raise ReceiptContractError(f"receipt evidence name is invalid: {receipt_id}")
        if not isinstance(item["sha256"], str) or DIGEST.fullmatch(item["sha256"]) is None:
            raise ReceiptContractError(f"receipt evidence hash is invalid: {receipt_id}")
        if item["classification"] not in {"PUBLIC", "PRIVATE_REDACTED"}:
            raise ReceiptContractError(f"receipt evidence classification is invalid: {receipt_id}")

    claimed_hash = receipt.get("content_hash")
    payload = dict(receipt)
    payload.pop("content_hash", None)
    if claimed_hash != canonical_sha256(payload):
        raise ReceiptContractError(f"receipt content hash mismatch: {receipt_id}")
    _scan(receipt)
    return generated_at, {
        "source_commit": source_commit,
        "infrastructure_fingerprint": infrastructure,
        "worker_image_digest": image,
    }


def verify_acceptance_receipts(
    directory: Path,
    *,
    repository_root: Path,
    contract_path: Path = DEFAULT_RECEIPT_CONTRACT,
) -> dict[str, Any]:
    """Verify completeness, cryptographic bindings, role evidence and honest status ordering."""
    root = repository_root.resolve()
    contract = load_receipt_contract(
        contract_path,
        deployment_manifest_path=root / "config" / "foundry_deployment_manifest.json",
    )
    expected_bindings = expected_receipt_bindings(contract, root)
    rules = _mapping(contract["receipts"], "receipts")
    required_ids = set(rules)
    present_paths = {path.stem: path for path in directory.glob("*.json") if path.is_file()}
    missing = sorted(required_ids - set(present_paths))
    unexpected = sorted(set(present_paths) - required_ids)
    failures: list[str] = []
    timestamps: dict[str, dt.datetime] = {}
    common_bindings: dict[str, set[str]] = {
        "source_commit": set(),
        "infrastructure_fingerprint": set(),
        "worker_image_digest": set(),
    }

    for receipt_id in sorted(required_ids & set(present_paths)):
        receipt = _load(present_paths[receipt_id], f"receipt {receipt_id}")
        timestamp, bindings = _validate_receipt(
            receipt,
            receipt_id=receipt_id,
            rule=_mapping(rules[receipt_id], f"rule {receipt_id}"),
            expected_bindings=expected_bindings,
        )
        timestamps[receipt_id] = timestamp
        for key, value in bindings.items():
            common_bindings[key].add(value)
        if receipt["result"] != "PASS":
            failures.append(receipt_id)

    inconsistent = sorted(key for key, values in common_bindings.items() if len(values) > 1)
    if inconsistent:
        raise ReceiptContractError(
            "receipts do not share deployment bindings: " + ", ".join(inconsistent)
        )
    if "honest_public_status" in timestamps:
        other_times = [
            value for key, value in timestamps.items() if key != "honest_public_status"
        ]
        if other_times and timestamps["honest_public_status"] < max(other_times):
            raise ReceiptContractError("honest public status predates another acceptance receipt")

    if failures:
        status = str(contract["failed_status"])
    elif missing or unexpected:
        status = str(contract["incomplete_status"])
    else:
        status = str(contract["accepted_status"])
    report: dict[str, Any] = {
        "schema": "canli.foundry-acceptance-verification.v1",
        "status": status,
        "claim_boundary": (
            "ACCEPTED_OPERATIONAL means only that every contract-bound receipt is present and "
            "machine-valid. Any incomplete or failed set remains explicitly not operational."
        ),
        "receipt_contract_hash": canonical_sha256(contract),
        "required_receipts": len(required_ids),
        "valid_receipts_present": len(timestamps),
        "missing_receipts": missing,
        "unexpected_receipts": unexpected,
        "failed_receipts": sorted(failures),
        "shared_bindings": {
            key: next(iter(values)) if len(values) == 1 else None
            for key, values in sorted(common_bindings.items())
        },
    }
    report["content_hash"] = canonical_sha256(report)
    return report
