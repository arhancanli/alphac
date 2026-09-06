"""Operator commands for Foundry contract binding and sanitized status export."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Annotated

import typer

from alphaforge.foundry.contract import FoundryContract
from alphaforge.foundry.database import FoundryDatabase
from alphaforge.foundry.migration import load_and_verify_legacy_migration
from alphaforge.foundry.policy import load_foundry_policy
from alphaforge.foundry.receipts import verify_acceptance_receipts
from alphaforge.foundry.sanitizer import sanitize_public_status

foundry_app = typer.Typer(
    help="Operate the bounded Foundry research control plane.",
    no_args_is_help=True,
)

DEFAULT_LEGACY_MIGRATION = Path(
    "config/foundry_legacy_migrations/eia_petroleum_inventory_v1.json"
)


@foundry_app.command("bind-contract")
def bind_contract(
    activated_by: str = typer.Option(..., help="Dated operator or reviewed deployment receipt."),
) -> None:
    """Bind an empty migrated database to the exact repository contracts once."""
    database = FoundryDatabase.from_environment()
    contract = FoundryContract.load()
    policy = load_foundry_policy()
    database.bind_contract(contract=contract, policy=policy, activated_by=activated_by)
    typer.echo(
        json.dumps(
            {
                "status": "BOUND_OR_ALREADY_BOUND",
                "lifecycle_hash": contract.content_hash,
                "policy_hash": policy.content_hash,
                "next_hard_review": policy.next_hard_review,
            },
            sort_keys=True,
        )
    )


@foundry_app.command("export-public-status")
def export_public_status(
    output: Annotated[Path, typer.Option("--output", dir_okay=False)],
    restore_status: Annotated[str, typer.Option()] = "NOT_TESTED",
) -> None:
    """Export the allowlisted, secret-scanned public status document."""
    database = FoundryDatabase.from_environment()
    contract = FoundryContract.load()
    trials, counters = database.public_status_inputs()
    generated_at = dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")
    document = sanitize_public_status(
        trials=trials,
        contract=contract,
        generated_at=generated_at,
        queue_depth=counters["queue_depth"],
        compute_seconds=counters["compute_seconds"],
        successful_jobs=counters["successful_jobs"],
        failed_jobs=counters["failed_jobs"],
        quota_breaches=counters["quota_breaches"],
        restore_status=restore_status,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    typer.echo(f"wrote sanitized Foundry status: {output}")


@foundry_app.command("verify-legacy-migration")
def verify_legacy_migration(
    packet_path: Annotated[Path, typer.Option("--packet", dir_okay=False)] = (
        DEFAULT_LEGACY_MIGRATION
    ),
    repository_root: Annotated[Path, typer.Option("--repository-root", file_okay=False)] = Path(
        "."
    ),
    verify_private_snapshot: Annotated[
        bool, typer.Option("--verify-private-snapshot/--tracked-bindings-only")
    ] = False,
) -> None:
    """Verify the selected killed identity without importing or replaying it."""
    _, report = load_and_verify_legacy_migration(
        packet_path,
        repository_root=repository_root,
        verify_private_snapshot=verify_private_snapshot,
    )
    typer.echo(json.dumps(report, indent=2, sort_keys=True))


@foundry_app.command("import-legacy-killed")
def import_legacy_killed(
    source_commit: Annotated[str, typer.Option(help="Exact reviewed 40-character commit.")],
    actor_id: Annotated[str, typer.Option(help="Dated human migration operator identifier.")],
    authorization_reference: Annotated[
        str, typer.Option(help="Reviewed private deployment receipt reference.")
    ],
    packet_path: Annotated[Path, typer.Option("--packet", dir_okay=False)] = (
        DEFAULT_LEGACY_MIGRATION
    ),
    repository_root: Annotated[Path, typer.Option("--repository-root", file_okay=False)] = Path(
        "."
    ),
) -> None:
    """Strictly preflight and import one historical kill with no new ordinal."""
    packet, report = load_and_verify_legacy_migration(
        packet_path,
        repository_root=repository_root,
        verify_private_snapshot=True,
    )
    trial = FoundryDatabase.from_environment().import_legacy_killed(
        packet=packet,
        source_commit=source_commit,
        actor_id=actor_id,
        authorization_reference=authorization_reference,
    )
    typer.echo(
        json.dumps(
            {
                "status": "IMPORTED_NOT_REPLAYED",
                "preflight_content_hash": report["content_hash"],
                "migration_manifest_hash": packet.manifest_hash,
                "public_trial_id": trial["public_trial_id"],
                "state": trial["state"],
                "foundry_identity_ordinal": trial["foundry_identity_ordinal"],
                "replay_status": trial["replay_status"],
            },
            sort_keys=True,
        )
    )


@foundry_app.command("enqueue-legacy-replay")
def enqueue_legacy_replay(
    image_digest: Annotated[str, typer.Option(help="Pinned and signed worker image digest.")],
    source_commit: Annotated[str, typer.Option(help="Exact reviewed 40-character commit.")],
    packet_path: Annotated[Path, typer.Option("--packet", dir_okay=False)] = (
        DEFAULT_LEGACY_MIGRATION
    ),
    repository_root: Annotated[Path, typer.Option("--repository-root", file_okay=False)] = Path(
        "."
    ),
) -> None:
    """Queue the one-shot, no-network replay after strict snapshot verification."""
    packet, _ = load_and_verify_legacy_migration(
        packet_path,
        repository_root=repository_root,
        verify_private_snapshot=True,
    )
    job = FoundryDatabase.from_environment().enqueue_legacy_replay(
        packet=packet,
        image_digest=image_digest,
        source_commit=source_commit,
    )
    typer.echo(
        json.dumps(
            {
                "status": "CLEAN_REPLAY_QUEUED",
                "job_id": str(job["id"]),
                "public_trial_id": packet.public_trial_id,
                "network_policy": job["network_policy"],
                "max_attempts": job["max_attempts"],
            },
            sort_keys=True,
        )
    )


@foundry_app.command("finalize-legacy-replay")
def finalize_legacy_replay(
    trial_id: Annotated[uuid.UUID, typer.Option()],
    job_id: Annotated[uuid.UUID, typer.Option()],
    observed_object_hash: Annotated[
        str, typer.Option(help="SHA-256 independently read from immutable replay output.")
    ],
    validator_id: Annotated[str, typer.Option()],
    authorization_reference: Annotated[str, typer.Option()],
) -> None:
    """Compare a terminal replay job to the immutable historical result hash."""
    trial = FoundryDatabase.from_environment().finalize_legacy_replay(
        trial_id=trial_id,
        job_id=job_id,
        observed_object_hash=observed_object_hash,
        validator_id=validator_id,
        authorization_reference=authorization_reference,
    )
    typer.echo(
        json.dumps(
            {
                "status": "LEGACY_REPLAY_FINALIZED",
                "public_trial_id": trial["public_trial_id"],
                "replay_status": trial["replay_status"],
            },
            sort_keys=True,
        )
    )


@foundry_app.command("enqueue-legacy-sanitizer")
def enqueue_legacy_sanitizer(
    image_digest: Annotated[str, typer.Option(help="Pinned and signed worker image digest.")],
    source_commit: Annotated[str, typer.Option(help="Exact reviewed 40-character commit.")],
    packet_path: Annotated[Path, typer.Option("--packet", dir_okay=False)] = (
        DEFAULT_LEGACY_MIGRATION
    ),
    repository_root: Annotated[Path, typer.Option("--repository-root", file_okay=False)] = Path(
        "."
    ),
) -> None:
    """Queue allowlisted sanitization after the replay gate has passed."""
    packet, _ = load_and_verify_legacy_migration(
        packet_path,
        repository_root=repository_root,
        verify_private_snapshot=True,
    )
    job = FoundryDatabase.from_environment().enqueue_legacy_sanitizer(
        packet=packet,
        image_digest=image_digest,
        source_commit=source_commit,
    )
    typer.echo(
        json.dumps(
            {
                "status": "LEGACY_SANITIZER_QUEUED",
                "job_id": str(job["id"]),
                "public_trial_id": packet.public_trial_id,
                "network_policy": job["network_policy"],
                "max_attempts": job["max_attempts"],
            },
            sort_keys=True,
        )
    )
@foundry_app.command("publish-legacy-packet")
def publish_legacy_packet(
    trial_id: Annotated[uuid.UUID, typer.Option()],
    job_id: Annotated[uuid.UUID, typer.Option()],
    observed_sanitized_hash: Annotated[
        str, typer.Option(help="SHA-256 independently read from sanitized output.")
    ],
    publisher_id: Annotated[str, typer.Option()],
    authorization_reference: Annotated[str, typer.Option()],
) -> None:
    """Bind a successful sanitizer job to the public killed-trial record."""
    trial = FoundryDatabase.from_environment().publish_legacy_packet(
        trial_id=trial_id,
        job_id=job_id,
        observed_sanitized_hash=observed_sanitized_hash,
        publisher_id=publisher_id,
        authorization_reference=authorization_reference,
    )
    typer.echo(
        json.dumps(
            {
                "status": "LEGACY_SANITIZED_PACKET_BOUND",
                "public_trial_id": trial["public_trial_id"],
                "artifact_hash": trial["artifact_hash"],
            },
            sort_keys=True,
        )
    )


@foundry_app.command("verify-acceptance-receipts")
def verify_foundry_acceptance_receipts(
    directory: Annotated[Path, typer.Option(file_okay=False)],
    repository_root: Annotated[Path, typer.Option("--repository-root", file_okay=False)] = Path(
        "."
    ),
) -> None:
    """Verify a receipt directory and refuse an operational claim if any proof is absent."""
    report = verify_acceptance_receipts(
        directory,
        repository_root=repository_root,
    )
    typer.echo(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "ACCEPTED_OPERATIONAL":
        raise typer.Exit(code=1)
