from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "import_tender_offer_blind_labels.py"
SPEC = importlib.util.spec_from_file_location("import_tender_offer_blind_labels", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

ROOT = SCRIPT.parents[1]
PACKET = ROOT / "artifacts" / "labeling" / "tender_offer_item4_blind"
SOURCE = ROOT / "artifacts" / "feasibility" / "tender_offer_spread"


def _complete(template: Path, destination: Path) -> pd.DataFrame:
    """A structurally valid return: a price and a posture on every row, one row ineligible."""
    labels = pd.read_csv(template, dtype=str, keep_default_na=False)
    labels["human_unique_cash_price"] = "12.50"
    labels["human_recommendation"] = "recommend_accept"
    labels.loc[0, "human_unique_cash_price"] = "ineligible"
    labels.loc[0, "human_recommendation"] = "ineligible"
    labels["human_notes"] = ""
    labels.to_csv(destination, index=False)
    return labels


def _attestation(path: Path, packet_hash: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "reviewer_name": "Reviewer",
                "reviewer_role": "Independent annotator",
                "reviewer_affiliation": "Independent",
                "relationship_to_researcher": "none",
                "compensation_or_incentive": "fixed fee",
                "conflicts_of_interest": "none",
                "completed_at": "2026-09-20T00:00:00Z",
                "packet_manifest_content_hash": packet_hash,
                **dict.fromkeys(MODULE.ATTESTATION_TRUE_FIELDS, True),
            }
        )
    )
    return path


def test_validate_labels_accepts_only_complete_unchanged_rows(tmp_path: Path) -> None:
    template = PACKET / "reviewer_labels.csv"
    completed = tmp_path / "completed.csv"
    _complete(template, completed)
    labels = MODULE.validate_labels(completed, template)
    assert len(labels) == 30

    changed = pd.read_csv(completed, dtype=str, keep_default_na=False)
    changed.loc[0, "accession"] = "changed"
    changed.to_csv(completed, index=False)
    with pytest.raises(ValueError, match="row identity"):
        MODULE.validate_labels(completed, template)


def test_validate_labels_enforces_the_frozen_label_vocabulary(tmp_path: Path) -> None:
    template = PACKET / "reviewer_labels.csv"
    completed = tmp_path / "completed.csv"

    _complete(template, completed)
    labels = pd.read_csv(completed, dtype=str, keep_default_na=False)
    labels.loc[1, "human_recommendation"] = "accept"
    labels.to_csv(completed, index=False)
    with pytest.raises(ValueError, match="recommendation must be one of"):
        MODULE.validate_labels(completed, template)

    _complete(template, completed)
    labels = pd.read_csv(completed, dtype=str, keep_default_na=False)
    labels.loc[1, "human_unique_cash_price"] = ""
    labels.to_csv(completed, index=False)
    with pytest.raises(ValueError, match="requires a cash price"):
        MODULE.validate_labels(completed, template)

    _complete(template, completed)
    labels = pd.read_csv(completed, dtype=str, keep_default_na=False)
    labels.loc[1, "human_unique_cash_price"] = "0"
    labels.to_csv(completed, index=False)
    with pytest.raises(ValueError, match="greater than zero"):
        MODULE.validate_labels(completed, template)


def test_ineligible_must_be_recorded_in_both_cells_or_neither(tmp_path: Path) -> None:
    template = PACKET / "reviewer_labels.csv"
    completed = tmp_path / "completed.csv"
    _complete(template, completed)
    labels = pd.read_csv(completed, dtype=str, keep_default_na=False)
    labels.loc[0, "human_unique_cash_price"] = "12.50"
    labels.to_csv(completed, index=False)
    with pytest.raises(ValueError, match="in both the price and recommendation cells"):
        MODULE.validate_labels(completed, template)


def test_attestation_requires_every_independence_flag(tmp_path: Path) -> None:
    manifest = json.loads((PACKET / "manifest.json").read_text())
    path = _attestation(tmp_path / "attestation.json", str(manifest["content_hash"]))
    MODULE.validate_attestation(path, str(manifest["content_hash"]))

    attestation = json.loads(path.read_text())
    attestation["no_automated_or_ai_labeling_assistance"] = False
    path.write_text(json.dumps(attestation))
    with pytest.raises(ValueError, match="no_automated_or_ai_labeling_assistance=true"):
        MODULE.validate_attestation(path, str(manifest["content_hash"]))

    attestation["no_automated_or_ai_labeling_assistance"] = True
    attestation["packet_manifest_content_hash"] = "sha256:other"
    path.write_text(json.dumps(attestation))
    with pytest.raises(ValueError, match="not bound to this packet"):
        MODULE.validate_attestation(path, str(manifest["content_hash"]))


def test_import_fills_the_frozen_file_in_place_and_refuses_a_second_import(
    tmp_path: Path,
) -> None:
    source = tmp_path / "tender_offer_spread"
    packet = tmp_path / "packet"
    shutil.copytree(SOURCE, source)
    shutil.copytree(PACKET, packet)
    (source / "human_label_import_receipt.json").unlink(missing_ok=True)
    manifest = json.loads((packet / "manifest.json").read_text())
    completed = tmp_path / "completed.csv"
    _complete(packet / "reviewer_labels.csv", completed)
    attestation = _attestation(tmp_path / "attestation.json", str(manifest["content_hash"]))

    before = pd.read_csv(source / "frozen_human_labels.csv", dtype=str, keep_default_na=False)
    receipt = MODULE.import_labels(completed, attestation, source, packet)
    after = pd.read_csv(source / "frozen_human_labels.csv", dtype=str, keep_default_na=False)

    assert list(after.columns) == list(before.columns)
    assert after["accession"].tolist() == before["accession"].tolist()
    assert after["human_recommendation"].ne("").all()
    assert after["human_unique_cash_price"].ne("").all()
    assert receipt["rows_imported"] == 30
    assert receipt["ineligible_rows"] == 1
    assert receipt["return_hypotheses_spent"] == 0
    assert receipt["content_hash"] == MODULE.content_hash(receipt)
    assert json.loads((source / "human_label_import_receipt.json").read_text()) == receipt

    with pytest.raises(ValueError, match="already have an import receipt"):
        MODULE.import_labels(completed, attestation, source, packet)


def test_import_refuses_a_packet_that_is_not_bound_to_the_current_sources(
    tmp_path: Path,
) -> None:
    source = tmp_path / "tender_offer_spread"
    packet = tmp_path / "packet"
    shutil.copytree(SOURCE, source)
    shutil.copytree(PACKET, packet)
    (source / "human_label_import_receipt.json").unlink(missing_ok=True)
    (source / "result.json").write_text("{}\n")
    manifest = json.loads((packet / "manifest.json").read_text())
    completed = tmp_path / "completed.csv"
    _complete(packet / "reviewer_labels.csv", completed)
    attestation = _attestation(tmp_path / "attestation.json", str(manifest["content_hash"]))
    with pytest.raises(ValueError, match="not bound to the current result_sha256"):
        MODULE.import_labels(completed, attestation, source, packet)
