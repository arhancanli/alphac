#!/usr/bin/env python3
"""Build a synthetic packet for clean-checkout browser-interface QA.

The fixture tests the offline workspace and verifier contract. It contains no SEC
research corpus and cannot be used as research evidence or as a human review.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[2]
TEMPLATE: Final = ROOT / "assets" / "active_ownership_review_workspace.html"
VERIFIER: Final = ROOT / "scripts" / "reviewer_verify_active_ownership.py"
SCHEMA: Final = "canli.labeling.active-ownership-13d-item4-blind-packet.v3"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def build(out: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    documents = out / "documents"
    documents.mkdir(exist_ok=True)
    rows: list[dict[str, Any]] = []
    document_hashes: dict[str, str] = {}
    for index in range(1, 49):
        packet_id = f"AO13D-{index:03d}"
        accession = f"0000000000-26-{index:06d}"
        source_text = (
            f"Synthetic browser-QA source excerpt {index}. "
            "This text tests selection, autosave, completion, export, and responsive layout."
        )
        digest = hashlib.sha256(source_text.encode()).hexdigest()
        row = {
            "packet_id": packet_id,
            "year": 2026,
            "accession": accession,
            "ticker": f"QA{index:02d}",
            "submission_url": "https://www.sec.gov/edgar/search/",
            "item4_sha256": digest,
            "document_text": source_text,
        }
        rows.append(row)
        document_path = documents / f"{packet_id}.txt"
        document_path.write_text(source_text + "\n")
        document_hashes[document_path.name] = _sha256(document_path)

    immutable = [
        "packet_id",
        "year",
        "accession",
        "ticker",
        "submission_url",
        "item4_sha256",
    ]
    labels_path = out / "reviewer_labels.csv"
    human = [
        "human_specific_active_intent",
        "human_representative_sentence",
        "human_aggregate_ownership_pct_or_unresolved",
        "human_notes",
    ]
    with labels_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*immutable, *human])
        writer.writeheader()
        for row in rows:
            writer.writerow({**{key: row[key] for key in immutable}, **dict.fromkeys(human, "")})

    attestation_path = out / "reviewer_attestation.json"
    attestation_path.write_text(
        json.dumps(
            {
                "reviewer_name": "",
                "reviewer_role": "",
                "reviewer_affiliation": "",
                "relationship_to_researcher": "",
                "compensation_or_incentive": "",
                "conflicts_of_interest": "",
                "completed_at": "",
                "packet_manifest_content_hash": "",
                "independent_of_parser_development": False,
                "independent_of_research_design": False,
                "machine_outputs_not_consulted": False,
                "prices_and_returns_not_consulted": False,
                "no_automated_or_ai_labeling_assistance": False,
                "no_outcome_contingent_compensation": False,
                "conflicts_disclosed_completely": False,
                "all_labels_are_personally_reviewed": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    instructions_path = out / "INSTRUCTIONS.md"
    instructions_path.write_text(
        "# Synthetic browser QA fixture\n\n"
        "This fixture tests interface behavior only. It is not research evidence or a review.\n"
    )
    verifier_path = out / "verify_review.py"
    shutil.copyfile(VERIFIER, verifier_path)

    payload = {
        "packet_key": "synthetic-browser-qa-v1",
        "immutable_columns": immutable,
        "rows": rows,
    }
    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count("__PACKET_DATA__") != 1:
        raise ValueError("review template must contain exactly one packet marker")
    embedded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).replace("</", "<\\/")
    review_path = out / "review.html"
    review_path.write_text(template.replace("__PACKET_DATA__", embedded), encoding="utf-8")

    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "author": "Arhan Canli",
        "rows": 48,
        "prediction_blind": True,
        "forbidden_machine_fields": [
            "active_sentences",
            "ownership_pct_candidates",
            "specific_active_intent",
        ],
        "packet_files": {
            "instructions_sha256": _sha256(instructions_path),
            "reviewer_labels_sha256": _sha256(labels_path),
            "reviewer_attestation_template_sha256": _sha256(attestation_path),
            "review_workspace_sha256": _sha256(review_path),
            "review_verifier_sha256": _sha256(verifier_path),
            "documents": document_hashes,
        },
        "synthetic_fixture": True,
        "research_evidence": False,
        "claim_boundary": (
            "Synthetic clean-checkout browser fixture only; no filing classification, reviewer "
            "judgment, performance result, or research validation may be inferred."
        ),
    }
    manifest["content_hash"] = _content_hash(manifest)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = build(args.out)
    print(json.dumps({"status": "SYNTHETIC_BROWSER_FIXTURE_READY", **manifest}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
