from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "reviewer_verify_active_ownership.py"
PACKET = REPO / "artifacts" / "labeling" / "active_ownership_13d_item4_v3_blind"


def _module():
    spec = importlib.util.spec_from_file_location("active_ownership_external_verifier", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _completed_review(tmp_path: Path) -> tuple[Path, Path, Path]:
    packet = tmp_path / "packet"
    shutil.copytree(PACKET, packet)
    labels = pd.read_csv(packet / "reviewer_labels.csv", dtype=str, keep_default_na=False)
    labels["human_specific_active_intent"] = "false"
    labels["human_representative_sentence"] = "No specific current action is stated."
    labels["human_aggregate_ownership_pct_or_unresolved"] = "unresolved"
    completed = packet / "completed_labels.csv"
    labels.to_csv(completed, index=False)

    manifest = json.loads((packet / "manifest.json").read_text())
    attestation = json.loads((packet / "reviewer_attestation.json").read_text())
    attestation.update(
        {
            "reviewer_name": "Independent Reviewer",
            "reviewer_role": "Source document reviewer",
            "completed_at": "2026-08-23T12:00:00+00:00",
            "packet_manifest_content_hash": manifest["content_hash"],
            "independent_of_parser_development": True,
            "machine_outputs_not_consulted": True,
            "prices_and_returns_not_consulted": True,
            "all_labels_are_personally_reviewed": True,
        }
    )
    completed_attestation = packet / "completed_attestation.json"
    completed_attestation.write_text(json.dumps(attestation, indent=2) + "\n")
    return packet, completed, completed_attestation


def test_dependency_free_verifier_accepts_a_structurally_complete_return(tmp_path: Path) -> None:
    packet, completed, attestation = _completed_review(tmp_path)
    result = _module().verify(packet, completed, attestation)
    assert result["status"] == "REVIEW_RETURN_VALID"
    assert result["documents_verified"] == result["rows_verified"] == 48

    process = subprocess.run(
        [
            sys.executable,
            str(packet / "verify_review.py"),
            "--completed",
            str(completed),
            "--attestation",
            str(attestation),
        ],
        cwd=packet,
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["status"] == "REVIEW_RETURN_VALID"


def test_verifier_rejects_source_or_identity_tampering(tmp_path: Path) -> None:
    packet, completed, attestation = _completed_review(tmp_path)
    (packet / "documents" / "AO13D-001.txt").write_text("tampered\n")
    with pytest.raises(ValueError, match="document hash mismatch"):
        _module().verify(packet, completed, attestation)


def test_verifier_rejects_reordered_or_changed_frozen_rows(tmp_path: Path) -> None:
    packet, completed, attestation = _completed_review(tmp_path)
    labels = pd.read_csv(completed, dtype=str, keep_default_na=False)
    labels.loc[0, "accession"] = "changed"
    labels.to_csv(completed, index=False)
    with pytest.raises(ValueError, match="changed frozen identity"):
        _module().verify(packet, completed, attestation)
