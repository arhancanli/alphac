from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "build_tender_offer_blind_label_packet.py"
SPEC = importlib.util.spec_from_file_location("tender_offer_blind_packet", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

ROOT = SCRIPT.parents[1]
PACKET = ROOT / "artifacts" / "labeling" / "tender_offer_item4_blind"
SOURCE = ROOT / "artifacts" / "feasibility" / "tender_offer_spread"


def test_persisted_packet_is_complete_prediction_blind_and_hash_bound() -> None:
    manifest = json.loads((PACKET / "manifest.json").read_text())
    labels = pd.read_csv(PACKET / "reviewer_labels.csv", keep_default_na=False)
    assert manifest["schema"] == "canli.labeling.tender-offer-item4-blind-packet.v1"
    assert manifest["rows"] == len(labels) == 30
    assert manifest["prediction_blind"] is True
    assert manifest["return_hypotheses_spent"] == 0
    assert set(MODULE.FORBIDDEN_MACHINE_FIELDS).isdisjoint(labels.columns)
    assert labels["packet_id"].is_unique
    assert labels[MODULE.HUMAN_COLUMNS].eq("").all().all()
    assert len(list((PACKET / "documents").glob("TOS-*.txt"))) == 30
    for field, path in {
        "instructions_sha256": PACKET / "INSTRUCTIONS.md",
        "reviewer_labels_sha256": PACKET / "reviewer_labels.csv",
        "reviewer_attestation_template_sha256": PACKET / "reviewer_attestation.json",
        "review_verifier_sha256": PACKET / "verify_review.py",
    }.items():
        assert manifest["packet_files"][field] == MODULE.sha256_file(path)
    assert manifest["content_hash"] == MODULE.content_hash(manifest)

    attestation = json.loads((PACKET / "reviewer_attestation.json").read_text())
    assert not any(value is True for value in attestation.values())
    assert attestation["no_automated_or_ai_labeling_assistance"] is False
    assert attestation["no_outcome_contingent_compensation"] is False


def test_packet_carries_the_frozen_source_and_none_of_the_parser_verdicts() -> None:
    audit = pd.read_parquet(SOURCE / "document_audit.parquet")
    audit["accession"] = audit["accession"].astype(str)
    by_accession = audit.set_index("accession")
    labels = pd.read_csv(PACKET / "reviewer_labels.csv", keep_default_na=False, dtype=str)
    for row in labels.to_dict("records"):
        document = (PACKET / "documents" / f"{row['packet_id']}.txt").read_text()
        header, _, body = document.partition("\n\n")
        source = by_accession.loc[str(row["accession"])]
        # The reviewer reads the frozen Item 4 text itself, bound by the hashes in the header.
        assert row["item4_sha256"] == str(source["item4_sha256"])
        assert row["item4_sha256"] in header
        assert row["document_sha256"] in header
        assert body.strip() == str(source["item4_text"]).strip()
        # Nothing the parser concluded travels with it. The header is exactly identity and source
        # hashes, so a verdict cannot ride along in it, and the body is the filing's own text.
        # (The parser's own class names are ordinary English words that occur inside filings, so
        # searching the document for them would fail on the source rather than on a leak.)
        assert [line.split(":", 1)[0] for line in header.splitlines()] == [
            "Packet ID",
            "Year",
            "CIK",
            "Accession",
            "Official document",
            "Primary document SHA-256",
            "Item 4 SHA-256",
        ]


def test_verifier_shipped_in_the_packet_is_the_governed_source() -> None:
    shipped = (PACKET / "verify_review.py").read_bytes()
    assert shipped == (ROOT / "scripts" / "reviewer_verify_tender_offer.py").read_bytes()


def test_rebuild_refuses_labels_that_are_no_longer_blind(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    pd.DataFrame(
        {
            "accession": [str(index) for index in range(30)],
            "human_unique_cash_price": ["12.50"] + [""] * 29,
            "human_recommendation": [""] * 30,
            "human_notes": [""] * 30,
        }
    ).to_csv(source / "frozen_human_labels.csv", index=False)
    with pytest.raises(ValueError, match="after human labels were opened"):
        MODULE.build(source, tmp_path / "out")


def test_rebuild_refuses_a_sample_that_is_not_the_frozen_thirty(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    pd.DataFrame(
        {
            "accession": [str(index) for index in range(29)],
            "human_unique_cash_price": [""] * 29,
            "human_recommendation": [""] * 29,
            "human_notes": [""] * 29,
        }
    ).to_csv(source / "frozen_human_labels.csv", index=False)
    with pytest.raises(ValueError, match="30 unique accessions"):
        MODULE.build(source, tmp_path / "out")
