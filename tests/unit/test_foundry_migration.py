from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from alphaforge.foundry.contract import canonical_sha256
from alphaforge.foundry.migration import (
    MigrationContractError,
    assert_replay_environment,
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


def test_archival_preflight_does_not_authorize_replay_in_patched_workspace() -> None:
    packet, report = load_and_verify_legacy_migration(
        PACKET,
        repository_root=ROOT,
        verify_private_snapshot=False,
    )
    assert report["replay_environment_files_match"] is False
    assert any(r["status"] == "HISTORICAL_ARCHIVE_ONLY" for r in report["environment_resolution"])
    with pytest.raises(MigrationContractError, match="Replay blocked"):
        assert_replay_environment(packet)


def test_exact_historical_workspace_is_rechecked_before_enqueue(tmp_path: Path) -> None:
    from alphaforge.environment_archive import resolve_environment_binding
    from alphaforge.foundry.database import FoundryDatabase

    for binding in json.loads(PACKET.read_text())["source_bindings"]:
        if binding["availability"] != "TRACKED":
            continue
        relative = binding["path"]
        source = ROOT / relative
        if binding["name"] == "research_lockfile":
            resolution = resolve_environment_binding(ROOT, relative, binding["sha256"])
            source = ROOT / resolution.resolved_path
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    packet, report = load_and_verify_legacy_migration(
        PACKET,
        repository_root=tmp_path,
        verify_private_snapshot=False,
    )
    assert report["replay_environment_files_match"] is True
    assert_replay_environment(packet)
    (tmp_path / "uv.lock").write_text("changed after preflight")
    # Must fail before opening any database connection, even after a passing preflight.
    with pytest.raises(MigrationContractError, match="Replay blocked"):
        FoundryDatabase("postgresql://invalid.invalid/no-connection").enqueue_legacy_replay(
            packet=packet,
            image_digest="registry.invalid/image@sha256:" + "a" * 64,
            source_commit="b" * 40,
        )
