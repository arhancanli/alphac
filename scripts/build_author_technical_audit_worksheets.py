#!/usr/bin/env python3
"""Build manuscript-specific author-audit worksheets without inventing author answers."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Final, cast

ROOT: Final = Path(__file__).resolve().parents[1]
REGISTRY: Final = ROOT / "config/external_publication_registry.json"
PROTOCOL: Final = ROOT / "config/external_review_protocol.json"
TEMPLATE: Final = ROOT / "docs/design/AUTHOR_TECHNICAL_AUDIT_TEMPLATE.md"
OUTPUT_ROOT: Final = ROOT / "artifacts/publication/author_technical_audits"
OUTPUT: Final = ROOT / "artifacts/publication/author_technical_audits.json"

QUESTIONS: Final = [
    ("WHY_TEST", "Why was this question worth testing?"),
    (
        "MECHANISM_AND_FALSIFIER",
        "Which mechanism did you expect, and what evidence would falsify it?",
    ),
    (
        "DECISIVE_IMPLEMENTATION",
        "Which implementation decision had the largest effect on the result?",
    ),
    ("CONTRARY_EVIDENCE", "What is the strongest evidence against your preferred interpretation?"),
    (
        "PROSPECTIVE_CHANGE",
        "What would you change in a prospective replication, without changing the reported "
        "historical decision?",
    ),
]

INTEGRITY_CHECKS: Final = [
    "COMPLETE_CHARGED_IDENTITY_UNION_RECONCILED",
    "NEGATIVE_AND_CONTRADICTORY_RESULTS_DISCLOSED",
    "POINT_IN_TIME_AND_SURVIVORSHIP_BOUNDARY_STATED",
    "COSTS_FINANCING_BORROW_IMPACT_AND_CAPACITY_BOUNDARY_STATED",
    "DSR_USES_DECLARED_UNION_WITHOUT_RETROSPECTIVE_REGRADE",
    "HISTORICAL_ALPACA_PAPER_AND_FUNDED_CAPITAL_SEPARATED",
    "KNOWN_CORRECTIONS_AND_UNRESOLVED_DEFECTS_DISCLOSED",
    "REFERENCES_CHECKED_AGAINST_PRIMARY_SOURCES",
    "REPRODUCTION_COMMAND_EXECUTED_IN_DECLARED_ENVIRONMENT",
    "MANUSCRIPT_READ_ALOUD_AND_REVISED_FOR_AUTHOR_MEANING",
    "VENUE_SPECIFIC_AI_ASSISTANCE_DISCLOSURE_REVIEWED",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _markdown(worksheet: dict[str, Any]) -> str:
    questions = "\n\n".join(
        f"### {number}. {item['prompt']}\n\n`[Arhan's answer required]`"
        for number, item in enumerate(worksheet["author_questions"], start=1)
    )
    checks = "\n".join(
        f"- [ ] `{item['check']}`: evidence required"
        for item in worksheet["research_integrity_checks"]
    )
    return f"""# Author technical audit: {worksheet['title']}

- **Author:** Arhan Canli
- **Status:** awaiting Arhan's technical audit; no approval claimed
- **Manuscript SHA-256:** `{worksheet['manuscript']['sha256']}`
- **PDF SHA-256:** `{worksheet['paper_pdf']['sha256']}`

## Author's research account

These answers must be written and approved by Arhan. Automation may not invent, paraphrase, or
approve them.

{questions}

## Claim trace

Add one row for every result-bearing claim, table, and figure. An empty trace blocks approval.

| Claim | Location | Capital kind | Source artifact | Selector | Recomputed value | Match |
|---|---|---|---|---|---:|---|
| `[required]` | | | | | | |

## Research-integrity checks

{checks}

## Approval

- **Decision:** `[REVISION_REQUIRED / APPROVED_FOR_FRESH_READER / WITHDRAWN]`
- **Blocking issues:** `[required]`
- **Author statement:** `[required]`
- **Governed signature or approval reference:** `[required]`

This blank worksheet proves no author audit, approval, external review, or publication.
"""


def registry_item(registry_key: str) -> dict[str, Any]:
    registry = json.loads(REGISTRY.read_text())
    matches = [item for item in registry["sleeves"] if item["key"] == registry_key]
    if len(matches) != 1:
        raise ValueError(f"registry key {registry_key!r} is not uniquely registered")
    return cast(dict[str, Any], matches[0])


def build_worksheet(item: dict[str, Any]) -> dict[str, Any]:
    manuscript = ROOT / item["source_paper"]
    bundle_manifest = ROOT / item["bundle_manifest"]
    paper_pdf = bundle_manifest.parent / "paper.pdf"
    for path in (manuscript, bundle_manifest, paper_pdf):
        if not path.is_file():
            raise FileNotFoundError(path)
    worksheet: dict[str, Any] = {
        "schema": "canli.alphac-author-technical-audit-worksheet.v1",
        "status": "AWAITING_ARHAN_TECHNICAL_AUDIT_NO_APPROVAL_CLAIMED",
        "registry_key": item["key"],
        "title": item["title"],
        "author": "Arhan Canli",
        "manuscript": {
            "path": item["source_paper"],
            "sha256": _sha256(manuscript),
        },
        "paper_pdf": {
            "path": str(paper_pdf.relative_to(ROOT)),
            "sha256": _sha256(paper_pdf),
        },
        "bundle_manifest": {
            "path": item["bundle_manifest"],
            "sha256": _sha256(bundle_manifest),
        },
        "author_questions": [
            {
                "id": question_id,
                "prompt": prompt,
                "answer": None,
                "answered_by": None,
                "approved_by_author": False,
            }
            for question_id, prompt in QUESTIONS
        ],
        "claim_trace": [],
        "research_integrity_checks": [
            {"check": check, "passes": None, "evidence": None}
            for check in INTEGRITY_CHECKS
        ],
        "approval": {
            "decision": None,
            "blocking_issues": [],
            "author_statement": None,
            "governed_signature_or_approval_reference": None,
            "approved_manuscript_sha256": None,
        },
        "ai_detector_used": False,
        "ai_detector_evasion_claimed": False,
        "author_audit_claimed": False,
        "external_review_claimed": False,
        "claim_boundary": (
            "This machine-populated worksheet binds one manuscript and leaves every author "
            "judgment, claim trace, integrity decision, and approval blank. It proves no "
            "authorship audit, approval, external review, or publication."
        ),
    }
    worksheet["content_hash"] = _content_hash(worksheet)
    return worksheet


def generate(out_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    registry = json.loads(REGISTRY.read_text())
    protocol = json.loads(PROTOCOL.read_text())
    if protocol["governed_templates"]["automation_may_invent_author_answers_or_approval"]:
        raise ValueError("review protocol improperly permits invented author approval")
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)
    records: list[dict[str, Any]] = []

    for item in registry["sleeves"]:
        worksheet = build_worksheet(item)
        destination = out_root / item["bundle_slug"]
        destination.mkdir()
        json_path = destination / "author_audit.json"
        markdown_path = destination / "AUTHOR_AUDIT.md"
        json_path.write_text(json.dumps(worksheet, indent=2, sort_keys=True) + "\n")
        markdown_path.write_text(_markdown(worksheet))
        records.append(
            {
                "registry_key": item["key"],
                "worksheet": str(json_path.relative_to(out_root)),
                "worksheet_sha256": _sha256(json_path),
                "worksheet_content_hash": worksheet["content_hash"],
                "markdown": str(markdown_path.relative_to(out_root)),
                "markdown_sha256": _sha256(markdown_path),
                "questions": len(QUESTIONS),
                "answers_completed": 0,
                "claim_trace_rows": 0,
                "approved": False,
            }
        )

    document: dict[str, Any] = {
        "schema": "canli.alphac-author-technical-audit-worksheet-manifest.v1",
        "status": "PASS_BLANK_WORKSHEETS_ZERO_AUTHOR_APPROVALS",
        "author": "Arhan Canli",
        "worksheets": len(records),
        "questions": sum(record["questions"] for record in records),
        "answers_completed": 0,
        "author_audits_completed": 0,
        "author_approvals": 0,
        "worksheet_root": (
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
            "These are blank manuscript-specific author worksheets. They prove no answers, "
            "claim tracing, technical audit, approval, external review, or publication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def main() -> None:
    document = generate()
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{document['status']}: {document['worksheets']} worksheets")
    print(f"content_hash: {document['content_hash']}")


if __name__ == "__main__":
    main()
