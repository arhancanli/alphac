#!/usr/bin/env python3
"""Replay audit-only sleeve evidence builders and prove no result or trial ledger changed.

The default mode uses the current project environment. ``--isolated`` uses a fresh uv dependency
environment locked by ``uv.lock`` while deliberately retaining the current repository workspace.
Neither mode is a portable clean-workspace reproduction or independent replication. Return-level
AlphaMax probes are deferred until a licensed, portable input environment exists. The commands
read persisted ledgers/results and regenerate family audit objects; they must not register
hypotheses or alter any released result byte.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
CATALOG: Final = ROOT / "config/sleeve_publication_evidence.json"
OUTPUT: Final = ROOT / "artifacts/audit/sleeve_publication_replay_verification.json"
ISOLATED_OUTPUT: Final = (
    ROOT / "artifacts/audit/sleeve_publication_isolated_replay_verification.json"
)
DEFERRED_SLEEVES: Final = {"alphamax_equity_momentum"}
ALLOWED_AUDIT_COMMANDS: Final = {
    "uv run python scripts/audit_remaining_research_families.py",
    "uv run python scripts/audit_alphatrend_family.py",
    "uv run python scripts/audit_crypto_momentum_family.py",
    "uv run python scripts/audit_crypto_multifactor_family.py",
    "uv run python scripts/audit_crypto_vrp_family.py",
    "uv run python scripts/audit_equity_narrative_family.py",
    "uv run python scripts/audit_equity_fundamental_families.py",
    "uv run python scripts/audit_crypto_carry_2022_tail.py",
    "uv run python scripts/replay_crypto_carry_frozen_inputs.py --seal-existing",
    "uv run python scripts/audit_crypto_carry_first_rebalance_drift.py",
    "uv run python scripts/audit_crypto_carry_full_path_drift.py",
    "uv run python scripts/seal_walkforward_input_snapshot_protocol.py",
    "uv run python scripts/seal_crypto_carry_replay_correction.py",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _ledger_paths() -> list[Path]:
    candidates = set(ROOT.glob("var*/experiments.jsonl"))
    candidates.update(ROOT.glob("artifacts/**/experiments.jsonl"))
    return sorted(path for path in candidates if path.is_file())


def _hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path.relative_to(ROOT)): _sha256(path) for path in paths}


def _result_paths(catalog: dict[str, Any]) -> list[Path]:
    paths = {
        ROOT / result["source"]
        for sleeve in catalog["sleeves"].values()
        for result in sleeve["result_objects"]
    }
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"catalogued result objects missing: {missing}")
    return sorted(paths)


def _execution_command(command: str, *, isolated: bool) -> list[str]:
    parts = shlex.split(command)
    if isolated:
        if parts[:2] != ["uv", "run"]:
            raise ValueError(f"isolated replay requires a uv run command: {command}")
        return ["uv", "run", "--isolated", "--frozen", *parts[2:]]
    return parts


def run(*, isolated: bool = False) -> dict[str, Any]:
    catalog = json.loads(CATALOG.read_text())
    sleeves = catalog["sleeves"]
    commands = {
        command
        for key, sleeve in sleeves.items()
        if key not in DEFERRED_SLEEVES
        for command in sleeve["reproduction_commands"]
    }
    if commands != ALLOWED_AUDIT_COMMANDS:
        raise ValueError(
            "catalog audit-command set changed; review the replay allowlist explicitly"
        )

    result_paths = _result_paths(catalog)
    ledger_paths = _ledger_paths()
    results_before = _hashes(result_paths)
    ledgers_before = _hashes(ledger_paths)
    command_receipts: list[dict[str, Any]] = []
    for command in sorted(commands):
        execution_command = _execution_command(command, isolated=isolated)
        completed = subprocess.run(
            execution_command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        command_receipts.append(
            {
                "command": command,
                "execution_command": shlex.join(execution_command),
                "returncode": completed.returncode,
                "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
                "stderr_sha256": hashlib.sha256(completed.stderr.encode()).hexdigest(),
            }
        )
        if completed.returncode != 0:
            raise RuntimeError(f"audit replay failed: {command}\n{completed.stderr}")

    results_after = _hashes(result_paths)
    ledgers_after = _hashes(ledger_paths)
    result_changes = sorted(
        path for path in results_before if results_before[path] != results_after[path]
    )
    ledger_changes = sorted(
        path for path in ledgers_before if ledgers_before[path] != ledgers_after[path]
    )
    if result_changes or ledger_changes:
        raise RuntimeError(
            f"replay changed governed bytes; results={result_changes}, ledgers={ledger_changes}"
        )

    executed_status = (
        "ISOLATED_FROZEN_DEPENDENCY_AUDIT_EXECUTED_ALL_RELEASED_RESULT_HASHES_STABLE"
        if isolated
        else "AUDIT_COMMAND_EXECUTED_ALL_RELEASED_RESULT_HASHES_STABLE"
    )
    sleeve_status = {
        key: (
            "MAPPED_NOT_EXECUTED_RETURN_LEVEL_REPLAY_DEFERRED"
            if key in DEFERRED_SLEEVES
            else executed_status
        )
        for key in sleeves
    }
    document: dict[str, Any] = {
        "schema": "canli.alphac-sleeve-publication-replay-verification.v2",
        "author": "Arhan Canli",
        "status": (
            "PASS_ISOLATED_FROZEN_DEPENDENCY_REPLAY_NOT_PORTABLE_WORKSPACE"
            if isolated
            else "PASS_INTERNAL_AUDIT_REPLAY_NOT_CLEAN_ENVIRONMENT"
        ),
        "passes": True,
        "dependency_environment": (
            "UV_ISOLATED_FROZEN" if isolated else "CURRENT_PROJECT_ENVIRONMENT"
        ),
        "isolated_dependency_environment_completed": isolated,
        "portable_clean_workspace_replay_completed": False,
        "raw_input_portability_established": False,
        "independent_replication": False,
        "commands_executed": len(command_receipts),
        "sleeves_with_audit_command_executed": len(sleeves) - len(DEFERRED_SLEEVES),
        "sleeves_deferred": sorted(DEFERRED_SLEEVES),
        "unique_released_result_objects_verified": len(result_paths),
        "experiment_ledgers_verified_unchanged": len(ledger_paths),
        "result_hash_changes": result_changes,
        "experiment_ledger_hash_changes": ledger_changes,
        "command_receipts": command_receipts,
        "sleeve_status": sleeve_status,
        "source_bindings": {
            "evidence_catalog": {
                "path": str(CATALOG.relative_to(ROOT)),
                "sha256": _sha256(CATALOG),
            },
            "result_objects": results_after,
            "experiment_ledgers": ledgers_after,
            "verification_script": {
                "path": str(Path(__file__).resolve().relative_to(ROOT)),
                "sha256": _sha256(Path(__file__).resolve()),
            },
        },
        "claim_boundary": (
            f"This proves that {len(command_receipts)} audit-only commands completed in a fresh "
            "uv isolated, frozen dependency environment while using the current repository "
            f"workspace, all {len(result_paths)} unique released result objects remained "
            "byte-identical, and no experiment ledger changed. "
            "It is not a portable clean-workspace replay, does not prove raw data portability, "
            "does not execute the deferred AlphaMax return-level probes, opens no new hypothesis, "
            "and is not independent replication."
            if isolated
            else f"This proves that {len(command_receipts)} audit-only commands completed in the "
            f"current repository environment, all {len(result_paths)} unique released result "
            "objects remained byte-identical, and no experiment ledger changed. It is not a "
            "clean-environment replay, does not prove raw "
            "data portability, does not execute the deferred AlphaMax return-level probes, opens "
            "no new hypothesis, and is not independent replication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--isolated",
        action="store_true",
        help="run through uv --isolated --frozen in the current repository workspace",
    )
    args = parser.parse_args()
    document = run(isolated=args.isolated)
    output = ISOLATED_OUTPUT if args.isolated else OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{document['status']}: {output}")
    print(f"content_hash: {document['content_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
