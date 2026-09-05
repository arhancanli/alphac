#!/usr/bin/env python3
"""Prepare and fail-closed verify an author's approval-gated protocol response."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
BUILDER: Final = ROOT / "scripts" / "build_author_protocol_review_packets.py"
sys.path.insert(0, str(ROOT / "scripts"))

from build_author_protocol_review_packets import (  # noqa: E402
    build_packet,
    canonical,
    content_hash,
    registry_item,
    sha256_file,
)

RESPONSE_SCHEMA: Final = "canli.alphac-author-protocol-approval-response.v1"
RECEIPT_SCHEMA: Final = "canli.alphac-author-protocol-approval-receipt.v1"
AUTHOR_STATEMENT: Final = (
    "I, Arhan Canli, reviewed this exact protocol and evidence version, wrote the answers in this "
    "response, and take responsibility for every retained rule, limitation, and disclosure."
)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _required_text(value: object, label: str, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise ValueError(f"{label} must contain at least {minimum} non-whitespace characters")
    normalized = value.strip()
    if normalized.startswith("[") or "TODO" in normalized.upper():
        raise ValueError(f"{label} still contains placeholder text")
    return normalized


def _packet_binding(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "builder": str(BUILDER.relative_to(ROOT)),
        "builder_sha256": sha256_file(BUILDER),
        "schema": packet["schema"],
        "content_hash": packet["content_hash"],
    }


def prepare(review_key: str) -> dict[str, Any]:
    packet = build_packet(registry_item(review_key))
    return {
        "schema": RESPONSE_SCHEMA,
        "status": "UNCOMPLETED_AUTHOR_RESPONSE_NO_APPROVAL_CLAIMED",
        "review_key": review_key,
        "family": packet["family"],
        "title": packet["title"],
        "author": "Arhan Canli",
        "packet_binding": _packet_binding(packet),
        "protocol_binding": dict(packet["protocol_binding"]),
        "evidence_binding": dict(packet["evidence_binding"]),
        "activation_boundary": dict(packet["activation_boundary"]),
        "author_questions": [dict(item) for item in packet["author_questions"]],
        "technical_checks": [dict(item) for item in packet["technical_checks"]],
        "ai_assistance": dict(packet["ai_assistance"]),
        "approval": dict(packet["approval"]),
        "claim_boundary": (
            "This uncompleted response is bound to one current protocol packet. Automation "
            "populated bindings and prompts only; it proves no author answer, approval, identity, "
            "next-stage authorization, external review, or publication."
        ),
    }


def _verify_file_binding(binding: object, authoritative: dict[str, Any], label: str) -> Path:
    if not isinstance(binding, dict) or binding != authoritative:
        raise ValueError(f"{label} does not equal the authoritative packet binding")
    path = (ROOT / str(authoritative["path"])).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError(f"{label} path is absent or escapes the repository")
    if sha256_file(path) != authoritative["sha256"]:
        raise ValueError(f"{label} file changed after packet preparation")
    return path


def verify(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("schema") != RESPONSE_SCHEMA:
        raise ValueError("unexpected author protocol response schema")
    if response.get("status") != "AUTHOR_COMPLETED_RESPONSE":
        raise ValueError("response status must be AUTHOR_COMPLETED_RESPONSE")
    review_key = _required_text(response.get("review_key"), "review_key")
    if response.get("author") != "Arhan Canli":
        raise ValueError("the response author must be exactly Arhan Canli")
    packet = build_packet(registry_item(review_key))
    if response.get("packet_binding") != _packet_binding(packet):
        raise ValueError("response is not bound to the current immutable protocol packet")
    protocol = _verify_file_binding(
        response.get("protocol_binding"), packet["protocol_binding"], "protocol_binding"
    )
    evidence = _verify_file_binding(
        response.get("evidence_binding"), packet["evidence_binding"], "evidence_binding"
    )
    if response.get("activation_boundary") != packet["activation_boundary"]:
        raise ValueError("activation boundary changed from the authoritative packet")

    expected_questions = {item["id"]: item for item in packet["author_questions"]}
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

    expected_checks = {item["check"] for item in packet["technical_checks"]}
    checks = response.get("technical_checks")
    if (
        not isinstance(checks, list)
        or len(checks) != len(expected_checks)
        or {item.get("check") for item in checks} != expected_checks
    ):
        raise ValueError("all and only the governed technical checks are required")
    for check in checks:
        check_id = str(check["check"])
        if check.get("author_confirmed") is not True:
            raise ValueError(f"technical check {check_id} is not author-confirmed")
        _required_text(check.get("evidence"), f"technical check {check_id} evidence", 8)

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
        _required_text(ai.get("public_disclosure_text"), "public AI disclosure text", 30)
    elif systems:
        raise ValueError("AI systems cannot be named while AI assistance used is false")
    if ai.get("author_reviewed_every_retained_claim") is not True:
        raise ValueError("the author must review every retained claim")
    if ai.get("disclosure_approved_by_author") is not True:
        raise ValueError("the public AI disclosure is not approved by the author")

    approval = response.get("approval")
    if not isinstance(approval, dict):
        raise ValueError("approval must be an object")
    expected_decision = packet["activation_boundary"]["expected_approval_decision"]
    if approval.get("decision") != expected_decision:
        raise ValueError(f"only {expected_decision} produces this approval receipt")
    if approval.get("blocking_issues") != []:
        raise ValueError("an approved response cannot retain blocking issues")
    if approval.get("author_statement") != AUTHOR_STATEMENT:
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
    if approval.get("approved_protocol_sha256") != sha256_file(protocol):
        raise ValueError("approved protocol hash is not the current protocol")
    if approval.get("approved_evidence_sha256") != sha256_file(evidence):
        raise ValueError("approved evidence hash is not the current evidence artifact")
    if approval.get("approved_evidence_content_hash") != packet["evidence_binding"]["content_hash"]:
        raise ValueError("approved evidence content hash is not the current artifact")
    if approval.get("self_attested_by_author") is not True:
        raise ValueError("author self-attestation is required")

    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "status": "PASS_SELF_ATTESTED_AUTHOR_PROTOCOL_APPROVAL",
        "review_key": review_key,
        "family": packet["family"],
        "author": "Arhan Canli",
        "approval_date": approval_date,
        "approval_decision": expected_decision,
        "explicit_authorization_reference": authorization,
        "protocol": packet["protocol_binding"],
        "evidence": packet["evidence_binding"],
        "packet": _packet_binding(packet),
        "response_sha256": hashlib.sha256(canonical(response)).hexdigest(),
        "questions_answered": len(answers),
        "technical_checks_confirmed": len(checks),
        "ai_assistance_used": ai["used"],
        "ai_systems_disclosed": systems,
        "public_ai_disclosure_text": ai.get("public_disclosure_text"),
        "next_stage": packet["activation_boundary"]["next_stage"],
        "external_review_claimed": False,
        "publication_claimed": False,
        "identity_proof": "AUTHOR_SELF_ATTESTATION_NOT_INDEPENDENTLY_VERIFIED_BY_SOFTWARE",
        "claim_boundary": (
            "This receipt proves only that a structurally complete self-attested response matches "
            "the current repository hashes. Software cannot prove who typed it. It is not "
            "independent review, return evidence, sleeve admission, external submission, or "
            "publication acceptance."
        ),
    }
    receipt["content_hash"] = content_hash(receipt)
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
    prepare_parser.add_argument("--review-key", required=True)
    prepare_parser.add_argument("--output", type=Path, required=True)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--input", type=Path, required=True)
    verify_parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            document = prepare(str(args.review_key))
            _write_new(args.output, document)
            print(f"prepared blank author protocol response -> {args.output}")
            return 0
        response = _load_json(args.input)
        receipt = verify(response)
        if args.output is not None:
            _write_new(args.output, receipt)
            print(f"verified author protocol approval receipt -> {args.output}")
        else:
            print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except (FileExistsError, FileNotFoundError, KeyError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
