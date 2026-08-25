#!/usr/bin/env python3
"""Seal the prospective walk-forward derived-input snapshot control."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
SNAPSHOT_MODULE: Final = ROOT / "src/alphaforge/validation/input_snapshot.py"
WALKFORWARD_MODULE: Final = ROOT / "src/alphaforge/analytics/walkforward.py"
READER_MODULE: Final = ROOT / "src/alphaforge/data/store/reader.py"
UNIT_TEST: Final = ROOT / "tests/unit/test_walkforward_input_snapshot.py"
INTEGRATION_TEST: Final = ROOT / "tests/unit/test_walkforward.py"
OUTPUT: Final = ROOT / "artifacts/audit/walkforward_input_snapshot_protocol.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _run_method() -> ast.FunctionDef:
    tree = ast.parse(WALKFORWARD_MODULE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "WalkForwardRunner":
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == "run":
                    return child
    raise RuntimeError("WalkForwardRunner.run not found")


def _call_lines(function: ast.FunctionDef, name: str) -> list[int]:
    lines = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        called = (
            target.id
            if isinstance(target, ast.Name)
            else target.attr
            if isinstance(target, ast.Attribute)
            else None
        )
        if called == name:
            lines.append(node.lineno)
    return sorted(lines)


def build() -> dict[str, Any]:
    run_method = _run_method()
    snapshot_calls = _call_lines(run_method, "seal_walkforward_input_snapshot")
    execution_calls = _call_lines(run_method, "_run_leg_set")
    if len(snapshot_calls) != 1 or not execution_calls or snapshot_calls[0] >= execution_calls[0]:
        raise RuntimeError("input snapshot is not enforced before the first execution leg")
    walkforward_text = WALKFORWARD_MODULE.read_text(encoding="utf-8")
    snapshot_text = SNAPSHOT_MODULE.read_text(encoding="utf-8")
    required_fragments = {
        "automatic_for_persisted_run": "if out_dir is not None:",
        "result_manifest_binding": 'config["input_snapshot"] = input_snapshot_binding',
        "atomic_directory_promotion": "os.replace(temporary, destination)",
        "refuse_overwrite": "refusing to overwrite input snapshot",
        "signal_frame": "derived_signal_frame.parquet",
        "universe_intervals": "universe_intervals.parquet",
        "instrument_metadata": "instrument_metadata.json",
        "resolved_config": "declared_run.json",
        "raw_partitions": "raw_partitions",
        "source_environment": "source_environment",
        "private_rights_default": '"public_release_allowed": False',
    }
    failures = []
    for key, fragment in required_fragments.items():
        source = (
            walkforward_text
            if key
            in {
                "automatic_for_persisted_run",
                "result_manifest_binding",
            }
            else snapshot_text
        )
        if fragment not in source:
            failures.append(key)
    if failures:
        raise RuntimeError(f"snapshot protocol controls missing: {failures}")
    bindings = {
        str(path.relative_to(ROOT)): {
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in (
            SNAPSHOT_MODULE,
            WALKFORWARD_MODULE,
            READER_MODULE,
            UNIT_TEST,
            INTEGRATION_TEST,
        )
    }
    document: dict[str, Any] = {
        "schema": "canli.alphac-walkforward-input-snapshot-protocol-receipt.v1",
        "author": "Arhan Canli",
        "status": "PASS_PROSPECTIVE_PRIVATE_INPUT_SNAPSHOT_ENFORCED",
        "bindings": bindings,
        "enforcement": {
            "automatic_for_every_persisted_walkforward": True,
            "snapshot_call_line": snapshot_calls[0],
            "first_execution_call_line": execution_calls[0],
            "sealed_before_first_execution_leg": snapshot_calls[0] < execution_calls[0],
            "atomic_sibling_directory_promotion": True,
            "existing_snapshot_overwrite_refused": True,
            "manifest_bound_into_walkforward_config": True,
            "payloads": [
                "exact derived signal frame",
                "overlapping point-in-time universe intervals",
                "complete SCD2 history for every declared instrument",
                "hard-linked or copied execution OHLCV/funding/corporate-action partitions",
                "resolved settings and declared run parameters",
                "dirty local Python source tree, YAML profiles, pyproject and uv.lock",
            ],
            "validator_rehashes_every_payload": True,
            "private_data_rights_default": True,
        },
        "retroactivity": {
            "repairs_historical_missing_snapshot": False,
            "authorizes_historical_exact_replay_claim": False,
            "reason": (
                "A prospective control cannot reconstruct bytes that a historical run never sealed."
            ),
        },
        "trial_accounting": {
            "new_return_hypotheses": 0,
            "new_trials": 0,
            "classification": "REPRODUCIBILITY_INFRASTRUCTURE_ONLY",
        },
        "claim_boundary": (
            "This receipt proves the control exists in the bound source and is structurally "
            "invoked before persisted walk-forward execution. Focused tests separately exercise "
            "atomicity, lake-replacement immunity, tamper failure and result binding. It is not "
            "a performance result or a retroactive historical snapshot."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def run(output: Path = OUTPUT) -> dict[str, Any]:
    document = build()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.output.resolve()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
