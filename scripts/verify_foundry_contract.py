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
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> dict[str, Any]:
    missing = [str(path) for path in FILES if not (ROOT / path).is_file()]
    if missing:
        raise RuntimeError(f"Foundry contract files are missing: {', '.join(missing)}")

    lifecycle = json.loads((ROOT / FILES[0]).read_text(encoding="utf-8"))
    deployment = json.loads((ROOT / FILES[1]).read_text(encoding="utf-8"))
    runtime = json.loads((ROOT / FILES[2]).read_text(encoding="utf-8"))
    core_sql = (ROOT / FILES[3]).read_text(encoding="utf-8")
    privileges = (ROOT / FILES[4]).read_text(encoding="utf-8")

    failures: list[str] = []
    if lifecycle["status"] != "DESIGN_FROZEN_NOT_DEPLOYED":
        failures.append("lifecycle status overclaims deployment")
    if deployment["status"] != "PLANNED_NOT_APPLIED":
        failures.append("deployment manifest overclaims application")
    if deployment["networks"]["holdout"]["peered_with_research"] is not False:
        failures.append("holdout is peered with research")
    if deployment["networks"]["execution"]["reachable_from_research"] is not False:
        failures.append("research can reach execution")
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

    receipt = {
        "schema": "canli.foundry-local-contract-verification.v1",
        "status": "PASS" if not failures else "FAIL",
        "claim_boundary": (
            "This receipt verifies committed local contracts. It is not a Terraform plan, cloud "
            "inventory, deployment, network probe, database integration test or restore receipt."
        ),
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
        },
        "failures": failures,
        "files": [
            {"path": str(path), "sha256": _sha256(ROOT / path)} for path in sorted(FILES)
        ],
    }
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
