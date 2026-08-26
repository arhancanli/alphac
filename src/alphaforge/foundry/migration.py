"""Fail-closed preparation of historical killed-trial migrations."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from alphaforge.foundry.contract import canonical_sha256

MIGRATION_SCHEMA: Final[str] = "canli.foundry-legacy-killed-migration.v1"
DIGEST: Final[re.Pattern[str]] = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
PUBLIC_TRIAL_ID: Final[re.Pattern[str]] = re.compile(r"^ft_[0-9a-f]{16}$")
MIGRATION_KEY: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9-]{2,95}$")


class MigrationContractError(ValueError):
    """A migration packet or one of its immutable inputs is invalid."""


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MigrationContractError(f"{field} must be an object")
    return {str(key): nested for key, nested in value.items()}


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise MigrationContractError(f"{field} must be a non-empty string")
    return value


def _digest(value: object, field: str, *, prefix: bool) -> str:
    text = _string(value, field)
    if DIGEST.fullmatch(text) is None:
        raise MigrationContractError(f"{field} must be a SHA-256 digest")
    if prefix and not text.startswith("sha256:"):
        raise MigrationContractError(f"{field} must include the sha256: prefix")
    if not prefix and text.startswith("sha256:"):
        raise MigrationContractError(f"{field} must omit the sha256: prefix")
    return text


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(root: Path, relative: object, field: str) -> Path:
    text = _string(relative, field)
    candidate = (root / text).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise MigrationContractError(f"{field} escapes the repository root") from error
    return candidate


def _load_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MigrationContractError(f"cannot load {field}: {path}") from error
    return _mapping(value, field)


def _verify_semantic_hash(document: dict[str, Any], expected: str, field: str) -> None:
    payload = dict(document)
    claimed = payload.pop("content_hash", None)
    observed = canonical_sha256(payload)
    if claimed != expected or observed != expected:
        raise MigrationContractError(f"{field} semantic content hash mismatch")


@dataclass(frozen=True, slots=True)
class LegacyMigrationPacket:
    """Validated import fields plus the complete source packet."""

    path: Path
    document: dict[str, Any]
    manifest_hash: str
    trial_id: uuid.UUID
    public_trial_id: str
    historical_identity_key: str
    private_hypothesis_hash: str
    historical_recorded_at: str
    identity_packet_hash: str
    input_snapshot_hash: str
    expected_result_hash: str
    prior_replay_receipt_hash: str

    @property
    def migration_key(self) -> str:
        return cast(str, self.document["migration_key"])


def _validate_packet_shape(path: Path, document: dict[str, Any]) -> LegacyMigrationPacket:
    if document.get("schema") != MIGRATION_SCHEMA:
        raise MigrationContractError("unexpected legacy migration schema")
    if document.get("status") != "PREPARED_NOT_IMPORTED_OR_REPLAYED":
        raise MigrationContractError("legacy migration must remain explicitly unexecuted")
    migration_key = _string(document.get("migration_key"), "migration_key")
    if MIGRATION_KEY.fullmatch(migration_key) is None:
        raise MigrationContractError("migration_key is malformed")

    trial = _mapping(document.get("trial"), "trial")
    try:
        trial_id = uuid.UUID(_string(trial.get("database_id"), "trial.database_id"))
    except ValueError as error:
        raise MigrationContractError("trial.database_id must be a UUID") from error
    public_trial_id = _string(trial.get("public_trial_id"), "trial.public_trial_id")
    if PUBLIC_TRIAL_ID.fullmatch(public_trial_id) is None:
        raise MigrationContractError("trial.public_trial_id is malformed")
    if public_trial_id != f"ft_{trial_id.hex[:16]}":
        raise MigrationContractError("public trial identifier is not derived from database UUID")
    if trial.get("state") != "KILLED" or trial.get("identity_spent") is not True:
        raise MigrationContractError("legacy import must preserve a spent KILLED identity")
    if trial.get("foundry_identity_ordinal") is not None:
        raise MigrationContractError("legacy import cannot allocate a Foundry identity ordinal")
    if trial.get("migrated_legacy") is not True:
        raise MigrationContractError("legacy import marker is absent")
    if trial.get("holdout_consumptions") != 0:
        raise MigrationContractError("the selected killed identity must not claim holdout access")

    security = _mapping(document.get("security"), "security")
    if any(value is not False for value in security.values()):
        raise MigrationContractError("every legacy migration security capability must be false")
    replay = _mapping(document.get("replay"), "replay")
    if replay.get("status") != "NOT_RUN_IN_FOUNDRY":
        raise MigrationContractError("Foundry replay status must remain NOT_RUN_IN_FOUNDRY")
    if replay.get("shell") is not False or replay.get("network_policy") != "NONE":
        raise MigrationContractError("legacy replay must use argv execution with no network")
    argv = replay.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(item, str) for item in argv):
        raise MigrationContractError("replay.argv must be a non-empty string array")
    if replay.get("max_attempts") != 1:
        raise MigrationContractError("legacy replay must be one-shot")
    expected_result_hash = "sha256:" + _digest(
        replay.get("expected_result_sha256"), "replay.expected_result_sha256", prefix=False
    )

    source_bindings = document.get("source_bindings")
    if not isinstance(source_bindings, list) or not source_bindings:
        raise MigrationContractError("source_bindings must be a non-empty array")
    bindings_by_name: dict[str, dict[str, Any]] = {}
    for index, raw_binding in enumerate(source_bindings):
        binding = _mapping(raw_binding, f"source_bindings[{index}]")
        name = _string(binding.get("name"), f"source_bindings[{index}].name")
        if name in bindings_by_name:
            raise MigrationContractError(f"duplicate source binding: {name}")
        bindings_by_name[name] = binding
    required = {
        "publication_trial_accounting",
        "complete_identity_packet",
        "preregistration",
        "historical_result",
        "prior_isolated_replay_receipt",
        "reproduction_contract",
        "runner",
        "python_project",
        "research_lockfile",
    }
    if set(bindings_by_name) != required:
        raise MigrationContractError("legacy migration source binding inventory drifted")

    identity_packet_hash = _digest(
        bindings_by_name["complete_identity_packet"].get("semantic_content_hash"),
        "complete_identity_packet.semantic_content_hash",
        prefix=True,
    )
    if trial.get("private_hypothesis_hash") != identity_packet_hash:
        raise MigrationContractError("trial identity hash differs from complete packet hash")
    prior_replay_receipt_hash = _digest(
        bindings_by_name["prior_isolated_replay_receipt"].get("semantic_content_hash"),
        "prior_isolated_replay_receipt.semantic_content_hash",
        prefix=True,
    )
    snapshot = _mapping(document.get("private_input_snapshot"), "private_input_snapshot")
    input_snapshot_hash = _digest(
        snapshot.get("semantic_content_hash"),
        "private_input_snapshot.semantic_content_hash",
        prefix=True,
    )

    return LegacyMigrationPacket(
        path=path,
        document=document,
        manifest_hash=canonical_sha256(document),
        trial_id=trial_id,
        public_trial_id=public_trial_id,
        historical_identity_key=_string(
            trial.get("historical_identity_key"), "trial.historical_identity_key"
        ),
        private_hypothesis_hash=identity_packet_hash,
        historical_recorded_at=_string(
            trial.get("historical_recorded_at"), "trial.historical_recorded_at"
        ),
        identity_packet_hash=identity_packet_hash,
        input_snapshot_hash=input_snapshot_hash,
        expected_result_hash=expected_result_hash,
        prior_replay_receipt_hash=prior_replay_receipt_hash,
    )


def _verify_binding(
    root: Path,
    binding: dict[str, Any],
    *,
    verify_private_snapshot: bool,
) -> tuple[str, bool]:
    name = _string(binding.get("name"), "source binding name")
    availability = binding.get("availability")
    if availability not in {"TRACKED", "PRIVATE_SNAPSHOT_REQUIRED"}:
        raise MigrationContractError(f"unsupported availability for source binding: {name}")
    if availability == "PRIVATE_SNAPSHOT_REQUIRED" and not verify_private_snapshot:
        return name, False
    path = _safe_path(root, binding.get("path"), f"source binding {name}.path")
    if not path.is_file():
        raise MigrationContractError(f"required source binding is missing: {name}")
    expected = _digest(binding.get("sha256"), f"source binding {name}.sha256", prefix=False)
    if _sha256_file(path) != expected:
        raise MigrationContractError(f"source binding hash mismatch: {name}")
    semantic = binding.get("semantic_content_hash")
    if semantic is not None:
        expected_semantic = _digest(
            semantic, f"source binding {name}.semantic_content_hash", prefix=True
        )
        _verify_semantic_hash(_load_json(path, name), expected_semantic, name)
    return name, True


def _verify_snapshot_references(root: Path, snapshot_document: dict[str, Any]) -> int:
    references: list[tuple[object, object, str]] = [
        (
            snapshot_document.get("preregistration_path"),
            snapshot_document.get("preregistration_sha256"),
            "snapshot preregistration",
        ),
        (
            snapshot_document.get("events_path"),
            snapshot_document.get("events_sha256"),
            "snapshot events",
        ),
        (
            snapshot_document.get("first_release_manifest_path"),
            snapshot_document.get("first_release_manifest_sha256"),
            "snapshot first-release manifest",
        ),
    ]
    market = _mapping(snapshot_document.get("market_data_partitions"), "market_data_partitions")
    for symbol, raw_items in market.items():
        if not isinstance(raw_items, list) or not raw_items:
            raise MigrationContractError(f"market snapshot is empty: {symbol}")
        for index, raw_item in enumerate(raw_items):
            item = _mapping(raw_item, f"market_data_partitions.{symbol}[{index}]")
            references.append(
                (item.get("path"), item.get("sha256"), f"market snapshot {symbol}[{index}]")
            )
    curves = _mapping(snapshot_document.get("diversification_curves"), "diversification_curves")
    for name, raw_curve in curves.items():
        curve = _mapping(raw_curve, f"diversification_curves.{name}")
        references.append((curve.get("path"), curve.get("sha256"), f"curve {name}"))

    verified = 0
    for raw_path, raw_hash, label in references:
        path = _safe_path(root, raw_path, f"{label}.path")
        expected = _digest(raw_hash, f"{label}.sha256", prefix=False)
        if not path.is_file() or _sha256_file(path) != expected:
            raise MigrationContractError(f"private input snapshot mismatch: {label}")
        verified += 1

    release_manifest_path = _safe_path(
        root, snapshot_document.get("first_release_manifest_path"), "first-release manifest path"
    )
    release_manifest = _load_json(release_manifest_path, "first-release manifest")
    release_files = release_manifest.get("files")
    if not isinstance(release_files, list):
        raise MigrationContractError("first-release manifest has no file inventory")
    if snapshot_document.get("first_release_files_validated") != len(release_files):
        raise MigrationContractError("first-release file count differs from snapshot declaration")
    for index, raw_item in enumerate(release_files):
        item = _mapping(raw_item, f"first-release files[{index}]")
        path = _safe_path(root, item.get("path"), f"first-release files[{index}].path")
        expected = _digest(
            item.get("sha256"), f"first-release files[{index}].sha256", prefix=False
        )
        if not path.is_file() or _sha256_file(path) != expected:
            raise MigrationContractError(f"first-release source mismatch at index {index}")
        verified += 1
    return verified


def load_and_verify_legacy_migration(
    path: Path,
    *,
    repository_root: Path,
    verify_private_snapshot: bool,
) -> tuple[LegacyMigrationPacket, dict[str, Any]]:
    """Load a packet and hash every input in the requested trust scope."""
    document = _load_json(path, "legacy migration packet")
    packet = _validate_packet_shape(path, document)
    root = repository_root.resolve()

    raw_bindings = cast(list[object], document["source_bindings"])
    verified_files: list[str] = []
    deferred_files: list[str] = []
    for raw_binding in raw_bindings:
        binding = _mapping(raw_binding, "source binding")
        name, verified = _verify_binding(
            root, binding, verify_private_snapshot=verify_private_snapshot
        )
        (verified_files if verified else deferred_files).append(name)

    accounting_path = _safe_path(
        root,
        next(
            binding["path"]
            for binding in raw_bindings
            if isinstance(binding, Mapping)
            and binding.get("name") == "publication_trial_accounting"
        ),
        "publication trial accounting",
    )
    accounting = _load_json(accounting_path, "publication trial accounting")
    identities = accounting.get("identities")
    if not isinstance(identities, list):
        raise MigrationContractError("publication trial accounting has no identities")
    selected = [
        _mapping(identity, "publication identity")
        for identity in identities
        if isinstance(identity, Mapping)
        and identity.get("hypothesis_key") == packet.historical_identity_key
    ]
    if len(selected) != 1:
        raise MigrationContractError("historical identity is not unique in publication accounting")
    identity = selected[0]
    if (
        identity.get("identity_packet_status") != "COMPLETE_EVIDENCED_KILL"
        or _mapping(identity.get("completion_assessment"), "completion assessment").get("status")
        != "COMPLETE"
        or identity.get("identity_packet_content_hash") != packet.identity_packet_hash
    ):
        raise MigrationContractError(
            "selected historical identity is not a complete evidenced kill"
        )

    result_binding = next(
        _mapping(binding, "historical_result")
        for binding in raw_bindings
        if isinstance(binding, Mapping) and binding.get("name") == "historical_result"
    )
    result = _load_json(
        _safe_path(root, result_binding.get("path"), "historical result"), "historical result"
    )
    replay = _mapping(document.get("replay"), "replay")
    if result.get("verdict") != replay.get("expected_verdict"):
        raise MigrationContractError("historical result does not preserve the expected kill")

    snapshot_objects_verified = 0
    if verify_private_snapshot:
        snapshot = _mapping(document.get("private_input_snapshot"), "private_input_snapshot")
        snapshot_path = _safe_path(root, snapshot.get("manifest_path"), "snapshot manifest")
        expected_sha = _digest(
            snapshot.get("manifest_sha256"), "private_input_snapshot.manifest_sha256", prefix=False
        )
        if not snapshot_path.is_file() or _sha256_file(snapshot_path) != expected_sha:
            raise MigrationContractError("private input snapshot manifest hash mismatch")
        snapshot_document = _load_json(snapshot_path, "private input snapshot")
        _verify_semantic_hash(
            snapshot_document, packet.input_snapshot_hash, "private input snapshot"
        )
        snapshot_objects_verified = _verify_snapshot_references(root, snapshot_document)

    report: dict[str, Any] = {
        "schema": "canli.foundry-legacy-migration-preflight.v1",
        "status": (
            "PASS_FULL_PRIVATE_SNAPSHOT_PREDEPLOYMENT_ONLY"
            if verify_private_snapshot
            else "PASS_TRACKED_BINDINGS_PRIVATE_SNAPSHOT_DEFERRED"
        ),
        "claim_boundary": (
            "This preflight validates a prepared historical migration packet. It is not an "
            "import, Foundry replay, cloud deployment, sanitized publication or independent "
            "replication."
        ),
        "migration_key": packet.migration_key,
        "public_trial_id": packet.public_trial_id,
        "historical_identity_key": packet.historical_identity_key,
        "migration_manifest_hash": packet.manifest_hash,
        "verified_source_bindings": sorted(verified_files),
        "deferred_private_source_bindings": sorted(deferred_files),
        "private_snapshot_objects_verified": snapshot_objects_verified,
        "new_identity_spent": False,
        "foundry_replay_completed": False,
        "sanitized_publication_completed": False,
    }
    report["content_hash"] = canonical_sha256(report)
    return packet, report
