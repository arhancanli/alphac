from __future__ import annotations

import json
from pathlib import Path
from runpy import run_path
from types import SimpleNamespace

import pandas as pd
import pytest

MODULE = run_path(
    str(Path(__file__).parents[2] / "scripts" / "seal_repurchase_item703_labels.py")
)
parse_bool = MODULE["parse_bool"]
run = MODULE["run"]
validate_labels = MODULE["validate_labels"]
validate_attestation = MODULE["validate_attestation"]
validate_blind_packet = MODULE["validate_blind_packet"]
packet_content_hash = MODULE["packet_content_hash"]


def sample() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cik": 1,
                "accession": "a",
                "filing_year": 2020,
                "form": "10-K",
                "document_url": "https://example.test/a",
            },
            {
                "cik": 2,
                "accession": "b",
                "filing_year": 2021,
                "form": "10-Q",
                "document_url": "https://example.test/b",
            },
        ]
    )


def labels() -> pd.DataFrame:
    frame = sample()
    frame["has_item703_table"] = ["true", "false"]
    frame["expected_month_rows"] = [3, 0]
    frame["expected_total_row"] = ["1", "0"]
    frame["label_notes"] = ["quarter", "absent"]
    return frame


def test_labels_are_exact_complete_and_typed() -> None:
    result = validate_labels(labels(), sample())

    assert result["has_item703_table"].tolist() == [True, False]
    assert result["expected_month_rows"].tolist() == [3, 0]
    assert result["expected_total_row"].tolist() == [True, False]


def test_absent_table_cannot_claim_rows() -> None:
    frame = labels()
    frame.loc[1, "expected_month_rows"] = 1

    with pytest.raises(ValueError, match="without Item 703"):
        validate_labels(frame, sample())


def test_boolean_labels_fail_closed() -> None:
    with pytest.raises(ValueError, match="must be true/false"):
        parse_bool("yes", "field")


def test_reviewer_attestation_requires_every_independence_flag(tmp_path: Path) -> None:
    path = tmp_path / "attestation.json"
    path.write_text(
        """{
          "reviewer_name": "Independent Reviewer",
          "reviewer_role": "research auditor",
          "completed_at": "2026-08-23T00:00:00Z",
          "independent_of_parser_development": true,
          "machine_outputs_not_consulted": true,
          "prices_and_returns_not_consulted": true,
          "all_labels_are_personally_reviewed": false
        }"""
    )
    with pytest.raises(ValueError, match="all_labels_are_personally_reviewed=true"):
        validate_attestation(path)


def test_labels_cannot_be_sealed_after_parser_output(tmp_path: Path) -> None:
    parser_result = tmp_path / "parser.json"
    parser_result.write_text("{}")
    args = SimpleNamespace(
        out=tmp_path / "seal.json",
        parse_parts=tmp_path / "parts",
        parser_result=parser_result,
    )

    with pytest.raises(RuntimeError, match="after parser output"):
        run(args)


def test_blind_packet_validation_binds_templates_and_documents(tmp_path: Path) -> None:
    packet = tmp_path / "packet"
    documents = packet / "documents"
    documents.mkdir(parents=True)
    (packet / "reviewer_labels.csv").write_text("packet_id,label\nP-1,\n")
    (packet / "reviewer_attestation.json").write_text("{}\n")
    (documents / "P-1.html").write_text("<html>source</html>\n")
    sha = MODULE["file_sha256"]
    manifest = {
        "schema": "canli.labeling.repurchase-item703-blind-packet.v1",
        "prediction_blind": True,
        "packet_files": {
            "reviewer_labels_sha256": sha(packet / "reviewer_labels.csv"),
            "reviewer_attestation_template_sha256": sha(
                packet / "reviewer_attestation.json"
            ),
            "documents": {"P-1.html": sha(documents / "P-1.html")},
        },
    }
    manifest["content_hash"] = packet_content_hash(manifest)
    (packet / "manifest.json").write_text(json.dumps(manifest))
    validate_blind_packet(packet)

    (documents / "P-1.html").write_text("<html>tampered</html>\n")
    with pytest.raises(ValueError, match="document hash mismatch"):
        validate_blind_packet(packet)
