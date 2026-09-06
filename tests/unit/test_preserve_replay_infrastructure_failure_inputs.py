from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "preserve_replay_infrastructure_failure_inputs.py"
SPEC = importlib.util.spec_from_file_location("preserve_failure_inputs", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_recorded_failure_inputs_reconstruct_byte_exactly() -> None:
    environment, manifest = MODULE.reconstruct()
    assert MODULE._sha256_bytes(environment) == (
        "sha256:41d7823713fa5fccbe9371fe433404be59d83d139be78b83aab31c2eee3ffb77"
    )
    assert MODULE._sha256_bytes(manifest) == (
        "sha256:78b358c057a0ed09573f9cea425e37cde7121333289d20d546cd064713d25302"
    )


def test_failure_artifact_points_to_recoverable_immutable_inputs() -> None:
    failure = json.loads(MODULE.FAILURE.read_text())
    evidence = failure["evidence"]
    assert evidence["preserved_replay_environment_sha256"] == MODULE._sha256_bytes(
        MODULE.PRESERVED_ENVIRONMENT.read_bytes()
    )
    assert evidence["preserved_failed_lake_manifest_sha256"] == MODULE._sha256_bytes(
        MODULE.PRESERVED_MANIFEST.read_bytes()
    )
