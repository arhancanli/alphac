#!/usr/bin/env python3
"""Audit mechanical manuscript-style and authorship boundaries without scoring prose quality."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
REGISTRY: Final = ROOT / "config" / "external_publication_registry.json"
STANDARD: Final = ROOT / "docs" / "design" / "EXTERNAL_RESEARCH_PUBLICATION_STANDARD.md"
REVIEW_PROTOCOL: Final = ROOT / "config" / "external_review_protocol.json"
OUTPUT: Final = ROOT / "artifacts" / "audit" / "publication_manuscript_style.json"

FORBIDDEN_PATTERNS: Final = {
    "EM_DASH": re.compile("—"),
    "INFLATED_REVOLUTIONARY": re.compile(r"\brevolutionary\b", re.IGNORECASE),
    "INFLATED_GROUNDBREAKING": re.compile(r"\bgroundbreaking\b", re.IGNORECASE),
    "GENERIC_DELVE": re.compile(r"\bdelv(?:e|es|ed|ing)\b", re.IGNORECASE),
    "GENERIC_TAPESTRY": re.compile(r"\btapestry\b", re.IGNORECASE),
    "GENERIC_TESTAMENT": re.compile(r"\btestament to\b", re.IGNORECASE),
    "GENERIC_GAME_CHANGER": re.compile(r"\bgame[- ]changer\b", re.IGNORECASE),
    "FILLER_VERY": re.compile(r"\bvery\b", re.IGNORECASE),
    "FILLER_REALLY": re.compile(r"\breally\b", re.IGNORECASE),
    "FILLER_SIMPLY": re.compile(r"\bsimply\b", re.IGNORECASE),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def build() -> dict[str, Any]:
    registry = json.loads(REGISTRY.read_text())
    protocol = json.loads(REVIEW_PROTOCOL.read_text())
    records: list[dict[str, Any]] = []
    failures: list[str] = []

    for sleeve in registry["sleeves"]:
        path = ROOT / sleeve["source_paper"]
        text = path.read_text()
        paper_failures: list[dict[str, Any]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            for code, pattern in FORBIDDEN_PATTERNS.items():
                if pattern.search(line):
                    paper_failures.append({"code": code, "line": line_number})

        structural_checks = {
            "title_present": text.startswith("# "),
            "author_present": "Arhan Canli" in text,
            "review_boundary_present": "not peer reviewed" in text.lower(),
            "abstract_or_finding_present": (
                "## Abstract" in text or "## Finding and boundary" in text
            ),
        }
        for check, passes in structural_checks.items():
            if not passes:
                paper_failures.append({"code": check.upper(), "line": None})

        if paper_failures:
            failures.append(str(sleeve["key"]))
        records.append(
            {
                "registry_key": sleeve["key"],
                "path": sleeve["source_paper"],
                "sha256": _sha256(path),
                "word_count": len(re.findall(r"\b\w+\b", text)),
                "structural_checks": structural_checks,
                "mechanical_failures": paper_failures,
                "passes_mechanical_audit": not paper_failures,
            }
        )

    document: dict[str, Any] = {
        "schema": "canli.alphac-publication-manuscript-style-audit.v1",
        "status": "PASS_MECHANICAL_STYLE_BOUNDARY" if not failures else "FAIL_CLOSED",
        "passes": not failures,
        "owner_and_author": "Arhan Canli",
        "papers_audited": len(records),
        "papers_passing": sum(record["passes_mechanical_audit"] for record in records),
        "failed_registry_keys": failures,
        "records": records,
        "authorship_boundary": {
            "ai_detector_used": False,
            "ai_detector_evasion_claimed": False,
            "human_authorship_proved_by_this_audit": False,
            "final_human_approval_required": protocol["authorship_policy"][
                "final_human_approval_required"
            ],
        },
        "source_bindings": {
            "registry": {"path": str(REGISTRY.relative_to(ROOT)), "sha256": _sha256(REGISTRY)},
            "standard": {"path": str(STANDARD.relative_to(ROOT)), "sha256": _sha256(STANDARD)},
            "review_protocol": {
                "path": str(REVIEW_PROTOCOL.relative_to(ROOT)),
                "sha256": _sha256(REVIEW_PROTOCOL),
            },
        },
        "claim_boundary": (
            "This audit catches selected mechanical style and disclosure failures. It does not "
            "establish scientific quality, originality, human authorship, peer review, detector "
            "performance or independent replication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def main() -> int:
    document = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{document['status']}: {document['papers_passing']}/{document['papers_audited']}")
    return 0 if document["passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
