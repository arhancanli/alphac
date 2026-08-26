#!/usr/bin/env python3
"""Prepare and fail-closed verify an author's manuscript-approval response overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
GENERATOR: Final = ROOT / "scripts" / "build_author_technical_audit_worksheets.py"
sys.path.insert(0, str(ROOT / "scripts"))

from build_author_technical_audit_worksheets import (  # noqa: E402, I001
    build_worksheet,
    registry_item,
)
RESPONSE_SCHEMA: Final = "canli.alphac-author-technical-approval-response.v1"
RECEIPT_SCHEMA: Final = "canli.alphac-author-technical-approval-receipt.v1"
APPROVAL_STATEMENT: Final = (
    "I, Arhan Canli, have reviewed this exact manuscript version and take responsibility for "
    "every retained claim, correction, limitation, and disclosure."
)
ALLOWED_CAPITAL_KINDS: Final = {
    "HISTORICAL_RESEARCH_SIMULATION",
    "ALPACA_PAPER",
    "FUNDED_CAPITAL",
    "NON_PERFORMANCE_METHODS_OR_GOVERNANCE",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _authoritative_worksheet(registry_key: str) -> dict[str, Any]:
    worksheet = build_worksheet(registry_item(registry_key))
    if worksheet.get("content_hash") != _content_hash(worksheet):
        raise ValueError("author worksheet content hash does not verify")
    return worksheet


def _worksheet_binding(worksheet: dict[str, Any]) -> dict[str, Any]:
    return {
        "generator": str(GENERATOR.relative_to(ROOT)),
        "generator_sha256": _sha256(GENERATOR),
        "schema": worksheet["schema"],
        "content_hash": worksheet["content_hash"],
    }


def prepare(registry_key: str) -> dict[str, Any]:
    worksheet = _authoritative_worksheet(registry_key)
    response: dict[str, Any] = {
        "schema": RESPONSE_SCHEMA,
        "registry_key": registry_key,
        "author": "Arhan Canli",
        "worksheet_binding": _worksheet_binding(worksheet),
        "manuscript_binding": dict(worksheet["manuscript"]),
        "paper_pdf_binding": dict(worksheet["paper_pdf"]),
        "bundle_manifest_binding": dict(worksheet["bundle_manifest"]),
        "author_questions": [
            {
                "id": item["id"],
                "prompt": item["prompt"],
                "answer": None,
                "answered_by": None,
                "approved_by_author": False,
            }
            for item in worksheet["author_questions"]
        ],
        "claim_trace": [],
        "research_integrity_checks": [
            {"check": item["check"], "passes": None, "evidence": None}
            for item in worksheet["research_integrity_checks"]
        ],
        "ai_assistance": {
            "used": None,
            "systems": [],
            "scope": None,
            "venue_disclosure_text": None,
            "author_reviewed_every_retained_claim": False,
            "disclosure_approved_by_author": False,
        },
        "approval": {
            "decision": None,
            "blocking_issues": [],
            "author_statement": None,
            "explicit_authorization_reference": None,
            "approval_date": None,
            "approved_manuscript_sha256": None,
            "approved_pdf_sha256": None,
            "self_attested_by_author": False,
        },
        "claim_boundary": (
            "This is an uncompleted response overlay. Automation populated bindings and prompts "
            "only; it proves no author answer, audit, approval, review, or publication."
        ),
    }
    return response


def _required_text(value: object, label: str, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise ValueError(f"{label} must contain at least {minimum} non-whitespace characters")
    normalized = value.strip()
    if normalized.startswith("[") or "TODO" in normalized.upper():
        raise ValueError(f"{label} still contains placeholder text")
    return normalized


def _bound_file(binding: object, authoritative: dict[str, Any], label: str) -> Path:
    if not isinstance(binding, dict) or binding != authoritative:
        raise ValueError(f"{label} does not equal the authoritative worksheet binding")
    path = (ROOT / str(authoritative["path"])).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError(f"{label} path is absent or escapes the repository")
    if _sha256(path) != authoritative["sha256"]:
        raise ValueError(f"{label} file changed after the worksheet was generated")
    return path


def verify(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("schema") != RESPONSE_SCHEMA:
        raise ValueError("unexpected author approval response schema")
    registry_key = _required_text(response.get("registry_key"), "registry_key")
    if response.get("author") != "Arhan Canli":
        raise ValueError("the response author must be exactly Arhan Canli")
    worksheet = _authoritative_worksheet(registry_key)

    expected_worksheet_binding = _worksheet_binding(worksheet)
    if response.get("worksheet_binding") != expected_worksheet_binding:
        raise ValueError("response is not bound to the current immutable worksheet")
    manuscript = _bound_file(
        response.get("manuscript_binding"), worksheet["manuscript"], "manuscript_binding"
    )
    paper_pdf = _bound_file(
        response.get("paper_pdf_binding"), worksheet["paper_pdf"], "paper_pdf_binding"
    )
    _bound_file(
        response.get("bundle_manifest_binding"),
        worksheet["bundle_manifest"],
        "bundle_manifest_binding",
    )

    expected_questions = {item["id"]: item for item in worksheet["author_questions"]}
    answers = response.get("author_questions")
    if (
        not isinstance(answers, list)
        or len(answers) != len(expected_questions)
        or {item.get("id") for item in answers} != set(expected_questions)
    ):
        raise ValueError("all and only the governed author questions must be answered")
    for answer in answers:
        expected = expected_questions[str(answer["id"])]
        if answer.get("prompt") != expected["prompt"]:
            raise ValueError(f"question prompt changed for {answer['id']}")
        _required_text(answer.get("answer"), f"answer {answer['id']}", 40)
        if answer.get("answered_by") != "Arhan Canli":
            raise ValueError(f"answer {answer['id']} is not attributed to Arhan Canli")
        if answer.get("approved_by_author") is not True:
            raise ValueError(f"answer {answer['id']} is not approved by the author")

    claims = response.get("claim_trace")
    if not isinstance(claims, list) or not claims:
        raise ValueError("at least one result-bearing claim trace is required")
    claim_ids: set[str] = set()
    for index, claim in enumerate(claims, start=1):
        if not isinstance(claim, dict):
            raise ValueError(f"claim trace row {index} must be an object")
        claim_id = _required_text(claim.get("id"), f"claim trace row {index} id")
        if claim_id in claim_ids:
            raise ValueError(f"duplicate claim trace id {claim_id!r}")
        claim_ids.add(claim_id)
        _required_text(claim.get("claim"), f"claim {claim_id} text", 12)
        _required_text(claim.get("manuscript_location"), f"claim {claim_id} location", 3)
        if claim.get("capital_kind") not in ALLOWED_CAPITAL_KINDS:
            raise ValueError(f"claim {claim_id} has an unsupported capital kind")
        source_rel = _required_text(claim.get("source_artifact"), f"claim {claim_id} source")
        source = (ROOT / source_rel).resolve()
        if not source.is_relative_to(ROOT) or not source.is_file():
            raise ValueError(f"claim {claim_id} source is absent or escapes the repository")
        if claim.get("source_sha256") != _sha256(source):
            raise ValueError(f"claim {claim_id} source hash does not verify")
        _required_text(claim.get("selector"), f"claim {claim_id} selector")
        if claim.get("recomputed_value") is None:
            raise ValueError(f"claim {claim_id} has no recomputed value")
        if claim.get("matches_manuscript") is not True:
            raise ValueError(f"claim {claim_id} is not confirmed to match the manuscript")

    expected_checks = {item["check"] for item in worksheet["research_integrity_checks"]}
    checks = response.get("research_integrity_checks")
    if (
        not isinstance(checks, list)
        or len(checks) != len(expected_checks)
        or {item.get("check") for item in checks} != expected_checks
    ):
        raise ValueError("all and only the governed research-integrity checks are required")
    for check in checks:
        check_id = str(check["check"])
        if check.get("passes") is not True:
            raise ValueError(f"research-integrity check {check_id} does not pass")
        _required_text(check.get("evidence"), f"research-integrity check {check_id} evidence", 8)

    ai = response.get("ai_assistance")
    if not isinstance(ai, dict) or not isinstance(ai.get("used"), bool):
        raise ValueError("AI assistance used must be answered explicitly true or false")
    systems = ai.get("systems")
    if not isinstance(systems, list) or any(not isinstance(item, str) for item in systems):
        raise ValueError("AI assistance systems must be a list of names")
    if ai["used"]:
        if not systems:
            raise ValueError("AI-assisted work must name the systems used")
        _required_text(ai.get("scope"), "AI assistance scope", 20)
        _required_text(ai.get("venue_disclosure_text"), "venue AI disclosure text", 30)
    elif systems:
        raise ValueError("AI systems cannot be named while AI assistance used is false")
    if ai.get("author_reviewed_every_retained_claim") is not True:
        raise ValueError("the author must review every retained claim")
    if ai.get("disclosure_approved_by_author") is not True:
        raise ValueError("the venue AI disclosure is not approved by the author")

    approval = response.get("approval")
    if not isinstance(approval, dict):
        raise ValueError("approval must be an object")
    if approval.get("decision") != "APPROVED_FOR_FRESH_READER":
        raise ValueError("only APPROVED_FOR_FRESH_READER produces an approval receipt")
    if approval.get("blocking_issues") != []:
        raise ValueError("an approved response cannot retain blocking issues")
    if approval.get("author_statement") != APPROVAL_STATEMENT:
        raise ValueError("the exact governed author responsibility statement is required")
    authorization = _required_text(
        approval.get("explicit_authorization_reference"), "explicit authorization reference", 12
    )
    approval_date = _required_text(approval.get("approval_date"), "approval date", 10)
    try:
        parsed_approval_date = date.fromisoformat(approval_date)
    except ValueError as error:
        raise ValueError("approval date must be an ISO 8601 calendar date") from error
    if parsed_approval_date > datetime.now(UTC).date():
        raise ValueError("approval date cannot be in the future")
    if approval.get("approved_manuscript_sha256") != _sha256(manuscript):
        raise ValueError("approved manuscript hash is not the current manuscript")
    if approval.get("approved_pdf_sha256") != _sha256(paper_pdf):
        raise ValueError("approved PDF hash is not the current PDF")
    if approval.get("self_attested_by_author") is not True:
        raise ValueError("author self-attestation is required")

    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "status": "PASS_SELF_ATTESTED_AUTHOR_TECHNICAL_APPROVAL",
        "registry_key": registry_key,
        "author": "Arhan Canli",
        "approval_date": approval_date,
        "explicit_authorization_reference": authorization,
        "manuscript": {"path": str(manuscript.relative_to(ROOT)), "sha256": _sha256(manuscript)},
        "paper_pdf": {"path": str(paper_pdf.relative_to(ROOT)), "sha256": _sha256(paper_pdf)},
        "worksheet": expected_worksheet_binding,
        "response_sha256": hashlib.sha256(_canonical(response)).hexdigest(),
        "questions_answered": len(answers),
        "claim_trace_rows": len(claims),
        "integrity_checks_passed": len(checks),
        "ai_assistance_used": ai["used"],
        "ai_systems_disclosed": systems,
        "venue_disclosure_text": ai.get("venue_disclosure_text"),
        "approved_for_fresh_reader": True,
        "external_review_claimed": False,
        "publication_claimed": False,
        "identity_proof": "AUTHOR_SELF_ATTESTATION_NOT_INDEPENDENTLY_VERIFIED_BY_SOFTWARE",
        "claim_boundary": (
            "This receipt proves that a structurally complete self-attested response matches the "
            "current repository hashes. Software cannot prove who typed it. It is not fresh-reader "
            "review, external domain review, independent replication, peer review, submission, or "
            "publication acceptance."
        ),
    }
    receipt["content_hash"] = _content_hash(receipt)
    return receipt


def _write_new(path: Path, document: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--registry-key", required=True)
    prepare_parser.add_argument("--output", type=Path, required=True)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--input", type=Path, required=True)
    verify_parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        if args.command == "prepare":
            document = prepare(str(args.registry_key))
            _write_new(args.output, document)
            print(f"prepared blank author response -> {args.output}")
            return 0

        response = _load_json(args.input)
        receipt = verify(response)
        if args.output is not None:
            _write_new(args.output, receipt)
            print(f"verified author approval receipt -> {args.output}")
        else:
            print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except (FileExistsError, FileNotFoundError, KeyError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
