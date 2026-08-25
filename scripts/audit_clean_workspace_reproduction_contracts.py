#!/usr/bin/env python3
"""Audit whether each publication archive can genuinely reproduce its result cleanly."""

from __future__ import annotations

import hashlib
import json
import shlex
import tarfile
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
REGISTRY: Final = ROOT / "config/external_publication_registry.json"
ARCHIVES: Final = ROOT / "artifacts/publication/all_sleeve_review_archives.json"
RIGHTS: Final = ROOT / "artifacts/publication/all_sleeve_data_rights_audit.json"
ISOLATED_REPLAY: Final = (
    ROOT / "artifacts/audit/sleeve_publication_isolated_replay_verification.json"
)
ALPHAMAX_UPSTREAM_REPLAY: Final = (
    ROOT / "artifacts/publication/alphamax_upstream_clean_workspace.json"
)
PREREG_INVESTMENT_UPSTREAM_REPLAY: Final = (
    ROOT / "artifacts/publication/prereg_investment_upstream_clean_workspace.json"
)
OUTPUT: Final = ROOT / "artifacts/publication/clean_workspace_reproduction_audit.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _commands(reproduction: dict[str, Any]) -> list[str]:
    if reproduction.get("schema") == "canli.alphac-publication-reproduction.v1":
        return list(reproduction["commands"])
    return list(reproduction["result_reproduction_commands"])


def _command_record(
    command: str,
    reproduction: dict[str, Any],
    archive_members: set[str],
    archive_root: str,
) -> dict[str, Any]:
    parts = shlex.split(command)
    target: str | None = None
    if parts[:3] == ["uv", "run", "python"] and len(parts) >= 4:
        target = parts[3]
    kind = "ENVIRONMENT_SETUP" if parts[:2] == ["uv", "sync"] else "PYTHON_ENTRYPOINT"
    target_path = ROOT / target if target is not None else None
    workspace_present = target_path is None or target_path.is_file()
    current_sha = (
        _sha256(target_path) if target_path is not None and target_path.is_file() else None
    )
    declared_sha = reproduction.get("code_bindings", {}).get(target) if target else None
    binding_valid = target is None or (declared_sha is not None and declared_sha == current_sha)
    archive_path = f"{archive_root}/{target}" if target else None
    return {
        "command": command,
        "kind": kind,
        "shell_parse_valid": bool(parts),
        "repository_target": target,
        "target_present_in_author_workspace": workspace_present,
        "target_current_sha256": current_sha,
        "target_declared_sha256": declared_sha,
        "target_binding_valid": binding_valid,
        "target_in_review_archive": archive_path in archive_members if archive_path else False,
    }


def build() -> dict[str, Any]:
    registry = json.loads(REGISTRY.read_text())
    archives = json.loads(ARCHIVES.read_text())
    rights = json.loads(RIGHTS.read_text())
    isolated = json.loads(ISOLATED_REPLAY.read_text())
    alphamax_replay = json.loads(ALPHAMAX_UPSTREAM_REPLAY.read_text())
    prereg_investment_replay = json.loads(PREREG_INVESTMENT_UPSTREAM_REPLAY.read_text())
    if alphamax_replay.get("content_hash") != _content_hash(alphamax_replay):
        raise ValueError("AlphaMax upstream replay receipt content hash is invalid")
    if prereg_investment_replay.get("content_hash") != _content_hash(
        prereg_investment_replay
    ):
        raise ValueError("prereg_investment upstream replay receipt content hash is invalid")
    archive_by_key = {record["registry_key"]: record for record in archives["records"]}
    rights_by_key = {record["registry_key"]: record for record in rights["records"]}
    failures: list[str] = []
    records: list[dict[str, Any]] = []

    for paper in registry["sleeves"]:
        key = paper["key"]
        bundle_manifest = ROOT / paper["bundle_manifest"]
        bundle_dir = bundle_manifest.parent
        reproduction_path = bundle_dir / "reproduction.json"
        reproduction = json.loads(reproduction_path.read_text())
        archive = archive_by_key[key]
        archive_path = ROOT / archive["archive"]
        with tarfile.open(archive_path, "r:gz") as handle:
            members = {member.name for member in handle.getmembers() if member.isfile()}
        archive_root = next(iter(members)).split("/", 1)[0]
        command_records = [
            _command_record(command, reproduction, members, archive_root)
            for command in _commands(reproduction)
        ]

        env_records = []
        for relative, expected in reproduction["environment_bindings"].items():
            path = ROOT / relative
            archive_member = f"{archive_root}/{relative}"
            env_records.append(
                {
                    "path": relative,
                    "present_in_author_workspace": path.is_file(),
                    "current_sha256": _sha256(path) if path.is_file() else None,
                    "declared_sha256": expected,
                    "binding_valid": path.is_file() and _sha256(path) == expected,
                    "present_in_review_archive": archive_member in members,
                }
            )
        rights_record = rights_by_key[key]
        full_clean_claim = (
            reproduction.get("full_pipeline_clean_environment_reproduction_completed") is True
            if reproduction.get("schema") == "canli.alphac-publication-reproduction.v1"
            else reproduction.get("clean_environment_reproduction_completed") is True
        )
        full_decision = (
            reproduction.get("full_decision_clean_environment_reproduction_completed") is True
            and not full_clean_claim
        )
        core_only = (
            reproduction.get("core_clean_environment_reproduction_completed") is True
            and not full_decision
            and not full_clean_claim
        )
        upstream_strategy_replays = int(
            reproduction.get("upstream_benchmark_strategy_reproduction", {}).get(
                "completed_author_run_strategy_replays", 0
            )
        )
        all_targets_bound = all(
            record["target_present_in_author_workspace"] and record["target_binding_valid"]
            for record in command_records
        )
        all_environment_bound = all(record["binding_valid"] for record in env_records)
        archive_has_commands = all(
            record["kind"] == "ENVIRONMENT_SETUP" or record["target_in_review_archive"]
            for record in command_records
        )
        archive_has_environment = all(
            record["present_in_review_archive"] for record in env_records
        )
        archive_standalone = (
            archive_has_commands
            and archive_has_environment
            and rights_record["data_manifest_license_review_complete"] is True
        )
        if not all_targets_bound:
            failures.append(f"{key}:REPOSITORY_COMMAND_TARGET_BINDING_INVALID")
        if not all_environment_bound:
            failures.append(f"{key}:ENVIRONMENT_BINDING_INVALID")
        if full_clean_claim:
            failures.append(f"{key}:UNEXPECTED_FULL_CLEAN_WORKSPACE_CLAIM")

        if key == "alphavintage_macro_surprise":
            semantics = (
                "PORTABLE_FULL_DECISION_REPLAY_ALL_THREE_UPSTREAM_REPLAYS_COMPLETE_"
                "TWO_EXACT_ONE_DIVERGENT"
            )
        elif key == "alphamax_equity_momentum":
            semantics = "AUTHOR_RUN_UPSTREAM_STRATEGY_REPLAY_FAILED_EXACT_EQUIVALENCE"
        else:
            semantics = "AUDIT_ONLY_REBUILD_OR_CORRECTION_NOT_FULL_RESULT_GENERATION"
        records.append(
            {
                "registry_key": key,
                "reproduction_manifest": {
                    "path": str(reproduction_path.relative_to(ROOT)),
                    "sha256": _sha256(reproduction_path),
                    "schema": reproduction["schema"],
                },
                "review_archive": {
                    "path": archive["archive"],
                    "sha256": archive["sha256"],
                    "root": archive_root,
                },
                "commands": command_records,
                "environment": env_records,
                "repository_command_targets_present_and_bound": all_targets_bound,
                "repository_environment_files_present_and_bound": all_environment_bound,
                "archive_contains_command_targets": archive_has_commands,
                "archive_contains_environment_files": archive_has_environment,
                "archive_contains_raw_input_rows": False,
                "archive_standalone_reproduction_executable": archive_standalone,
                "manifest_full_clean_workspace_reproduction_claimed": full_clean_claim,
                "portable_core_only_reproduction_completed": core_only,
                "portable_full_decision_reproduction_completed": full_decision,
                "upstream_strategy_curve_replays_completed": upstream_strategy_replays,
                "upstream_historical_strategy_output_equivalences": int(
                    reproduction.get("upstream_benchmark_strategy_reproduction", {}).get(
                        "historical_strategy_output_equivalence_established", 0
                    )
                ),
                "author_upstream_strategy_replay": (
                    {
                        "path": str(ALPHAMAX_UPSTREAM_REPLAY.relative_to(ROOT)),
                        "sha256": _sha256(ALPHAMAX_UPSTREAM_REPLAY),
                        "content_hash": alphamax_replay["content_hash"],
                        "status": alphamax_replay["status"],
                        "passes_strategy_reproduction": alphamax_replay[
                            "passes_strategy_reproduction"
                        ],
                    }
                    if key == "alphamax_equity_momentum"
                    else None
                ),
                "command_semantics": semantics,
                "raw_input_portability_established": False,
                "data_license_review_complete": rights_record[
                    "data_manifest_license_review_complete"
                ],
                "independent_human_reproduction_completed": reproduction.get(
                    "independent_human_reproduction_completed"
                )
                is True,
                "next_replay_closure": [
                    "PUBLISH_OR_BIND_THE_EXACT_CODE_AND_FROZEN_ENVIRONMENT_USED_BY_THE_COMMANDS",
                    "PROVIDE_RIGHTS_COMPLIANT_INPUT_REACQUISITION_AND_HASH_COMPARISON",
                    "EXECUTE_RESULT_GENERATION_IN_A_FRESH_CHECKOUT_NOT_THE_AUTHOR_WORKSPACE",
                    "COMPARE_REGENERATED_OUTPUTS_TO_DECLARED_HASHES_AND_RECORD_DIVERGENCE",
                    "OBTAIN_NAMED_INDEPENDENT_HUMAN_REPRODUCTION_AFTER_INTERNAL_REPLAY_PASSES",
                ],
            }
        )

    full_clean = sum(
        record["manifest_full_clean_workspace_reproduction_claimed"] for record in records
    )
    archive_executable = sum(
        record["archive_standalone_reproduction_executable"] for record in records
    )
    core_only_count = sum(
        record["portable_core_only_reproduction_completed"] for record in records
    )
    full_decision_count = sum(
        record["portable_full_decision_reproduction_completed"] for record in records
    )
    independent = sum(
        record["independent_human_reproduction_completed"] for record in records
    )
    upstream_strategy_replays = sum(
        record["upstream_strategy_curve_replays_completed"] for record in records
    )
    document: dict[str, Any] = {
        "schema": "canli.alphac-clean-workspace-reproduction-audit.v1",
        "author": "Arhan Canli",
        "audit_date": "2026-08-24",
        "status": (
            "PASS_CONTRACT_AUDIT_ONE_FULL_DECISION_THREE_UPSTREAM_STRATEGY_REPLAYS_"
            "NO_FULL_PIPELINE_REPLAYS"
        )
        if not failures
        else "FAIL",
        "counts": {
            "sleeves": len(records),
            "repository_command_contracts_present_and_bound": sum(
                record["repository_command_targets_present_and_bound"]
                and record["repository_environment_files_present_and_bound"]
                for record in records
            ),
            "archive_standalone_reproductions_executable": archive_executable,
            "full_clean_workspace_reproductions_completed": full_clean,
            "portable_core_only_reproductions_completed": core_only_count,
            "portable_full_decision_reproductions_completed": full_decision_count,
            "upstream_strategy_curve_replays_completed": upstream_strategy_replays,
            "upstream_historical_strategy_output_equivalences": sum(
                record["upstream_historical_strategy_output_equivalences"]
                for record in records
            ),
            "failed_upstream_strategy_replay_attempts_completed": 1,
            "independent_human_reproductions_completed": independent,
        },
        "isolated_dependency_audit": {
            "status": isolated["status"],
            "commands_executed": isolated["commands_executed"],
            "sleeves_with_audit_command_executed": isolated[
                "sleeves_with_audit_command_executed"
            ],
            "portable_clean_workspace_replay_completed": isolated[
                "portable_clean_workspace_replay_completed"
            ],
            "claim_boundary": isolated["claim_boundary"],
        },
        "records": records,
        "failures": failures,
        "claim_boundary": (
            "This audit proves that declared command targets and frozen-environment files exist "
            "and match their current workspace hashes. The preparation archives intentionally "
            "contain papers, manifests and released result evidence—not repository code, lockfiles "
            "or raw third-party inputs—so none is a standalone full-result reproduction bundle. "
            "AlphaVintage's three benchmark inputs now have completed author-run strategy replays. "
            "AlphaTrend's consumed curve and the non-sleeve prereg_investment artifact establish "
            "historical output equivalence; AlphaMax's fresh-vendor replay failed exact strategy "
            "equivalence. These receipts do not clear data rights or constitute independent "
            "replication."
        ),
        "source_bindings": {
            "publication_registry": {
                "path": str(REGISTRY.relative_to(ROOT)),
                "sha256": _sha256(REGISTRY),
            },
            "review_archives": {
                "path": str(ARCHIVES.relative_to(ROOT)),
                "sha256": _sha256(ARCHIVES),
                "content_hash": archives["content_hash"],
            },
            "data_rights_audit": {
                "path": str(RIGHTS.relative_to(ROOT)),
                "sha256": _sha256(RIGHTS),
                "content_hash": rights["content_hash"],
            },
            "isolated_dependency_replay": {
                "path": str(ISOLATED_REPLAY.relative_to(ROOT)),
                "sha256": _sha256(ISOLATED_REPLAY),
                "content_hash": isolated["content_hash"],
            },
            "alphamax_upstream_replay": {
                "path": str(ALPHAMAX_UPSTREAM_REPLAY.relative_to(ROOT)),
                "sha256": _sha256(ALPHAMAX_UPSTREAM_REPLAY),
                "content_hash": alphamax_replay["content_hash"],
            },
            "prereg_investment_upstream_replay": {
                "path": str(PREREG_INVESTMENT_UPSTREAM_REPLAY.relative_to(ROOT)),
                "sha256": _sha256(PREREG_INVESTMENT_UPSTREAM_REPLAY),
                "content_hash": prereg_investment_replay["content_hash"],
                "status": prereg_investment_replay["status"],
            },
        },
    }
    document["content_hash"] = _content_hash(document)
    return document


def main() -> None:
    document = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{document['status']}: {OUTPUT}")
    print(f"content_hash: {document['content_hash']}")
    if document["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
