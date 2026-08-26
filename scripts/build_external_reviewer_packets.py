#!/usr/bin/env python3
"""Build hash-bound, preparation-only reviewer packets for flagship papers."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
REGISTRY: Final = ROOT / "config/external_publication_registry.json"
PROTOCOL: Final = ROOT / "config/external_review_protocol.json"
ARCHIVES: Final = ROOT / "artifacts/publication/all_sleeve_review_archives.json"
REVIEWER_BRIEF: Final = ROOT / "docs/design/EXTERNAL_REVIEWER_BRIEF_TEMPLATE.md"
RESPONSE_MATRIX: Final = ROOT / "docs/design/EXTERNAL_REVIEW_RESPONSE_MATRIX_TEMPLATE.md"
AUTHOR_AUDIT: Final = ROOT / "docs/design/AUTHOR_TECHNICAL_AUDIT_TEMPLATE.md"
ACQUISITION_PLAN: Final = ROOT / "docs/design/EXTERNAL_REVIEW_ACQUISITION_PLAN.md"
OUTPUT_ROOT: Final = ROOT / "artifacts/publication/external_reviewer_packets"
OUTPUT: Final = ROOT / "artifacts/publication/external_reviewer_packets.json"

QUESTIONS: Final = [
    "What is the strongest reason the central conclusion could be wrong?",
    "Does the information set contain plausible look-ahead, survivorship, or revision leakage?",
    "Does trial accounting include every inspected return identity that should affect inference?",
    "Are the estimator, uncertainty measure, and decision threshold appropriate for the decision?",
    "Do costs, turnover, financing, borrow, capacity, and impact support the interpretation?",
    "Can every result-bearing table and figure be traced to a released artifact?",
    "Which claim should be weakened, removed, or tested prospectively?",
    "Can the released protocol be reproduced without verbal guidance from the author?",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _packet_markdown(packet: dict[str, Any]) -> str:
    roles = "\n".join(
        f"- `{role['role']}`: `{role['required_scope']}`; reviewer not assigned"
        for role in packet["requested_reviews"]
    )
    questions = "\n".join(
        f"{number}. {question}" for number, question in enumerate(packet["questions"], start=1)
    )
    return f"""# External review request preparation: {packet['title']}

- **Author:** Arhan Canli
- **Status:** preparation only; no reviewer assigned, contacted, or completed
- **Manuscript SHA-256:** `{packet['manuscript']['sha256']}`
- **PDF SHA-256:** `{packet['paper_pdf']['sha256']}`
- **Review archive SHA-256:** `{packet['review_archive']['sha256']}`

## Requested independent roles

{roles}

The request asks for criticism, not endorsement. A reviewer must disclose qualifications,
relationships, financial conflicts, compensation, publication permissions, and automated-tool
use. Compensation may pay for time but may not depend on approval or a favourable conclusion.

## Questions

{questions}

## Required deliverables

1. A numbered review letter with `BLOCKING`, `MAJOR`, `MINOR`, or `QUESTION` severity.
2. A conflict and compensation statement.
3. Commands, environment, hashes, and deviations if execution is attempted.
4. A clear distinction between editorial review and independent replication.

Arhan must answer every finding in the governed response matrix. A completed local packet does not
establish outreach, review, replication, peer review, submission, acceptance, or endorsement.
"""


def generate(out_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    registry = json.loads(REGISTRY.read_text())
    protocol = json.loads(PROTOCOL.read_text())
    archives = json.loads(ARCHIVES.read_text())
    by_key = {item["key"]: item for item in registry["sleeves"]}
    archive_by_key = {item["registry_key"]: item for item in archives["records"]}
    flagship_keys = protocol["minimum_review_plan"]["flagship_registry_keys"]
    scopes = protocol["minimum_review_plan"]["required_external_scopes"]
    if len(scopes) != 2:
        raise ValueError("flagship review packets require exactly two governed external scopes")
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)
    records: list[dict[str, Any]] = []

    for key in flagship_keys:
        item = by_key[key]
        archive = archive_by_key[key]
        manuscript = ROOT / item["source_paper"]
        bundle_manifest = ROOT / item["bundle_manifest"]
        paper_pdf = bundle_manifest.parent / "paper.pdf"
        archive_path = ROOT / archive["archive"]
        for path in (manuscript, bundle_manifest, paper_pdf, archive_path):
            if not path.is_file():
                raise FileNotFoundError(path)
        text = manuscript.read_text()
        if "Arhan Canli" not in text or "not peer reviewed" not in text.lower():
            raise ValueError(f"manuscript lacks authorship or review boundary: {manuscript}")

        packet: dict[str, Any] = {
            "schema": "canli.alphac-external-review-request-packet.v1",
            "status": "PREPARATION_ONLY_NO_REVIEWER_ASSIGNED_ZERO_REVIEWS",
            "registry_key": key,
            "title": item["title"],
            "author": "Arhan Canli",
            "version": bundle_manifest.parent.name,
            "manuscript": {
                "path": item["source_paper"],
                "sha256": _sha256(manuscript),
            },
            "paper_pdf": {
                "path": str(paper_pdf.relative_to(ROOT)),
                "sha256": _sha256(paper_pdf),
            },
            "review_archive": {
                "path": archive["archive"],
                "sha256": _sha256(archive_path),
                "manifest_sha256": archive["sha256"],
            },
            "requested_reviews": [
                {
                    "role": "METHODS_REVIEWER",
                    "required_scope": scopes[0],
                    "reviewer_identity": None,
                    "reviewer_qualifications": [],
                    "conflicts": None,
                    "compensation": None,
                    "assigned": False,
                    "completed": False,
                },
                {
                    "role": "REPRODUCIBILITY_REVIEWER",
                    "required_scope": scopes[1],
                    "reviewer_identity": None,
                    "reviewer_qualifications": [],
                    "conflicts": None,
                    "compensation": None,
                    "assigned": False,
                    "completed": False,
                },
            ],
            "questions": list(QUESTIONS),
            "governed_templates": protocol["governed_templates"],
            "outreach_authorized": protocol["outreach_authorized"],
            "external_account_actions_authorized": protocol[
                "external_account_actions_authorized"
            ],
            "review_claimed": False,
            "independent_replication_claimed": False,
            "submission_claimed": False,
            "claim_boundary": (
                "This packet binds one manuscript, PDF, and review archive to two unassigned "
                "review roles. It proves no outreach, review, replication, endorsement, peer "
                "review, submission, acceptance, or publication."
            ),
        }
        packet["content_hash"] = _content_hash(packet)
        destination = out_root / item["bundle_slug"]
        destination.mkdir()
        packet_path = destination / "review_request.json"
        markdown_path = destination / "REVIEW_REQUEST.md"
        packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n")
        markdown_path.write_text(_packet_markdown(packet))
        records.append(
            {
                "registry_key": key,
                "packet": str(packet_path.relative_to(out_root)),
                "packet_sha256": _sha256(packet_path),
                "packet_content_hash": packet["content_hash"],
                "request_markdown": str(markdown_path.relative_to(out_root)),
                "request_markdown_sha256": _sha256(markdown_path),
                "review_roles": 2,
                "assigned_reviewers": 0,
                "completed_reviews": 0,
                "outreach_claimed": False,
            }
        )

    document: dict[str, Any] = {
        "schema": "canli.alphac-external-reviewer-packet-manifest.v1",
        "status": "PASS_PREPARATION_ONLY_ZERO_REVIEWERS_ZERO_REVIEWS",
        "author": "Arhan Canli",
        "flagship_packets": len(records),
        "review_roles": sum(record["review_roles"] for record in records),
        "assigned_reviewers": 0,
        "completed_reviews": 0,
        "outreach_authorized": protocol["outreach_authorized"],
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
            "review_archives": {
                "path": str(ARCHIVES.relative_to(ROOT)),
                "sha256": _sha256(ARCHIVES),
                "content_hash": archives["content_hash"],
            },
            "reviewer_brief": {
                "path": str(REVIEWER_BRIEF.relative_to(ROOT)),
                "sha256": _sha256(REVIEWER_BRIEF),
            },
            "response_matrix": {
                "path": str(RESPONSE_MATRIX.relative_to(ROOT)),
                "sha256": _sha256(RESPONSE_MATRIX),
            },
            "author_audit": {
                "path": str(AUTHOR_AUDIT.relative_to(ROOT)),
                "sha256": _sha256(AUTHOR_AUDIT),
            },
            "review_acquisition_plan": {
                "path": str(ACQUISITION_PLAN.relative_to(ROOT)),
                "sha256": _sha256(ACQUISITION_PLAN),
            },
        },
        "claim_boundary": (
            "These are local commissioning packets with blank reviewer fields. They prove no "
            "outreach, review, independent replication, submission, acceptance, or publication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def main() -> None:
    document = generate()
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{document['status']}: {document['flagship_packets']} packets")
    print(f"content_hash: {document['content_hash']}")


if __name__ == "__main__":
    main()
