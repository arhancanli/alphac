"""Operator commands for Foundry contract binding and sanitized status export."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Annotated

import typer

from alphaforge.foundry.contract import FoundryContract
from alphaforge.foundry.database import FoundryDatabase
from alphaforge.foundry.policy import load_foundry_policy
from alphaforge.foundry.sanitizer import sanitize_public_status

foundry_app = typer.Typer(
    help="Operate the bounded Foundry research control plane.",
    no_args_is_help=True,
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
