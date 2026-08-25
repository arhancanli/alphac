from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "import_active_ownership_blind_labels.py"
SPEC = importlib.util.spec_from_file_location("import_active_ownership_blind_labels", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _complete(template: Path, destination: Path) -> None:
    labels = pd.read_csv(template, dtype=str, keep_default_na=False)
    labels["human_specific_active_intent"] = "false"
    labels["human_representative_sentence"] = "Representative source sentence."
    labels["human_aggregate_ownership_pct_or_unresolved"] = "unresolved"
    labels.to_csv(destination, index=False)


def test_validate_labels_accepts_only_complete_unchanged_rows(tmp_path: Path) -> None:
    root = SCRIPT.parents[1]
    template = (
        root
        / "artifacts"
        / "labeling"
        / "active_ownership_13d_item4_v3_blind"
        / "reviewer_labels.csv"
    )
    completed = tmp_path / "completed.csv"
    _complete(template, completed)
    labels = MODULE.validate_labels(completed, template)
    assert len(labels) == 48

    changed = pd.read_csv(completed, dtype=str, keep_default_na=False)
    changed.loc[0, "accession"] = "changed"
    changed.to_csv(completed, index=False)
    with pytest.raises(ValueError, match="row identity"):
        MODULE.validate_labels(completed, template)


def test_attestation_requires_all_independence_flags(tmp_path: Path) -> None:
    path = tmp_path / "attestation.json"
    path.write_text(
        json.dumps(
            {
                "reviewer_name": "Reviewer",
                "reviewer_role": "Independent annotator",
                "completed_at": "2026-08-22T00:00:00Z",
                "packet_manifest_content_hash": "sha256:packet",
                "independent_of_parser_development": True,
                "machine_outputs_not_consulted": False,
                "prices_and_returns_not_consulted": True,
                "all_labels_are_personally_reviewed": True,
            }
        )
    )
    with pytest.raises(ValueError, match="machine_outputs_not_consulted=true"):
        MODULE.validate_attestation(path, "sha256:packet")


def test_packet_validation_rejects_a_tampered_template(tmp_path: Path) -> None:
    root = SCRIPT.parents[1]
    source = root / "artifacts" / "labeling" / "active_ownership_13d_item4_v3_blind"
    packet = tmp_path / "packet"
    packet.mkdir()
    controls = (
        "manifest.json",
        "reviewer_labels.csv",
        "reviewer_attestation.json",
        "INSTRUCTIONS.md",
        "review.html",
        "verify_review.py",
    )
    for name in controls:
        (packet / name).write_bytes((source / name).read_bytes())
    (packet / "documents").mkdir()
    for document in (source / "documents").glob("*.txt"):
        (packet / "documents" / document.name).write_bytes(document.read_bytes())
    MODULE.validate_packet(packet)
    (packet / "reviewer_labels.csv").write_text("tampered\n")
    with pytest.raises(ValueError, match="reviewer_labels_sha256 mismatch"):
        MODULE.validate_packet(packet)


def test_packet_validation_rejects_a_tampered_source_document(tmp_path: Path) -> None:
    root = SCRIPT.parents[1]
    source = root / "artifacts" / "labeling" / "active_ownership_13d_item4_v3_blind"
    packet = tmp_path / "packet"
    packet.mkdir()
    controls = (
        "manifest.json",
        "reviewer_labels.csv",
        "reviewer_attestation.json",
        "INSTRUCTIONS.md",
        "review.html",
        "verify_review.py",
    )
    for name in controls:
        (packet / name).write_bytes((source / name).read_bytes())
    (packet / "documents").mkdir()
    for document in (source / "documents").glob("*.txt"):
        (packet / "documents" / document.name).write_bytes(document.read_bytes())
    (packet / "documents" / "AO13D-017.txt").write_text("tampered\n")
    with pytest.raises(ValueError, match=r"document hash mismatch: AO13D-017\.txt"):
        MODULE.validate_packet(packet)


def test_valid_import_is_hash_bound_and_cannot_be_overwritten(tmp_path: Path) -> None:
    root = SCRIPT.parents[1]
    packet = root / "artifacts" / "labeling" / "active_ownership_13d_item4_v3_blind"
    source = root / "artifacts" / "feasibility" / "active_ownership_13d_item4_v3"
    isolated_source = tmp_path / "source"
    isolated_source.mkdir()
    for name in ("frozen_human_labels.csv", "document_audit.parquet", "result.json"):
        shutil.copy2(source / name, isolated_source / name)

    completed = tmp_path / "completed_labels.csv"
    _complete(packet / "reviewer_labels.csv", completed)
    manifest = json.loads((packet / "manifest.json").read_text())
    attestation = tmp_path / "reviewer_attestation.json"
    attestation.write_text(
        json.dumps(
            {
                "reviewer_name": "Independent Reviewer",
                "reviewer_role": "External source annotator",
                "completed_at": "2026-08-23T12:00:00+04:00",
                "packet_manifest_content_hash": manifest["content_hash"],
                "independent_of_parser_development": True,
                "machine_outputs_not_consulted": True,
                "prices_and_returns_not_consulted": True,
                "all_labels_are_personally_reviewed": True,
            }
        )
    )
    receipt = MODULE.import_labels(completed, attestation, isolated_source, packet)
    assert receipt["rows_imported"] == 48
    assert receipt["packet_content_hash"] == manifest["content_hash"]
    assert (isolated_source / "human_label_import_receipt.json").is_file()

    with pytest.raises(ValueError, match="already have an import receipt"):
        MODULE.import_labels(completed, attestation, isolated_source, packet)
