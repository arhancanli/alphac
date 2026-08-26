#!/usr/bin/env python3
"""Build blank, hash-bound author review packets for approval-gated protocols."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Final, cast

ROOT: Final = Path(__file__).resolve().parents[1]
REGISTRY: Final = ROOT / "config" / "author_protocol_review_registry.json"
OUTPUT_ROOT: Final = ROOT / "artifacts" / "governance" / "author_protocol_review_packets"
OUTPUT: Final = ROOT / "artifacts" / "governance" / "author_protocol_review_packets.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(canonical(body)).hexdigest()}"


def load_registry() -> dict[str, Any]:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if (
        registry.get("schema") != "canli.alphac-author-protocol-review-registry.v1"
        or registry.get("author") != "Arhan Canli"
        or registry.get("automation_may_invent_answers_or_approval") is not False
    ):
        raise ValueError("author protocol review registry is invalid")
    reviews = registry.get("reviews")
    if not isinstance(reviews, list) or not reviews:
        raise ValueError("author protocol review registry has no reviews")
    keys = [item.get("key") for item in reviews if isinstance(item, dict)]
    if len(keys) != len(reviews) or len(keys) != len(set(keys)):
        raise ValueError("author protocol review keys must be unique")
    return cast(dict[str, Any], registry)


def registry_item(review_key: str) -> dict[str, Any]:
    matches = [item for item in load_registry()["reviews"] if item["key"] == review_key]
    if len(matches) != 1:
        raise ValueError(f"review key {review_key!r} is not uniquely registered")
    return cast(dict[str, Any], matches[0])


def _bound_sources(item: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    protocol = (ROOT / str(item["protocol"])).resolve()
    artifact_path = (ROOT / str(item["evidence_artifact"])).resolve()
    for path in (protocol, artifact_path):
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise FileNotFoundError(path)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    if artifact.get("content_hash") != content_hash(artifact):
        raise ValueError(f"evidence artifact does not self-verify: {artifact_path}")
    if artifact.get("content_hash") != item.get("evidence_content_hash"):
        raise ValueError(f"registered evidence hash is stale: {item['key']}")
    if artifact.get("decision") != "AUTHOR_APPROVAL_REQUIRED":
        raise ValueError(f"protocol is not currently approval-gated: {item['key']}")
    if artifact.get("return_data_opened") is not False:
        raise ValueError(f"return boundary is already open: {item['key']}")
    return protocol, artifact_path, cast(dict[str, Any], artifact)


def build_packet(item: dict[str, Any]) -> dict[str, Any]:
    protocol, artifact_path, artifact = _bound_sources(item)
    packet: dict[str, Any] = {
        "schema": "canli.alphac-author-protocol-review-packet.v1",
        "status": "AWAITING_ARHAN_REVIEW_NO_APPROVAL_CLAIMED",
        "review_key": item["key"],
        "family": item["family"],
        "title": item["title"],
        "author": "Arhan Canli",
        "protocol_binding": {
            "path": str(protocol.relative_to(ROOT)),
            "sha256": sha256_file(protocol),
        },
        "evidence_binding": {
            "path": str(artifact_path.relative_to(ROOT)),
            "sha256": sha256_file(artifact_path),
            "content_hash": artifact["content_hash"],
            "technical_decision": artifact["technical_decision"],
            "governance_decision": artifact["governance_decision"],
        },
        "activation_boundary": {
            "expected_approval_decision": item["expected_approval_decision"],
            "next_stage": item["next_stage"],
            "approval_recorded": False,
            "next_stage_authorized": False,
            "return_data_opened": False,
            "return_hypotheses_spent": 0,
        },
        "author_questions": [
            {
                "id": question["id"],
                "prompt": question["prompt"],
                "answer": None,
                "answered_by": None,
                "approved_by_author": False,
            }
            for question in item["author_questions"]
        ],
        "technical_checks": [
            {"check": check, "author_confirmed": None, "evidence": None}
            for check in item["technical_checks"]
        ],
        "ai_assistance": {
            "used": None,
            "systems": [],
            "scope": None,
            "public_disclosure_text": None,
            "author_reviewed_every_retained_claim": False,
            "disclosure_approved_by_author": False,
        },
        "approval": {
            "decision": None,
            "blocking_issues": [],
            "author_statement": None,
            "explicit_authorization_reference": None,
            "approval_date": None,
            "approved_protocol_sha256": None,
            "approved_evidence_sha256": None,
            "approved_evidence_content_hash": None,
            "self_attested_by_author": False,
        },
        "answers_completed": 0,
        "technical_checks_confirmed": 0,
        "author_approval_claimed": False,
        "external_review_claimed": False,
        "identity_proof_claimed": False,
        "claim_boundary": (
            "Automation populated source bindings, governed questions, and blank checks only. "
            "This packet proves no author answer, approval, identity, corpus authorization, return "
            "authorization, external review, or publication acceptance."
        ),
    }
    packet["content_hash"] = content_hash(packet)
    return packet


def markdown(packet: dict[str, Any]) -> str:
    questions = "\n\n".join(
        f"### {index}. {question['prompt']}\n\n`[Arhan's answer required]`"
        for index, question in enumerate(packet["author_questions"], start=1)
    )
    checks = "\n".join(
        f"- [ ] `{item['check']}`: Arhan's evidence and confirmation required"
        for item in packet["technical_checks"]
    )
    boundary = packet["activation_boundary"]
    return f"""# Protocol review: {packet['title']}

- **Author and reviewer:** Arhan Canli
- **Status:** awaiting Arhan's review; no approval claimed
- **Protocol SHA-256:** `{packet['protocol_binding']['sha256']}`
- **Evidence SHA-256:** `{packet['evidence_binding']['sha256']}`
- **Evidence content hash:** `{packet['evidence_binding']['content_hash']}`
- **Required decision:** `{boundary['expected_approval_decision']}`

## What approval would authorize

{boundary['next_stage']}

It would not prove alpha, admit a sleeve, establish Sharpe or drawdown, constitute independent
review, or authorize any external submission.

## Arhan's technical account

These answers must be written and approved by Arhan. Automation may not invent, paraphrase, or
approve them.

{questions}

## Technical checks

{checks}

## AI-assistance disclosure

Arhan must identify every system used, describe its scope, approve the public disclosure text, and
confirm that he personally reviewed every retained claim.

## Approval

- **Decision:** `[required exact governed decision / REVISION_REQUIRED / WITHDRAWN]`
- **Blocking issues:** `[required]`
- **Author responsibility statement:** `[required]`
- **Explicit authorization reference:** `[required]`

This blank packet proves no author answer, approval, identity, external review, or authorization.
"""


def generate(out_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    registry = load_registry()
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)
    records: list[dict[str, Any]] = []
    for item in registry["reviews"]:
        packet = build_packet(item)
        destination = out_root / item["key"]
        destination.mkdir()
        json_path = destination / "review_packet.json"
        markdown_path = destination / "REVIEW.md"
        json_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        markdown_path.write_text(markdown(packet), encoding="utf-8")
        records.append(
            {
                "review_key": item["key"],
                "family": item["family"],
                "status": packet["status"],
                "packet": str(json_path.relative_to(out_root)),
                "packet_sha256": sha256_file(json_path),
                "packet_content_hash": packet["content_hash"],
                "markdown": str(markdown_path.relative_to(out_root)),
                "markdown_sha256": sha256_file(markdown_path),
                "questions": len(packet["author_questions"]),
                "answers_completed": 0,
                "technical_checks": len(packet["technical_checks"]),
                "technical_checks_confirmed": 0,
                "approved": False,
            }
        )
    manifest: dict[str, Any] = {
        "schema": "canli.alphac-author-protocol-review-packet-manifest.v1",
        "status": "PASS_BLANK_PROTOCOL_PACKETS_ZERO_AUTHOR_APPROVALS",
        "author": "Arhan Canli",
        "packets": len(records),
        "questions": sum(record["questions"] for record in records),
        "answers_completed": 0,
        "technical_checks": sum(record["technical_checks"] for record in records),
        "technical_checks_confirmed": 0,
        "author_approvals": 0,
        "records": records,
        "source_bindings": {
            "registry": {
                "path": str(REGISTRY.relative_to(ROOT)),
                "sha256": sha256_file(REGISTRY),
            },
            "builder": {
                "path": str(Path(__file__).resolve().relative_to(ROOT)),
                "sha256": sha256_file(Path(__file__).resolve()),
            },
        },
        "claim_boundary": (
            "These are blank hash-bound protocol review packets. They prove no author answers, "
            "approval, identity, next-stage authorization, external review, or publication."
        ),
    }
    manifest["content_hash"] = content_hash(manifest)
    return manifest


def main() -> int:
    manifest = generate()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{manifest['status']}: {manifest['packets']} packets")
    print(f"content_hash: {manifest['content_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
