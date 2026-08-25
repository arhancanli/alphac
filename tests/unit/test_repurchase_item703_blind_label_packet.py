from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "build_repurchase_item703_blind_label_packet.py"
SPEC = importlib.util.spec_from_file_location("repurchase_item703_blind_packet", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_blind_packet_contains_all_frozen_documents_without_machine_outputs() -> None:
    manifest = json.loads((MODULE.OUT / "manifest.json").read_text())
    labels = pd.read_csv(MODULE.OUT / "reviewer_labels.csv", keep_default_na=False)
    documents = sorted((MODULE.OUT / "documents").glob("*.html"))
    assert manifest["rows"] == len(labels) == len(documents) == 60
    assert manifest["prediction_blind"] is True
    assert manifest["parser_outputs_present"] is False
    assert manifest["return_hypotheses_spent"] == 0
    assert labels["has_item703_table"].eq("").all()
    assert labels["expected_month_rows"].eq("").all()
    assert labels["expected_total_row"].eq("").all()
    attestation = json.loads((MODULE.OUT / "reviewer_attestation.json").read_text())
    assert not any(value is True for value in attestation.values())
    assert set(manifest["packet_files"]["documents"]) == {path.name for path in documents}


def test_packet_manifest_content_hash_is_valid() -> None:
    manifest = json.loads((MODULE.OUT / "manifest.json").read_text())
    assert manifest["content_hash"] == MODULE._content_hash(manifest)
    protocol = (
        MODULE.REPO / "docs/design/FEASIBILITY_REPURCHASE_ISSUANCE_FLOW.md"
    ).read_text()
    assert manifest["content_hash"] in protocol
