#!/usr/bin/env python3
"""Build blank, hash-bound fresh-context reader packets for every manuscript."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
REGISTRY: Final = ROOT / "config" / "external_publication_registry.json"
PROTOCOL: Final = ROOT / "config" / "external_review_protocol.json"
TEMPLATE: Final = ROOT / "docs" / "design" / "FRESH_CONTEXT_READER_TEMPLATE.md"
OUTPUT_ROOT: Final = ROOT / "artifacts" / "publication" / "fresh_context_reader_packets"
OUTPUT: Final = ROOT / "artifacts" / "publication" / "fresh_context_reader_packets.json"

QUESTIONS: Final = [
    ("HYPOTHESIS_AND_MECHANISM", "What hypothesis and economic mechanism does the paper test?"),
    ("ESTIMAND_AND_SAMPLE", "What is the estimand, unit, universe, and horizon?"),
    ("INFORMATION_SET", "What information was available at each decision time?"),
    ("PROCEDURE", "How does the procedure convert inputs into weights or a research decision?"),
    ("SEARCH_AND_DECISION", "What search breadth and decision rule govern the result?"),
    ("RESULT_AND_CAPITAL", "What result was observed, and what capital type produced it?"),
    ("CONTRARY_EVIDENCE", "What is the strongest negative or contradictory evidence?"),
    ("LIMITS_AND_REVERSAL", "Which limitations matter, and what could reverse the conclusion?"),
    ("REPRODUCTION", "Which command and evidence bundle should reproduce the result?"),
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _markdown(packet: dict[str, Any]) -> str:
    questions = "\n\n".join(
        f"### {number}. {item['prompt']}\n\n"
        "- **Answer:** `[required or UNRESOLVED]`\n"
        "- **Manuscript support:** `[section, table, figure, or artifact]`"
        for number, item in enumerate(packet["questions"], start=1)
    )
    return f"""# Fresh-context reader review: {packet['title']}

- **Status:** no reader assigned and no review claimed
- **Manuscript SHA-256:** `{packet['manuscript']['sha256']}`
- **PDF SHA-256:** `{packet['paper_pdf']['sha256']}`

## Reader disclosure

- **Identity:** `[required]`
- **Background:** `[required]`
- **Relationship or conflict:** `[required, including none]`
- **Compensation:** `[required, including none]`
- **Review date:** `[required]`

Answer from the manuscript and bundle only. Do not ask Arhan to explain an ambiguity before
recording it.

## Questions

{questions}

## Decision

- **Decision:** `[PASS_FRESH_CONTEXT / REVISION_REQUIRED]`
- **Unresolved questions:** `[required]`
- **Ambiguous claims:** `[required]`
- **Missing definitions or evidence bindings:** `[required]`
- **Reader attestation:** `[required]`

This blank packet proves no assignment, reader review, external domain review, replication, peer
review, endorsement, or publication.
"""


def generate(out_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    registry = json.loads(REGISTRY.read_text())
    protocol = json.loads(PROTOCOL.read_text())
    if protocol["current_counts"]["fresh_context_reader_reviews"] != 0:
        raise ValueError("review protocol does not declare a zero-review preparation state")
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)
    records: list[dict[str, Any]] = []

    for item in registry["sleeves"]:
        manuscript = ROOT / item["source_paper"]
        bundle_manifest = ROOT / item["bundle_manifest"]
        paper_pdf = bundle_manifest.parent / "paper.pdf"
        for path in (manuscript, bundle_manifest, paper_pdf):
            if not path.is_file():
                raise FileNotFoundError(path)
        packet: dict[str, Any] = {
            "schema": "canli.alphac-fresh-context-reader-packet.v1",
            "status": "PREPARATION_ONLY_NO_READER_ASSIGNED_ZERO_REVIEWS",
            "registry_key": item["key"],
            "title": item["title"],
            "author": "Arhan Canli",
            "manuscript": {"path": item["source_paper"], "sha256": _sha256(manuscript)},
            "paper_pdf": {
                "path": str(paper_pdf.relative_to(ROOT)),
                "sha256": _sha256(paper_pdf),
            },
            "bundle_manifest": {
                "path": item["bundle_manifest"],
                "sha256": _sha256(bundle_manifest),
            },
            "reader": {
                "identity": None,
                "background": [],
                "relationship_or_conflict": None,
                "compensation": None,
                "assigned": False,
            },
            "questions": [
                {"id": question_id, "prompt": prompt, "answer": None, "support": []}
                for question_id, prompt in QUESTIONS
            ],
            "decision": {
                "value": None,
                "unresolved_questions": [],
                "ambiguous_claims": [],
                "missing_definitions_or_evidence_bindings": [],
                "reader_attestation": None,
                "review_date": None,
            },
            "fresh_context_review_claimed": False,
            "external_domain_review_claimed": False,
            "independent_replication_claimed": False,
            "claim_boundary": (
                "This packet binds a manuscript to a blank clarity review. It proves no reader "
                "assignment, review, external domain assessment, replication, peer review, "
                "endorsement, or publication."
            ),
        }
        packet["content_hash"] = _content_hash(packet)
        destination = out_root / item["bundle_slug"]
        destination.mkdir()
        json_path = destination / "reader_review.json"
        markdown_path = destination / "READER_REVIEW.md"
        json_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n")
        markdown_path.write_text(_markdown(packet))
        records.append(
            {
                "registry_key": item["key"],
                "packet": str(json_path.relative_to(out_root)),
                "packet_sha256": _sha256(json_path),
                "packet_content_hash": packet["content_hash"],
                "markdown": str(markdown_path.relative_to(out_root)),
                "markdown_sha256": _sha256(markdown_path),
                "questions": len(QUESTIONS),
                "answers_completed": 0,
                "reader_assigned": False,
                "review_completed": False,
            }
        )

    document: dict[str, Any] = {
        "schema": "canli.alphac-fresh-context-reader-packet-manifest.v1",
        "status": "PASS_BLANK_PACKETS_ZERO_READERS_ZERO_REVIEWS",
        "papers": len(records),
        "questions": sum(record["questions"] for record in records),
        "answers_completed": 0,
        "readers_assigned": 0,
        "reviews_completed": 0,
        "packet_root": (
            str(out_root.relative_to(ROOT)) if out_root.is_relative_to(ROOT) else str(out_root)
        ),
        "records": records,
        "source_bindings": {
            "registry": {"path": str(REGISTRY.relative_to(ROOT)), "sha256": _sha256(REGISTRY)},
            "review_protocol": {
                "path": str(PROTOCOL.relative_to(ROOT)),
                "sha256": _sha256(PROTOCOL),
            },
            "template": {"path": str(TEMPLATE.relative_to(ROOT)), "sha256": _sha256(TEMPLATE)},
        },
        "claim_boundary": (
            "These are blank fresh-context reader packets. They prove no assignment, review, "
            "external domain assessment, replication, peer review, or publication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def main() -> None:
    document = generate()
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{document['status']}: {document['papers']} packets")
    print(f"content_hash: {document['content_hash']}")


if __name__ == "__main__":
    main()

