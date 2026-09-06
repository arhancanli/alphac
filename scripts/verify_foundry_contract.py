#!/usr/bin/env python3
"""Verify Foundry design, database, runtime and deployment artifacts without cloud access."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
FILES: Final = (
    Path("config/foundry_trial_state_machine.json"),
    Path("config/foundry_deployment_manifest.json"),
    Path("config/foundry_runtime_contract.json"),
    Path("deploy/foundry/sql/001_core.sql"),
    Path("deploy/foundry/sql/002_privileges.sql"),
    Path("deploy/foundry/host/research.nft"),
    Path("deploy/foundry/host/holdout.nft"),
    Path("deploy/foundry/host/squid-foundry.conf"),
    Path("deploy/foundry/host/squid-holdout.conf"),
    Path("deploy/foundry/requirements.in"),
    Path("deploy/foundry/requirements.lock"),
    Path("deploy/foundry/terraform/.terraform.lock.hcl"),
    Path("deploy/foundry/terraform/tests/isolation.tftest.hcl"),
    Path("deploy/foundry/sql/003_legacy_migration.sql"),
    Path("config/foundry_legacy_migrations/eia_petroleum_inventory_v1.json"),
    Path("config/foundry_acceptance_receipt_contract.json"),
    Path("deploy/foundry/README.md"),
    Path("deploy/foundry/terraform/main.tf"),
    Path("deploy/foundry/terraform/outputs.tf"),
    Path("deploy/foundry/terraform/variables.tf"),
    Path("deploy/foundry/terraform/versions.tf"),
    Path("deploy/foundry/terraform/terraform.tfvars.example"),
    Path("deploy/foundry/terraform/cloud-init/bastion.yaml"),
    Path("deploy/foundry/terraform/cloud-init/holdout.yaml.tftpl"),
    Path("deploy/foundry/terraform/cloud-init/research.yaml.tftpl"),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def verify() -> dict[str, Any]:
    missing = [str(path) for path in FILES if not (ROOT / path).is_file()]
    if missing:
        raise RuntimeError(f"Foundry contract files are missing: {', '.join(missing)}")

    lifecycle = json.loads((ROOT / FILES[0]).read_text(encoding="utf-8"))
    deployment = json.loads((ROOT / FILES[1]).read_text(encoding="utf-8"))
    runtime = json.loads((ROOT / FILES[2]).read_text(encoding="utf-8"))
    core_sql = (ROOT / FILES[3]).read_text(encoding="utf-8")
    privileges = (ROOT / FILES[4]).read_text(encoding="utf-8")
    legacy_sql = (ROOT / "deploy/foundry/sql/003_legacy_migration.sql").read_text(
        encoding="utf-8"
    )
    migration = json.loads(
        (ROOT / "config/foundry_legacy_migrations/eia_petroleum_inventory_v1.json").read_text(
            encoding="utf-8"
        )
    )
    receipt_contract = json.loads(
        (ROOT / "config/foundry_acceptance_receipt_contract.json").read_text(
            encoding="utf-8"
        )
    )
    terraform_main = (ROOT / "deploy/foundry/terraform/main.tf").read_text(encoding="utf-8")
    terraform_versions = (ROOT / "deploy/foundry/terraform/versions.tf").read_text(
        encoding="utf-8"
    )

    failures: list[str] = []
    if lifecycle["status"] != "DESIGN_FROZEN_NOT_DEPLOYED":
        failures.append("lifecycle status overclaims deployment")
    if deployment["status"] != "PLANNED_NOT_APPLIED":
        failures.append("deployment manifest overclaims application")
    if deployment["networks"]["holdout"]["peered_with_research"] is not False:
        failures.append("holdout is peered with research")
    if deployment["networks"]["execution"]["reachable_from_research"] is not False:
        failures.append("research can reach execution")
    if deployment["networks"]["egress"] != {
        "type": "dedicated_managed_nat_per_vpc",
        "shared_between_research_and_holdout": False,
        "default_route_required_before_private_host_creation": True,
        "host_and_cloud_firewalls_remain_authoritative": True,
        "documented_monthly_base_cost_usd_as_of_2026_08_26": 80,
    }:
        failures.append("private-host egress contract drifted")
    if terraform_main.count('resource "digitalocean_vpc_nat_gateway"') != 2:
        failures.append("Terraform does not declare two dedicated NAT gateways")
    if terraform_main.count("default_gateway = true") != 2:
        failures.append("each Foundry VPC does not have a default NAT route")
    for required in (
        "vpc_uuid        = digitalocean_vpc.research.id",
        "vpc_uuid        = digitalocean_vpc.holdout.id",
    ):
        if required not in terraform_main:
            failures.append(f"dedicated NAT attachment missing: {required}")
    if terraform_main.count("ssh_keys          = var.operator_ssh_key_fingerprints") != 3:
        failures.append("reviewed operator keys are not installed on every SSH host")
    if terraform_main.count("depends_on = [digitalocean_vpc_nat_gateway.") != 2:
        failures.append("private host creation is not ordered after NAT readiness")
    for required in ('backend "s3"', "use_lockfile                = true"):
        if required not in terraform_versions:
            failures.append(f"protected remote state control missing: {required}")
    if any(
        component["broker_write_access"] is not False
        for component in runtime["components"].values()
    ):
        failures.append("a runtime component grants broker write access")
    for required in (
        "FOR UPDATE SKIP LOCKED",
        "BEFORE UPDATE OR DELETE ON foundry.audit_event",
        "next_ordinal > binding.next_hard_review",
        "holdout_consumptions BETWEEN 0 AND 1",
    ):
        if required not in core_sql:
            failures.append(f"database control missing: {required}")
    if "GRANT SELECT, INSERT, UPDATE ON foundry.trial" in privileges:
        failures.append("researchd has a direct trial mutation grant")
    if "GRANT SELECT, INSERT, UPDATE ON foundry.job" in privileges:
        failures.append("researchd has a direct job mutation grant")
    for required in (
        "CREATE TABLE foundry.legacy_migration",
        "foundry.import_legacy_killed_trial",
        "foundry.finalize_legacy_replay",
        "foundry.publish_legacy_packet",
        "foundry_identity_ordinal, migrated_legacy",
        "current_trial.replay_status <> 'NOT_RUN'",
    ):
        if required not in legacy_sql:
            failures.append(f"legacy migration control missing: {required}")
    if migration["status"] != "PREPARED_NOT_IMPORTED_OR_REPLAYED":
        failures.append("legacy migration packet overclaims execution")
    if migration["trial"]["state"] != "KILLED":
        failures.append("legacy migration does not preserve the killed state")
    if migration["trial"]["foundry_identity_ordinal"] is not None:
        failures.append("legacy migration allocates a new Foundry identity")
    if migration["replay"]["network_policy"] != "NONE":
        failures.append("legacy migration replay has network access")
    if any(value is not False for value in migration["security"].values()):
        failures.append("legacy migration enables a forbidden capability")
    if receipt_contract["status"] != "FROZEN_NOT_SATISFIED":
        failures.append("acceptance receipt contract overclaims satisfaction")
    if set(receipt_contract["receipts"]) != set(deployment["acceptance_receipts_required"]):
        failures.append("acceptance receipt inventory differs from deployment manifest")
    if runtime["components"]["migration_operator"]["disabled_after_first_migration"] is not True:
        failures.append("migration operator is not disabled after first import")
    if runtime["components"]["validator"]["database_role"] != "foundry_validator":
        failures.append("validator database role is absent")
    if runtime["components"]["sanitizer_publisher"]["database_role"] != "foundry_publisher":
        failures.append("publisher database role is absent")

    receipt = {
        "schema": "canli.foundry-local-contract-verification.v1",
        "status": "PASS" if not failures else "FAIL",
        "claim_boundary": (
            "This receipt verifies committed local contracts. It is not a Terraform plan, cloud "
            "inventory, deployment, network probe, database integration test or restore receipt."
        ),
        "design_status": {
            "deployment": deployment["status"],
            "runtime": runtime["status"],
            "lifecycle": lifecycle["status"],
            "acceptance": "INCOMPLETE_NOT_OPERATIONAL",
        },
        "architecture": {
            "provider": deployment["provider"]["name"],
            "research_services": deployment["compute"]["research_node"][
                "rootless_services"
            ],
            "research_and_holdout_separate": (
                deployment["networks"]["holdout"]["peered_with_research"] is False
            ),
            "execution_managed_by_foundry": deployment["networks"]["execution"][
                "managed_by_this_manifest"
            ],
            "execution_reachable_from_research": deployment["networks"]["execution"][
                "reachable_from_research"
            ],
            "broker_write_access": any(
                component["broker_write_access"]
                for component in runtime["components"].values()
            ),
            "database": {
                "engine": deployment["database"]["engine"],
                "version": deployment["database"]["version"],
                "queue_mechanism": deployment["database"]["queue_mechanism"],
            },
        },
        "lifecycle": {
            "states": len(lifecycle["states"]),
            "transitions": len(lifecycle["transitions"]),
            "holdout_max_consumptions_per_identity": lifecycle["invariants"][
                "holdout_max_consumptions_per_identity"
            ],
            "terminal_states_have_no_outbound_transitions": lifecycle["invariants"][
                "terminal_states_have_no_outbound_transitions"
            ],
            "gate_failure_can_be_overridden": not lifecycle["invariants"][
                "gate_failure_cannot_be_overridden_by_human_approval"
            ],
        },
        "acceptance": {
            "contract_status": receipt_contract["status"],
            "required_receipts": len(deployment["acceptance_receipts_required"]),
            "public_receipts_attached": 0,
            "missing_receipts": sorted(deployment["acceptance_receipts_required"]),
            "accepted_status": receipt_contract["accepted_status"],
            "current_status": receipt_contract["incomplete_status"],
        },
        "first_migration": {
            "status": migration["status"],
            "public_trial_id": migration["trial"]["public_trial_id"],
            "historical_identity_key": migration["trial"]["historical_identity_key"],
            "preserved_state": migration["trial"]["state"],
            "replay_status": migration["replay"]["status"],
            "network_policy": migration["replay"]["network_policy"],
            "max_attempts": migration["replay"]["max_attempts"],
            "new_identity_spend_allowed": migration["security"][
                "new_identity_spend_allowed"
            ],
        },
        "contract_hashes": {
            "deployment_manifest": _canonical_hash(deployment),
            "runtime_contract": _canonical_hash(runtime),
            "lifecycle_contract": _canonical_hash(lifecycle),
            "acceptance_contract": _canonical_hash(receipt_contract),
            "migration_packet": _canonical_hash(migration),
        },
        "checks": {
            "files_present": not missing,
            "honest_statuses": not any("overclaims" in item for item in failures),
            "execution_isolated_by_contract": not any("execution" in item for item in failures),
            "broker_credentials_absent_by_contract": not any(
                "broker write" in item for item in failures
            ),
            "database_controls_declared": not any(
                "database control" in item for item in failures
            ),
            "direct_mutation_grants_absent": not any(
                "direct" in item and "grant" in item for item in failures
            ),
            "legacy_kill_migration_bounded": not any(
                "legacy migration" in item for item in failures
            ),
            "acceptance_receipts_fail_closed": not any(
                "acceptance receipt" in item for item in failures
            ),
            "migration_roles_separated": not any(
                "operator" in item or "database role" in item for item in failures
            ),
            "private_host_egress_and_state_protected": not any(
                "NAT" in item or "egress" in item or "remote state" in item
                for item in failures
            ),
        },
        "failures": failures,
        "files": [
            {"path": str(path), "sha256": _sha256(ROOT / path)} for path in sorted(FILES)
        ],
    }
    receipt["content_hash"] = _canonical_hash(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    receipt = verify()
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
