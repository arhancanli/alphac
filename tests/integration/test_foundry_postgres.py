from __future__ import annotations

import importlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from alphaforge.foundry.contract import FoundryContract
from alphaforge.foundry.database import FoundryDatabase, TransitionRequest
from alphaforge.foundry.migration import LegacyMigrationPacket, load_and_verify_legacy_migration
from alphaforge.foundry.policy import load_foundry_policy

ADMIN_DSN = os.environ.get("FOUNDRY_TEST_ADMIN_DSN")
RESEARCHD_DSN = os.environ.get("FOUNDRY_TEST_RESEARCHD_DSN")
WORKER_DSN = os.environ.get("FOUNDRY_TEST_WORKER_DSN")
STATUS_DSN = os.environ.get("FOUNDRY_TEST_STATUS_DSN")
MIGRATOR_DSN = os.environ.get("FOUNDRY_TEST_MIGRATOR_DSN")
VALIDATOR_DSN = os.environ.get("FOUNDRY_TEST_VALIDATOR_DSN")
PUBLISHER_DSN = os.environ.get("FOUNDRY_TEST_PUBLISHER_DSN")
psycopg = importlib.import_module("psycopg") if ADMIN_DSN else None

pytestmark = pytest.mark.skipif(
    not all(
        (
            ADMIN_DSN,
            RESEARCHD_DSN,
            WORKER_DSN,
            STATUS_DSN,
            MIGRATOR_DSN,
            VALIDATOR_DSN,
            PUBLISHER_DSN,
        )
    ),
    reason="Foundry PostgreSQL role DSNs are not configured",
)


@pytest.fixture(scope="module")
def reserved_trial() -> dict[str, object]:
    assert ADMIN_DSN is not None
    assert psycopg is not None
    assert RESEARCHD_DSN is not None
    contract = FoundryContract.load()
    FoundryDatabase(ADMIN_DSN).bind_contract(
        contract=contract,
        policy=load_foundry_policy(),
        activated_by="ci:foundry-database-contract",
    )
    database = FoundryDatabase(RESEARCHD_DSN)
    created = database.create_feasibility_trial(
        private_hypothesis={"family": "ci-fixture", "outcome_data_read": False},
        actor_id="ci-research-author",
        authorization_reference="ci://proposal/1",
    )
    proposed = database.transition(
        TransitionRequest(
            trial_id=created["id"],
            expected_state="FEASIBILITY",
            target_state="PROPOSED",
            action="submit_preregistration",
            actor_kind="human",
            actor_id="ci-research-author",
            actor_role="research_author",
            authorization_reference="ci://preregistration/1",
        ),
        contract=contract,
    )
    return database.transition(
        TransitionRequest(
            trial_id=proposed["id"],
            expected_state="PROPOSED",
            target_state="RESERVED",
            action="reserve_identity",
            actor_kind="human",
            actor_id="ci-research-approver",
            actor_role="research_approver",
            authorization_reference="ci://approval/1",
        ),
        contract=contract,
    )


@pytest.fixture(scope="module")
def migrated_kill(
    reserved_trial: dict[str, object],
) -> tuple[LegacyMigrationPacket, dict[str, Any]]:
    assert reserved_trial["state"] == "RESERVED"
    assert MIGRATOR_DSN is not None
    root = Path(__file__).resolve().parents[2]
    packet, _ = load_and_verify_legacy_migration(
        root / "config/foundry_legacy_migrations/eia_petroleum_inventory_v1.json",
        repository_root=root,
        verify_private_snapshot=False,
    )
    trial = FoundryDatabase(MIGRATOR_DSN).import_legacy_killed(
        packet=packet,
        source_commit="a" * 40,
        actor_id="ci-migration-operator",
        authorization_reference="ci://migration/eia-petroleum-inventory-v1",
    )
    return packet, trial


@pytest.fixture(scope="module")
def replayed_kill(
    migrated_kill: tuple[LegacyMigrationPacket, dict[str, Any]],
) -> tuple[LegacyMigrationPacket, dict[str, Any]]:
    assert RESEARCHD_DSN is not None
    assert WORKER_DSN is not None
    assert VALIDATOR_DSN is not None
    packet, _ = migrated_kill
    job = FoundryDatabase(RESEARCHD_DSN).enqueue_legacy_replay(
        packet=packet,
        image_digest="registry.invalid/foundry@sha256:" + "b" * 64,
        source_commit="a" * 40,
    )
    claimed = FoundryDatabase(WORKER_DSN).claim_job("worker-ci-legacy-replay", 60)
    assert claimed is not None
    assert claimed["id"] == job["id"]
    FoundryDatabase(WORKER_DSN).complete_job(
        job_id=job["id"],
        worker_id="worker-ci-legacy-replay",
        status="SUCCEEDED",
        result_artifact_hash=packet.expected_result_hash,
    )
    trial = FoundryDatabase(VALIDATOR_DSN).finalize_legacy_replay(
        trial_id=packet.trial_id,
        job_id=job["id"],
        observed_object_hash=packet.expected_result_hash,
        validator_id="validator-ci-1",
        authorization_reference="ci://validation/eia-petroleum-inventory-v1",
    )
    return packet, trial


@pytest.fixture(scope="module")
def published_kill(
    replayed_kill: tuple[LegacyMigrationPacket, dict[str, Any]],
) -> tuple[LegacyMigrationPacket, dict[str, Any], str]:
    assert RESEARCHD_DSN is not None
    assert WORKER_DSN is not None
    assert PUBLISHER_DSN is not None
    packet, _ = replayed_kill
    sanitized_hash = "sha256:" + "e" * 64
    job = FoundryDatabase(RESEARCHD_DSN).enqueue_legacy_sanitizer(
        packet=packet,
        image_digest="registry.invalid/foundry@sha256:" + "b" * 64,
        source_commit="a" * 40,
    )
    claimed = FoundryDatabase(WORKER_DSN).claim_job("worker-ci-sanitizer", 60)
    assert claimed is not None
    assert claimed["id"] == job["id"]
    FoundryDatabase(WORKER_DSN).complete_job(
        job_id=job["id"],
        worker_id="worker-ci-sanitizer",
        status="SUCCEEDED",
        result_artifact_hash=sanitized_hash,
    )
    with pytest.raises(psycopg.errors.RaiseException, match="differs from worker result"):
        FoundryDatabase(PUBLISHER_DSN).publish_legacy_packet(
            trial_id=packet.trial_id,
            job_id=job["id"],
            observed_sanitized_hash="sha256:" + "f" * 64,
            publisher_id="publisher-ci-1",
            authorization_reference="ci://publication/eia-petroleum-inventory-v1",
        )
    published = FoundryDatabase(PUBLISHER_DSN).publish_legacy_packet(
        trial_id=packet.trial_id,
        job_id=job["id"],
        observed_sanitized_hash=sanitized_hash,
        publisher_id="publisher-ci-1",
        authorization_reference="ci://publication/eia-petroleum-inventory-v1",
    )
    return packet, published, sanitized_hash


def test_reservation_is_transactional_and_appends_audit_events(
    reserved_trial: dict[str, object],
) -> None:
    assert ADMIN_DSN is not None
    assert psycopg is not None
    assert reserved_trial["state"] == "RESERVED"
    assert reserved_trial["identity_spent"] is True
    assert reserved_trial["foundry_identity_ordinal"] == 229
    with psycopg.connect(ADMIN_DSN) as connection:
        events = connection.execute(
            "SELECT prior_state, next_state, action FROM foundry.audit_event "
            "WHERE trial_id = %s ORDER BY sequence",
            (reserved_trial["id"],),
        ).fetchall()
    assert events == [
        (None, "FEASIBILITY", "register_feasibility"),
        ("FEASIBILITY", "PROPOSED", "submit_preregistration"),
        ("PROPOSED", "RESERVED", "reserve_identity"),
    ]


def test_audit_event_rejects_update_even_for_database_owner(
    reserved_trial: dict[str, object],
) -> None:
    assert ADMIN_DSN is not None
    with (
        psycopg.connect(ADMIN_DSN) as connection,
        pytest.raises(psycopg.errors.RaiseException, match="append-only"),
    ):
        connection.execute(
            "UPDATE foundry.audit_event SET action = 'rewritten' WHERE trial_id = %s",
            (reserved_trial["id"],),
        )


def test_researchd_cannot_bypass_the_transition_function(
    reserved_trial: dict[str, object],
) -> None:
    assert RESEARCHD_DSN is not None
    assert psycopg is not None
    with (
        psycopg.connect(RESEARCHD_DSN) as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        connection.execute(
            "UPDATE foundry.trial SET state = 'ADMITTED' WHERE id = %s",
            (reserved_trial["id"],),
        )


def test_worker_lease_is_single_claim_under_concurrency(
    reserved_trial: dict[str, object],
) -> None:
    assert RESEARCHD_DSN is not None
    assert WORKER_DSN is not None
    assert psycopg is not None
    job_id = uuid.uuid4()
    with psycopg.connect(RESEARCHD_DSN) as connection:
        connection.execute(
            """
            SELECT * FROM foundry.enqueue_job(
                %s, %s, 'SNAPSHOT', %s, %s, %s,
                1000, 512, 64, 1024, 300, 'DATA_GATEWAY_ONLY', 1
            )
            """,
            (
                job_id,
                reserved_trial["id"],
                "sha256:" + "1" * 64,
                "registry.invalid/foundry@sha256:" + "2" * 64,
                "a" * 40,
            ),
        )

    def claim(worker: str) -> dict[str, object] | None:
        return FoundryDatabase(WORKER_DSN).claim_job(worker, 60)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, ("worker-ci-1", "worker-ci-2")))
    won = [claim for claim in claims if claim is not None]
    assert len(won) == 1
    assert won[0]["id"] == job_id
    assert won[0]["attempts"] == 1
    FoundryDatabase(WORKER_DSN).complete_job(
        job_id=job_id,
        worker_id=str(won[0]["lease_owner"]),
        status="SUCCEEDED",
        result_artifact_hash="sha256:" + "3" * 64,
    )


def test_status_role_cannot_read_private_hypothesis_hash() -> None:
    assert STATUS_DSN is not None
    assert psycopg is not None
    with (
        psycopg.connect(STATUS_DSN) as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        connection.execute("SELECT private_hypothesis_hash FROM foundry.trial").fetchall()


def test_legacy_import_preserves_kill_without_spending_foundry_ordinal(
    migrated_kill: tuple[LegacyMigrationPacket, dict[str, Any]],
) -> None:
    assert ADMIN_DSN is not None
    assert psycopg is not None
    packet, trial = migrated_kill
    assert trial["public_trial_id"] == packet.public_trial_id
    assert trial["state"] == "KILLED"
    assert trial["identity_spent"] is True
    assert trial["foundry_identity_ordinal"] is None
    assert trial["migrated_legacy"] is True
    assert trial["replay_status"] == "NOT_RUN"
    with psycopg.connect(ADMIN_DSN) as connection:
        foundry_ordinals = connection.execute(
            "SELECT count(*) FROM foundry.trial WHERE foundry_identity_ordinal IS NOT NULL"
        ).fetchone()[0]
    assert foundry_ordinals == 1


def test_migration_role_cannot_read_private_migration_table(
    migrated_kill: tuple[LegacyMigrationPacket, dict[str, Any]],
) -> None:
    assert migrated_kill[1]["state"] == "KILLED"
    assert MIGRATOR_DSN is not None
    assert psycopg is not None
    with (
        psycopg.connect(MIGRATOR_DSN) as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        connection.execute("SELECT * FROM foundry.legacy_migration").fetchall()


def test_replay_pass_requires_exact_historical_result_hash(
    replayed_kill: tuple[LegacyMigrationPacket, dict[str, Any]],
) -> None:
    packet, trial = replayed_kill
    assert trial["public_trial_id"] == packet.public_trial_id
    assert trial["state"] == "KILLED"
    assert trial["replay_status"] == "PASS"
    assert trial["artifact_hash"] is None


def test_legacy_replay_is_one_shot_after_validation(
    replayed_kill: tuple[LegacyMigrationPacket, dict[str, Any]],
) -> None:
    assert RESEARCHD_DSN is not None
    assert psycopg is not None
    packet, _ = replayed_kill
    with pytest.raises(psycopg.errors.RaiseException, match="one-shot"):
        FoundryDatabase(RESEARCHD_DSN).enqueue_legacy_replay(
            packet=packet,
            image_digest="registry.invalid/foundry@sha256:" + "b" * 64,
            source_commit="a" * 40,
        )


def test_sanitized_packet_can_be_bound_only_after_passing_replay(
    published_kill: tuple[LegacyMigrationPacket, dict[str, Any], str],
) -> None:
    _, published, sanitized_hash = published_kill
    assert published["state"] == "KILLED"
    assert published["replay_status"] == "PASS"
    assert published["artifact_hash"] == sanitized_hash


def test_legacy_audit_events_remain_append_only_and_named(
    published_kill: tuple[LegacyMigrationPacket, dict[str, Any], str],
) -> None:
    assert ADMIN_DSN is not None
    assert psycopg is not None
    packet, _, _ = published_kill
    with psycopg.connect(ADMIN_DSN) as connection:
        actions = connection.execute(
            "SELECT action FROM foundry.audit_event WHERE trial_id = %s ORDER BY sequence",
            (packet.trial_id,),
        ).fetchall()
    assert [row[0] for row in actions] == [
        "import_legacy_killed_identity",
        "confirm_legacy_clean_replay",
        "publish_legacy_sanitized_packet",
    ]
