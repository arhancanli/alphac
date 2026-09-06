from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pandas as pd

SCRIPT = Path(__file__).parents[2] / "scripts" / "audit_active_ownership_13d_item4.py"
SPEC = importlib.util.spec_from_file_location("active_ownership_item4_scoring", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_complete_labels_score_single_candidate_else_unresolved(tmp_path: Path) -> None:
    rows = pd.DataFrame(
        {
            "accession": ["a", "b", "c"],
            "specific_active_intent": [True, False, True],
            "ownership_pct_candidates": [[7.5], [], [4.0, 8.0]],
        }
    )
    labels = pd.DataFrame(
        {
            "accession": ["a", "b", "c"],
            "human_specific_active_intent": ["true", "false", "true"],
            "human_representative_sentence": ["one", "two", "three"],
            "human_aggregate_ownership_pct_or_unresolved": ["7.5", "unresolved", "unresolved"],
        }
    )
    path = tmp_path / "labels.csv"
    labels.to_csv(path, index=False)
    score = MODULE.score_labels(rows, path)
    assert score["complete"] is True
    assert score["positive_precision"] == 1.0
    assert score["positive_recall"] == 1.0
    assert score["ownership_exact_rate"] == 1.0
    assert score["ownership_machine_rule"] == "sole_candidate_else_unresolved"


def test_invalid_ownership_label_fails_closed(tmp_path: Path) -> None:
    rows = pd.DataFrame(
        {
            "accession": ["a"],
            "specific_active_intent": [False],
            "ownership_pct_candidates": [[]],
        }
    )
    labels = pd.DataFrame(
        {
            "accession": ["a"],
            "human_specific_active_intent": ["false"],
            "human_representative_sentence": ["sentence"],
            "human_aggregate_ownership_pct_or_unresolved": ["unknown"],
        }
    )
    path = tmp_path / "labels.csv"
    labels.to_csv(path, index=False)
    score = MODULE.score_labels(rows, path)
    assert score["complete"] is False
    assert "plain number" in score["error"]


def test_completed_labels_require_matching_sealed_import_receipt(tmp_path: Path) -> None:
    labels = tmp_path / "labels.csv"
    labels.write_text("human_specific_active_intent\ntrue\n")
    receipt = tmp_path / "receipt.json"
    payload = {
        "canonical_labels_after_sha256": hashlib.sha256(labels.read_bytes()).hexdigest(),
        "rows_imported": 48,
        "prediction_blind_attested": True,
        "return_hypotheses_spent": 0,
        "return_data_opened": False,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["content_hash"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
    receipt.write_text(json.dumps(payload))
    MODULE.validate_import_receipt(labels, receipt)

    labels.write_text("human_specific_active_intent\nfalse\n")
    try:
        MODULE.validate_import_receipt(labels, receipt)
    except ValueError as error:
        assert "do not match" in str(error)
    else:
        raise AssertionError("tampered labels must fail closed")
