from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "build_active_ownership_blind_label_packet.py"
SPEC = importlib.util.spec_from_file_location("active_ownership_blind_packet", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_persisted_packet_is_complete_prediction_blind_and_hash_bound() -> None:
    root = SCRIPT.parents[1]
    out = root / "artifacts" / "labeling" / "active_ownership_13d_item4_v3_blind"
    manifest = json.loads((out / "manifest.json").read_text())
    labels = pd.read_csv(out / "reviewer_labels.csv", keep_default_na=False)
    assert manifest["rows"] == len(labels) == 48
    assert manifest["prediction_blind"] is True
    assert set(MODULE.FORBIDDEN_MACHINE_FIELDS).isdisjoint(labels.columns)
    assert labels["packet_id"].is_unique
    assert len(list((out / "documents").glob("*.txt"))) == 48
    attestation = json.loads((out / "reviewer_attestation.json").read_text())
    assert not any(value is True for value in attestation.values())
    assert manifest["packet_files"]["reviewer_attestation_template_sha256"] == (
        MODULE.sha256_file(out / "reviewer_attestation.json")
    )
    assert manifest["schema"] == "canli.labeling.active-ownership-13d-item4-blind-packet.v3"
    assert manifest["packet_files"]["review_verifier_sha256"] == MODULE.sha256_file(
        out / "verify_review.py"
    )
    assert manifest["packet_files"]["review_workspace_sha256"] == MODULE.sha256_file(
        out / "review.html"
    )
    workspace = (out / "review.html").read_text()
    assert "Active Ownership Evidence Desk" in workspace
    assert "__PACKET_DATA__" not in workspace
    assert "ownership_pct_candidates" not in workspace
    assert "active_sentences" not in workspace
    assert manifest["content_hash"] == MODULE.content_hash(manifest)


def test_rebuild_refuses_labels_that_are_no_longer_blind(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    pd.DataFrame(
        {
            "accession": [str(index) for index in range(48)],
            "human_specific_active_intent": ["true"] + [""] * 47,
        }
    ).to_csv(source / "frozen_human_labels.csv", index=False)
    with pytest.raises(ValueError, match="after human labels were opened"):
        MODULE.build(source, tmp_path / "out")
