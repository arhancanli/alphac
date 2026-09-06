#!/usr/bin/env python3
"""Seal both observed AlphaVintage full-decision replay attempts without cherry-picking."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
CURRENT_RECEIPT: Final = (
    ROOT / "artifacts/publication/alphavintage_full_decision_clean_workspace.json"
)
TRANSCRIPT: Final = Path(
    "/Users/arhancanli/.codex/sessions/2026/08/22/"
    "rollout-2026-08-22T12-21-36-01a0288f-9e88-7ff3-b55c-e7eee2a26de0.jsonl"
)
OUTPUT: Final = (
    ROOT / "artifacts/publication/alphavintage_full_decision_replay_attempt_ledger.json"
)
FIRST_CONTENT_HASH: Final = (
    "sha256:970b4404798c43cf70e1d69b083ae37e47a3df3bed4e49fad61c5c58dcefa3cb"
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{_sha256_bytes(_canonical(body))}"


def _command_item(record: dict[str, Any]) -> dict[str, Any] | None:
    payload = record.get("payload", {})
    item = payload.get("item", {})
    return item if item.get("type") == "CommandExecution" else None


def _recover_first_attempt() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    execution_record = None
    inspection_record = None
    source_records = []
    for line_number, raw_line in enumerate(TRANSCRIPT.read_bytes().splitlines(keepends=True), 1):
        record = json.loads(raw_line)
        item = _command_item(record)
        if item is None:
            continue
        command = " ".join(item.get("command", []))
        stdout = item.get("stdout", "")
        if FIRST_CONTENT_HASH in stdout and "--execute" in command:
            execution_record = record
            source_records.append(
                {
                    "purpose": "FIRST_EXECUTION_EXIT_AND_RECEIPT_HASH",
                    "jsonl_line_number": line_number,
                    "ordinal": record["ordinal"],
                    "timestamp": record["timestamp"],
                    "record_sha256": _sha256_bytes(raw_line),
                }
            )
        if (
            "jq '{status, passes, exact_decision_checks, metric_comparisons" in command
            and '"absolute_delta": 0.00006245716285778469' in stdout
        ):
            inspection_record = record
            source_records.append(
                {
                    "purpose": "FIRST_EXECUTION_EXACT_SELECTED_RESULT_FIELDS",
                    "jsonl_line_number": line_number,
                    "ordinal": record["ordinal"],
                    "timestamp": record["timestamp"],
                    "record_sha256": _sha256_bytes(raw_line),
                }
            )
    if execution_record is None or inspection_record is None:
        raise RuntimeError("could not recover the first replay attempt from the exact transcript")
    execution_item = _command_item(execution_record)
    inspection_item = _command_item(inspection_record)
    assert execution_item is not None and inspection_item is not None
    selected = json.loads(inspection_item["stdout"])
    attempt = {
        "attempt": 1,
        "executed_at": execution_record["timestamp"],
        "command_exit_code": execution_item["exit_code"],
        "receipt_content_hash_before_overwrite": FIRST_CONTENT_HASH,
        "receipt_status_before_overwrite": selected["status"],
        "numeric_equivalence_acceptance_passes": selected["passes"],
        "all_four_gate_values_stable": selected["exact_decision_checks"][
            "all_four_gate_values"
        ],
        "all_exact_decision_checks": selected["exact_decision_checks"],
        "metric_comparisons": selected["metric_comparisons"],
        "fresh_checks": selected["fresh_checks"],
        "fresh_verdict": selected["fresh_verdict"],
        "fresh_diversification": selected["fresh_diversification"],
        "execution_records": selected["execution_records"],
        "failed_metric": "placebo_nw_t",
        "failed_metric_absolute_delta": 0.00006245716285778469,
        "fixed_tolerance": 0.00005,
        "recovered_evidence_scope": "EXACT_FIELDS_PRINTED_BEFORE_RECEIPT_WAS_OVERWRITTEN",
        "full_first_receipt_archived": False,
    }
    return attempt, source_records


def build() -> dict[str, Any]:
    first, transcript_records = _recover_first_attempt()
    current = json.loads(CURRENT_RECEIPT.read_text())
    if current.get("content_hash") != _content_hash(current):
        raise RuntimeError("current replay receipt content hash is invalid")
    second = {
        "attempt": 2,
        "executed_at": current["executed_at"],
        "receipt": {
            "path": str(CURRENT_RECEIPT.relative_to(ROOT)),
            "sha256": _sha256(CURRENT_RECEIPT),
            "content_hash": current["content_hash"],
            "status": current["status"],
        },
        "numeric_equivalence_acceptance_passes": current["passes"],
        "receipt_integrity_passes": current["receipt_integrity_passes"],
        "all_four_gate_values_stable": current["exact_decision_checks"][
            "all_four_gate_values"
        ],
        "all_exact_decision_checks": current["exact_decision_checks"],
        "metric_comparisons": current["metric_comparisons"],
        "fresh_checks": current["fresh_result"]["checks"],
        "fresh_verdict": current["fresh_result"]["verdict"],
    }
    attempts = [first, second]
    document: dict[str, Any] = {
        "schema": "canli.alphac-alphavintage-full-decision-attempt-ledger.v1",
        "author": "Arhan Canli",
        "status": "PASS_BOTH_ATTEMPTS_DISCLOSED_MIXED_NUMERIC_EQUIVALENCE_GATE_STABLE",
        "source_bindings": {
            "current_receipt": {
                "path": str(CURRENT_RECEIPT.relative_to(ROOT)),
                "sha256": _sha256(CURRENT_RECEIPT),
            },
            "first_attempt_transcript": {
                "path": str(TRANSCRIPT),
                "records": transcript_records,
                "whole_file_sha256_intentionally_omitted": (
                    "The active append-only session transcript continues to grow; exact immutable "
                    "record bytes are bound instead."
                ),
            },
        },
        "attempts": attempts,
        "counts": {
            "attempts_disclosed": len(attempts),
            "numeric_equivalence_acceptance_passes": sum(
                attempt["numeric_equivalence_acceptance_passes"] for attempt in attempts
            ),
            "all_four_gate_values_stable": sum(
                attempt["all_four_gate_values_stable"] for attempt in attempts
            ),
            "verdicts_killed": sum(attempt["fresh_verdict"] == "KILLED" for attempt in attempts),
        },
        "acceptance_tolerance_changed_between_attempts": False,
        "first_failed_attempt_disclosed": True,
        "current_receipt_path_was_overwritten_by_second_attempt": True,
        "claim_boundary": (
            "Two consecutive author-run fresh-source attempts are disclosed. The first missed "
            "the unchanged numeric-equivalence tolerance on placebo Newey-West t while preserving "
            "all four gates and the KILLED verdict; the second passed that tolerance. This tiny "
            "sample does not estimate vendor reliability, erase the failed attempt, establish a "
            "portable public bundle, regenerate upstream benchmark strategies, or constitute "
            "independent replication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def main() -> None:
    document = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{document['status']}: {OUTPUT}")
    print(f"content_hash: {document['content_hash']}")


if __name__ == "__main__":
    main()
