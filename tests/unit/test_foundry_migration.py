from __future__ import annotations

import json
from pathlib import Path

import pytest

from alphaforge.foundry.contract import canonical_sha256
from alphaforge.foundry.migration import (
    MigrationContractError,
    load_and_verify_legacy_migration,
)

ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / "config/foundry_legacy_migrations/eia_petroleum_inventory_v1.json"


def test_production_migration_selects_complete_kill_without_claiming_execution() -> None:
    packet, report = load_and_verify_legacy_migration(
        PACKET,
        repository_root=ROOT,
        verify_private_snapshot=False,
    )
    assert packet.public_trial_id == "ft_a9ae69f6bc4a5269"
    assert packet.historical_identity_key == "8446702cb8dd1768"
    assert report["status"] == "PASS_TRACKED_BINDINGS_PRIVATE_SNAPSHOT_DEFERRED"
    assert report["new_identity_spent"] is False
    assert report["foundry_replay_completed"] is False
    assert report["sanitized_publication_completed"] is False
    assert report["deferred_private_source_bindings"] == ["complete_identity_packet"]


@pytest.mark.workspace_evidence
def test_production_private_snapshot_expands_every_referenced_object() -> None:
    _, report = load_and_verify_legacy_migration(
        PACKET,
        repository_root=ROOT,
        verify_private_snapshot=True,
    )
    assert report["status"] == "PASS_FULL_PRIVATE_SNAPSHOT_PREDEPLOYMENT_ONLY"
    assert report["private_snapshot_objects_verified"] == 851


def test_tracked_binding_tamper_fails_closed(tmp_path: Path) -> None:
    document = json.loads(PACKET.read_text())
    document["source_bindings"][0]["sha256"] = "0" * 64
    tampered = tmp_path / "migration.json"
    tampered.write_text(json.dumps(document))
    with pytest.raises(MigrationContractError, match="source binding hash mismatch"):
        load_and_verify_legacy_migration(
            tampered,
            repository_root=ROOT,
            verify_private_snapshot=False,
        )


def test_packet_cannot_allocate_a_new_foundry_identity(tmp_path: Path) -> None:
    document = json.loads(PACKET.read_text())
    document["trial"]["foundry_identity_ordinal"] = 229
    tampered = tmp_path / "migration.json"
    tampered.write_text(json.dumps(document))
    with pytest.raises(MigrationContractError, match="cannot allocate"):
        load_and_verify_legacy_migration(
            tampered,
            repository_root=ROOT,
            verify_private_snapshot=False,
        )


def test_packet_manifest_hash_binds_the_full_prepared_document() -> None:
    packet, _ = load_and_verify_legacy_migration(
        PACKET,
        repository_root=ROOT,
        verify_private_snapshot=False,
    )
    assert packet.manifest_hash == canonical_sha256(json.loads(PACKET.read_text()))
