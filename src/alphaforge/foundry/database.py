"""PostgreSQL adapter for the Foundry controller and worker lease protocol."""

from __future__ import annotations

import importlib
import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, cast

from alphaforge.foundry.contract import FoundryContract, canonical_sha256
from alphaforge.foundry.migration import LegacyMigrationPacket
from alphaforge.foundry.policy import FoundryPolicy

BROKER_ENVIRONMENT_KEY: Final[re.Pattern[str]] = re.compile(
    r"(?:ALPACA|BROKER).*(?:KEY|SECRET|TOKEN|CREDENTIAL)|"
    r"(?:KEY|SECRET|TOKEN|CREDENTIAL).*(?:ALPACA|BROKER)",
    re.IGNORECASE,
)
DSN_ENV: Final[str] = "FOUNDRY_DATABASE_DSN"


class DatabaseContractError(RuntimeError):
    """The database is absent, stale, unauthorized, or contract-incompatible."""


class CredentialBoundaryError(RuntimeError):
    """A broker-write credential is present inside a Foundry process."""


def assert_no_broker_credentials(environment: Mapping[str, str] = os.environ) -> None:
    """Fail startup based on environment key names without reading or logging values."""
    forbidden = sorted(key for key in environment if BROKER_ENVIRONMENT_KEY.search(key))
    if forbidden:
        names = ", ".join(forbidden)
        raise CredentialBoundaryError(
            f"Foundry startup refused because broker credential variables are present: {names}"
        )


@dataclass(frozen=True, slots=True)
class TransitionRequest:
    trial_id: uuid.UUID
    expected_state: str
    target_state: str
    action: str
    actor_kind: str
    actor_id: str
    actor_role: str | None
    authorization_reference: str
    source_commit: str | None = None
    image_digest: str | None = None
    data_snapshot_hash: str | None = None
    job_manifest_hash: str | None = None
    result_artifact_hash: str | None = None

    @property
    def event_payload_hash(self) -> str:
        return canonical_sha256(
            {
                "trial_id": str(self.trial_id),
                "expected_state": self.expected_state,
                "target_state": self.target_state,
                "action": self.action,
                "actor_kind": self.actor_kind,
                "actor_id": self.actor_id,
                "actor_role": self.actor_role,
                "authorization_reference": self.authorization_reference,
                "source_commit": self.source_commit,
                "image_digest": self.image_digest,
                "data_snapshot_hash": self.data_snapshot_hash,
                "job_manifest_hash": self.job_manifest_hash,
                "result_artifact_hash": self.result_artifact_hash,
            }
        )


class FoundryDatabase:
    """Narrow database interface; DSN and row contents are never logged here."""

    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise DatabaseContractError("Foundry database DSN is empty")
        self._dsn = dsn

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] = os.environ
    ) -> FoundryDatabase:
        assert_no_broker_credentials(environment)
        dsn = environment.get(DSN_ENV)
        if not dsn:
            raise DatabaseContractError(f"required environment variable is absent: {DSN_ENV}")
        return cls(dsn)

    def _connect(self) -> Any:
        try:
            psycopg = importlib.import_module("psycopg")
            rows = importlib.import_module("psycopg.rows")
        except ModuleNotFoundError as error:
            raise DatabaseContractError(
                "Psycopg is a deployment-only runtime requirement; install the pinned "
                "deploy/foundry/requirements.lock without changing the research lockfile"
            ) from error
        return psycopg.connect(self._dsn, row_factory=rows.dict_row)

    def bind_contract(
        self,
        *,
        contract: FoundryContract,
        policy: FoundryPolicy,
        activated_by: str,
    ) -> None:
        """Load an empty database once; reject silent lifecycle or policy drift thereafter."""
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT lifecycle_hash, policy_hash FROM foundry.contract_binding WHERE singleton"
            )
            existing = cursor.fetchone()
            if existing is not None:
                expected = (contract.content_hash, policy.content_hash)
                observed = (existing["lifecycle_hash"], existing["policy_hash"])
                if observed != expected:
                    raise DatabaseContractError(
                        "Foundry database binding differs from the reviewed repository contracts"
                    )
                return

            cursor.executemany(
                """
                INSERT INTO foundry.lifecycle_state (
                    name, public_label, identity_spent, return_outcome_access,
                    holdout_access, broker_write_access, terminal
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                contract.database_states(),
            )
            cursor.executemany(
                """
                INSERT INTO foundry.lifecycle_transition (
                    source_state, target_state, action, authorization_kind, allowed_roles
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                contract.database_transitions(),
            )
            cursor.execute(
                """
                INSERT INTO foundry.contract_binding (
                    lifecycle_schema, lifecycle_version, lifecycle_hash, policy_hash,
                    observed_identities, identity_budget, next_hard_review, activated_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    contract.schema,
                    contract.version,
                    contract.content_hash,
                    policy.content_hash,
                    policy.observed_identities,
                    policy.identity_budget,
                    policy.next_hard_review,
                    activated_by,
                ),
            )

    def create_feasibility_trial(
        self,
        *,
        private_hypothesis: Mapping[str, object],
        actor_id: str,
        authorization_reference: str,
    ) -> dict[str, Any]:
        """Register metadata-only feasibility without spending an identity."""
        trial_id = uuid.uuid4()
        public_trial_id = f"ft_{trial_id.hex[:16]}"
        hypothesis_hash = canonical_sha256(private_hypothesis)
        event_hash = canonical_sha256(
            {
                "trial_id": str(trial_id),
                "public_trial_id": public_trial_id,
                "next_state": "FEASIBILITY",
                "action": "register_feasibility",
                "actor_id": actor_id,
                "authorization_reference": authorization_reference,
            }
        )
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM foundry.register_feasibility(%s, %s, %s, %s, %s, %s)
                """,
                (
                    trial_id,
                    public_trial_id,
                    hypothesis_hash,
                    actor_id,
                    authorization_reference,
                    event_hash,
                ),
            )
            trial = cursor.fetchone()
            if trial is None:
                raise DatabaseContractError("database did not return the created trial")
            return cast(dict[str, Any], trial)

    def transition(
        self,
        request: TransitionRequest,
        *,
        contract: FoundryContract,
    ) -> dict[str, Any]:
        """Authorize in application code and re-enforce inside one database transaction."""
        contract.authorize(
            source=request.expected_state,
            target=request.target_state,
            action=request.action,
            actor_kind=request.actor_kind,
            actor_role=request.actor_role,
        )
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM foundry.transition_trial(
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
                """,
                (
                    request.trial_id,
                    request.expected_state,
                    request.target_state,
                    request.action,
                    request.actor_kind,
                    request.actor_id,
                    request.actor_role,
                    request.authorization_reference,
                    request.event_payload_hash,
                    request.source_commit,
                    request.image_digest,
                    request.data_snapshot_hash,
                    request.job_manifest_hash,
                    request.result_artifact_hash,
                ),
            )
            trial = cursor.fetchone()
            if trial is None:
                raise DatabaseContractError("database transition returned no trial")
            return cast(dict[str, Any], trial)

    def import_legacy_killed(
        self,
        *,
        packet: LegacyMigrationPacket,
        source_commit: str,
        actor_id: str,
        authorization_reference: str,
    ) -> dict[str, Any]:
        """Import one hash-bound historical kill without allocating a new identity."""
        event_hash = canonical_sha256(
            {
                "migration_key": packet.migration_key,
                "trial_id": str(packet.trial_id),
                "public_trial_id": packet.public_trial_id,
                "historical_identity_key": packet.historical_identity_key,
                "identity_packet_hash": packet.identity_packet_hash,
                "input_snapshot_hash": packet.input_snapshot_hash,
                "expected_result_hash": packet.expected_result_hash,
                "prior_replay_receipt_hash": packet.prior_replay_receipt_hash,
                "migration_manifest_hash": packet.manifest_hash,
                "source_commit": source_commit,
                "actor_id": actor_id,
                "authorization_reference": authorization_reference,
            }
        )
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM foundry.import_legacy_killed_trial(
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    packet.migration_key,
                    packet.trial_id,
                    packet.public_trial_id,
                    packet.historical_identity_key,
                    packet.private_hypothesis_hash,
                    packet.historical_recorded_at,
                    packet.identity_packet_hash,
                    packet.input_snapshot_hash,
                    packet.expected_result_hash,
                    packet.prior_replay_receipt_hash,
                    packet.manifest_hash,
                    source_commit,
                    actor_id,
                    authorization_reference,
                    event_hash,
                ),
            )
            trial = cursor.fetchone()
            if trial is None:
                raise DatabaseContractError("database legacy import returned no trial")
            return cast(dict[str, Any], trial)

    def enqueue_legacy_replay(
        self,
        *,
        packet: LegacyMigrationPacket,
        image_digest: str,
        source_commit: str,
    ) -> dict[str, Any]:
        """Queue the packet's exact one-shot, no-network replay manifest."""
        replay = cast(dict[str, Any], packet.document["replay"])
        quota = cast(dict[str, int], replay["quota"])
        job_manifest_hash = canonical_sha256(
            {
                "migration_manifest_hash": packet.manifest_hash,
                "trial_id": str(packet.trial_id),
                "argv": replay["argv"],
                "shell": replay["shell"],
                "network_policy": replay["network_policy"],
                "workspace": replay["workspace"],
                "historical_ledger_mode": replay["historical_ledger_mode"],
                "expected_result_path": replay["expected_result_path"],
                "expected_result_hash": packet.expected_result_hash,
                "quota": quota,
                "image_digest": image_digest,
                "source_commit": source_commit,
            }
        )
        job_id = uuid.uuid4()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM foundry.enqueue_job(
                    %s, %s, 'CLEAN_REPLAY', %s, %s, %s,
                    %s, %s, %s, %s, %s, 'NONE', 1
                )
                """,
                (
                    job_id,
                    packet.trial_id,
                    job_manifest_hash,
                    image_digest,
                    source_commit,
                    quota["cpu_millis"],
                    quota["memory_mebibytes"],
                    quota["process_limit"],
                    quota["disk_mebibytes"],
                    quota["wall_seconds"],
                ),
            )
            job = cursor.fetchone()
            if job is None:
                raise DatabaseContractError("database legacy replay enqueue returned no job")
            return cast(dict[str, Any], job)

    def finalize_legacy_replay(
        self,
        *,
        trial_id: uuid.UUID,
        job_id: uuid.UUID,
        observed_object_hash: str,
        validator_id: str,
        authorization_reference: str,
    ) -> dict[str, Any]:
        event_hash = canonical_sha256(
            {
                "trial_id": str(trial_id),
                "job_id": str(job_id),
                "observed_object_hash": observed_object_hash,
                "validator_id": validator_id,
                "authorization_reference": authorization_reference,
            }
        )
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM foundry.finalize_legacy_replay(%s, %s, %s, %s, %s, %s)",
                (
                    trial_id,
                    job_id,
                    observed_object_hash,
                    validator_id,
                    authorization_reference,
                    event_hash,
                ),
            )
            trial = cursor.fetchone()
            if trial is None:
                raise DatabaseContractError("database legacy replay finalizer returned no trial")
            return cast(dict[str, Any], trial)

    def enqueue_legacy_sanitizer(
        self,
        *,
        packet: LegacyMigrationPacket,
        image_digest: str,
        source_commit: str,
    ) -> dict[str, Any]:
        """Queue the allowlisted sanitizer after the database has recorded replay PASS."""
        publication = cast(dict[str, Any], packet.document["publication"])
        job_manifest_hash = canonical_sha256(
            {
                "migration_manifest_hash": packet.manifest_hash,
                "trial_id": str(packet.trial_id),
                "required_replay_status": publication["required_replay_status"],
                "public_fields_only": publication["public_fields_only"],
                "forbidden_claims": publication["forbidden_claims"],
                "image_digest": image_digest,
                "source_commit": source_commit,
            }
        )
        job_id = uuid.uuid4()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM foundry.enqueue_job(
                    %s, %s, 'SANITIZE', %s, %s, %s,
                    500, 256, 32, 512, 60, 'PUBLICATION_ONLY', 1
                )
                """,
                (
                    job_id,
                    packet.trial_id,
                    job_manifest_hash,
                    image_digest,
                    source_commit,
                ),
            )
            job = cursor.fetchone()
            if job is None:
                raise DatabaseContractError("database legacy sanitizer enqueue returned no job")
            return cast(dict[str, Any], job)

    def publish_legacy_packet(
        self,
        *,
        trial_id: uuid.UUID,
        job_id: uuid.UUID,
        observed_sanitized_hash: str,
        publisher_id: str,
        authorization_reference: str,
    ) -> dict[str, Any]:
        event_hash = canonical_sha256(
            {
                "trial_id": str(trial_id),
                "job_id": str(job_id),
                "observed_sanitized_hash": observed_sanitized_hash,
                "publisher_id": publisher_id,
                "authorization_reference": authorization_reference,
            }
        )
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM foundry.publish_legacy_packet(%s, %s, %s, %s, %s, %s)",
                (
                    trial_id,
                    job_id,
                    observed_sanitized_hash,
                    publisher_id,
                    authorization_reference,
                    event_hash,
                ),
            )
            trial = cursor.fetchone()
            if trial is None:
                raise DatabaseContractError("database legacy publisher returned no trial")
            return cast(dict[str, Any], trial)

    def claim_job(self, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM foundry.claim_job(%s, %s)",
                (worker_id, lease_seconds),
            )
            return cast(dict[str, Any] | None, cursor.fetchone())

    def complete_job(
        self,
        *,
        job_id: uuid.UUID,
        worker_id: str,
        status: str,
        result_artifact_hash: str | None,
    ) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM foundry.complete_job(%s, %s, %s, %s)",
                (job_id, worker_id, status, result_artifact_hash),
            )
            job = cursor.fetchone()
            if job is None:
                raise DatabaseContractError("database completion returned no job")
            return cast(dict[str, Any], job)

    def public_status_inputs(self) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """Read only public-safe columns and aggregate operational counters."""
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT public_trial_id, state, identity_spent, reserved_at, updated_at,
                       artifact_hash, replay_status
                  FROM foundry.trial
                 ORDER BY public_trial_id
                """
            )
            trials = cursor.fetchall()
            for trial in trials:
                for field in ("reserved_at", "updated_at"):
                    value = trial.get(field)
                    if value is not None:
                        trial[field] = value.isoformat()
            cursor.execute(
                """
                SELECT
                    count(*) FILTER (WHERE status = 'QUEUED')::integer AS queue_depth,
                    COALESCE(sum(
                        EXTRACT(EPOCH FROM (completed_at - started_at))
                    ) FILTER (
                        WHERE completed_at IS NOT NULL AND started_at IS NOT NULL
                    ), 0)::integer
                        AS compute_seconds,
                    count(*) FILTER (WHERE status = 'SUCCEEDED')::integer AS successful_jobs,
                    count(*) FILTER (WHERE status = 'FAILED')::integer AS failed_jobs,
                    count(*) FILTER (WHERE status = 'QUOTA_BREACH')::integer AS quota_breaches
                FROM foundry.job
                """
            )
            counters = cursor.fetchone()
            if counters is None:
                raise DatabaseContractError("database status aggregation returned no row")
            return trials, {key: int(value) for key, value in counters.items()}
