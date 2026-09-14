#!/usr/bin/env python3
"""Bring the 118 externally measured identities' packets home, each with a decided closure.

WHY. On 2026-09-14 the trial-accounting reconciliation imported 52 experiment ledgers from the
second checkout (~/alphac-prospective-pause-20260911) so the union counted every identity the
autonomous research session had measured (config/trial_accounting_reviews.json,
external_ledger_reconciliation). It imported the ledgers, not the packets. The seriality guard
(alphaforge.validation.trial_reservation._validate_forward_epoch_serial_completion) then blocks
every new reservation, correctly: 118 forward-epoch identities exist in the ledgers with no
packet and no decision in the canonical tree, and an undecided identity is exactly what the
guard exists to stop a new one from walking past.

Each of those identities was reserved, run and retired IN THAT TREE: its packet is complete
(every section evidenced) and its study's development closure records
REJECT_UNDER_FROZEN_SCENARIO with admitted false. This script copies each packet (content hash
verified), copies any evidence file the packet binds that is not yet in the canonical tree (hash
verified against the packet's binding), writes one canonical admission closure per identity that
binds the study's development closure and states the disposition in the vocabulary the guard
reads (KILL: rejected under its frozen scenario, never admitted, never regradable), appends that
closure to the packet's admission_or_kill_decision evidence, and re-seals the packet's content
hash. It reads no return and changes no ledger; the union count is unchanged.

Owner authorization: the delegation of 2026-09-14 ("full permission for the activations") and
the goals document's rule that this direction "does not retroactively admit rejected
candidates". A KILL here is what the study already said.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Final

REPO: Final[Path] = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from alphaforge.validation.experiments import ExperimentLog  # noqa: E402
from alphaforge.validation.trial_reservation import (  # noqa: E402
    IDENTITY_PACKET_DIR,
    LEGACY_EPOCH_CLOSURE,
    _observed_content_hash,
)

EXTERNAL_TREE: Final[Path] = Path(os.path.expanduser("~/alphac-prospective-pause-20260911"))
CLOSURE_DIR: Final[Path] = Path("artifacts") / "research" / "development_closures"
REVIEWS: Final[Path] = Path("config") / "trial_accounting_reviews.json"
CLOSURE_SCHEMA: Final[str] = "canli.alphac-development-trial-admission-closure.v1"
PACKET_SCHEMA: Final[str] = "canli.alphac-identity-trial-packet.v2"
# The study's own verdict, when a development closure exists beside the reservation, and the
# packet's own statement otherwise ("Full admission evaluation is INCOMPLETE_NOT_ADMITTED" on
# every one of them). Every mapped disposition is KILL in the admission vocabulary: a
# retrospective development measurement on inspected history can never be admitted as it is,
# because the contract admits only untouched out-of-sample evidence; a construction the study
# asked to retain is retained for a NEW identity, and this one is spent and final.
DISPOSITION_MAP: Final[dict[str, str]] = {
    "REJECT_UNDER_FROZEN_SCENARIO": "KILL",
    "RETAIN_FOR_FURTHER_TESTING": "KILL",
    "PACKET_STATEMENT_NOT_ADMITTED": "KILL",
    "PACKET_STATEMENT_RETROSPECTIVE_DEVELOPMENT_MEASUREMENT": "KILL",
}
# Every imported packet's own decision statement must say, in one of the phrasings the external
# session used, either that the identity was not admitted or that the measurement was a
# retrospective, known-history or development one (which the contract can never admit as it is:
# it admits untouched out-of-sample evidence only). A packet that says neither is refused.
NOT_ADMITTED: Final[re.Pattern[str]] = re.compile(
    r"INCOMPLETE_NOT_ADMITTED|no admission|not admitted|NOT_ADMITTED|never admitted|"
    r"\bREJECT\b|fails required|\bfailed\b|retire|\bkill",
    re.I,
)
RETROSPECTIVE: Final[re.Pattern[str]] = re.compile(
    r"retrospective|known-history|inspected history|not untouched OOS|development comparison|"
    r"development experiment|\bdiagnostic\b|accounting only",
    re.I,
)
AUTHORIZATION: Final[str] = (
    "Arhan Canli, owner, 2026-09-14: 'i give you full permision for the activiations so you can "
    "go ahead'; docs/design/ALPHAC_OWNER_GOALS_2026-09-12.md: this direction does not "
    "retroactively admit rejected candidates."
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def forward_identities_without_packets(repo: Path = REPO) -> list[str]:
    """Forward-epoch identities (not in the legacy closure) whose packet is absent here."""
    legacy: set[str] = set()
    closure_path = repo / LEGACY_EPOCH_CLOSURE
    if closure_path.is_file():
        legacy = {
            str(item.get("hypothesis_key"))
            for item in json.loads(closure_path.read_text(encoding="utf-8")).get("identities", [])
            if isinstance(item, dict)
        }
    first: dict[str, tuple[int, str]] = {}
    for ledger_path in sorted(
        {*repo.glob("var*/experiments.jsonl"), *repo.glob("artifacts/**/experiments.jsonl")}
    ):
        if any("archive" in part.casefold() for part in ledger_path.relative_to(repo).parts):
            continue
        ledger = ExperimentLog(ledger_path)
        for record in ledger.all():
            key = ledger._hypothesis_key(record.config)
            if key in legacy:
                continue
            ordering = (record.now_ms, record.config_hash)
            if key not in first or ordering < first[key]:
                first[key] = ordering
    ordered = [key for key, _ in sorted(first.items(), key=lambda item: (*item[1], item[0]))]
    return [key for key in ordered if not (repo / IDENTITY_PACKET_DIR / f"{key}.json").is_file()]


def _evidence_paths(packet: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for section in packet.get("required_sections", {}).values():
        for item in section.get("evidence", []) or []:
            if isinstance(item, dict) and (item.get("path") or item.get("source_path")):
                out.append(item)
    return out


def _study_closure_for(
    packet: dict[str, Any], external: Path
) -> tuple[Path | None, dict[str, Any] | None]:
    """The study's own development closure beside the reservation the packet binds, if any."""
    for item in _evidence_paths(packet):
        path = str(item.get("path") or item.get("source_path"))
        if path.endswith("/reservation.json"):
            candidate = external / path.rsplit("/", 1)[0] / "development_closure.json"
            if candidate.is_file():
                return candidate, json.loads(candidate.read_text(encoding="utf-8"))
    return None, None


def import_identity(key: str, *, external: Path, repo: Path, imported_on: str) -> dict[str, Any]:
    source = external / IDENTITY_PACKET_DIR / f"{key}.json"
    if not source.is_file():
        raise ValueError(f"{key}: no packet in the external tree")
    packet = json.loads(source.read_text(encoding="utf-8"))
    if packet.get("schema") != PACKET_SCHEMA or packet.get("hypothesis_key") != key:
        raise ValueError(f"{key}: external packet schema or key mismatch")
    if packet.get("content_hash") != _observed_content_hash(packet):
        raise ValueError(f"{key}: external packet content hash mismatch")
    if packet.get("complete") is not True or packet.get("missing_sections"):
        raise ValueError(
            f"{key}: external packet is not complete; it cannot be imported as decided"
        )
    copied: list[str] = []
    for item in _evidence_paths(packet):
        relative = str(item.get("path") or item.get("source_path"))
        here = repo / relative
        there = external / relative
        claimed = item.get("sha256")
        if here.is_file():
            if claimed and _sha256(here) != claimed:
                raise ValueError(f"{key}: evidence differs between trees: {relative}")
            continue
        if not there.is_file():
            raise ValueError(f"{key}: bound evidence missing in both trees: {relative}")
        if claimed and _sha256(there) != claimed:
            raise ValueError(f"{key}: external evidence does not match its binding: {relative}")
        here.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(there, here)
        copied.append(relative)
    decision_section = packet["required_sections"]["admission_or_kill_decision"]
    statement = str(decision_section.get("statement") or "")
    if NOT_ADMITTED.search(statement) is not None:
        basis = "PACKET_STATEMENT_NOT_ADMITTED"
    elif RETROSPECTIVE.search(statement) is not None:
        basis = "PACKET_STATEMENT_RETROSPECTIVE_DEVELOPMENT_MEASUREMENT"
    else:
        raise ValueError(
            f"{key}: packet statement says neither not-admitted nor retrospective: {statement!r}"
        )
    study_closure_path, study_closure = _study_closure_for(packet, external)
    study_binding: dict[str, Any] | None = None
    external_disposition = basis
    if study_closure is not None and study_closure_path is not None:
        named = study_closure.get("hypothesis_identity")
        if named not in (None, key) or study_closure.get("admitted") is True:
            raise ValueError(f"{key}: development closure does not retire this identity")
        external_disposition = str(study_closure.get("disposition"))
        if external_disposition not in DISPOSITION_MAP:
            raise ValueError(f"{key}: development disposition not mapped: {external_disposition}")
        study_closure_relative = str(study_closure_path.relative_to(external))
        here_study = repo / study_closure_relative
        if not here_study.is_file():
            here_study.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(study_closure_path, here_study)
            copied.append(study_closure_relative)
        study_binding = {
            "path": study_closure_relative,
            "sha256": _sha256(here_study),
            "schema": study_closure.get("schema"),
            "disposition": external_disposition,
        }
    closure: dict[str, Any] = {
        "schema": CLOSURE_SCHEMA,
        "author": "Arhan Canli",
        "imported_on": imported_on,
        "status": "FINAL_DEVELOPMENT_TRIAL_KILLED_NOT_ADMITTED",
        "identity": {
            "hypothesis_key": key,
            "config_hash": packet.get("config_hash"),
            "family_trial_account": packet.get("research_family_key"),
            "label": packet.get("label"),
        },
        "decision": {
            "disposition": DISPOSITION_MAP[external_disposition],
            "external_disposition": external_disposition,
            "admitted": False,
            "killed": True,
            "final_for_admission": True,
            "identity_may_be_regraded_later": False,
            "technically_eligible": False,
            "statement": statement,
            "construction_retained_for_a_new_identity": (
                external_disposition == "RETAIN_FOR_FURTHER_TESTING"
            ),
            "mapping": (
                "The packet's own statement is that full admission evaluation is "
                "INCOMPLETE_NOT_ADMITTED: a retrospective development measurement on inspected "
                "history, which the admission contract can never admit as it is. In the "
                "admission vocabulary the guard reads that is KILL for THIS identity: not "
                "admitted, final, never regradable. A construction the study asked to retain "
                "is retained for a new identity under a v2 reservation; nothing here softens "
                "a gate or evaluates one."
            ),
        },
        "lineage": {
            "external_tree": str(EXTERNAL_TREE),
            "external_packet_sha256": _sha256(source),
            "external_packet_content_hash": packet["content_hash"],
            "study_development_closure": study_binding,
            "decision_evidence": decision_section.get("evidence", []),
        },
        "authorization": AUTHORIZATION,
        "claim_boundary": (
            "A closure records a decision already made by the study that ran the identity; it "
            "computes nothing, reads no return, and cannot admit anything. Its purpose is "
            "seriality: an identity with a decided closure no longer blocks the next reservation."
        ),
    }
    closure["content_hash"] = _observed_content_hash(closure)
    closure_path = repo / CLOSURE_DIR / f"{key}_admission_closure.json"
    closure_path.parent.mkdir(parents=True, exist_ok=True)
    closure_path.write_text(json.dumps(closure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    decision_section.setdefault("evidence", []).append(
        {
            "path": str(closure_path.relative_to(repo)),
            "sha256": _sha256(closure_path),
            "content_hash": closure["content_hash"],
            "type": "final_development_admission_closure",
        }
    )
    decision_section["status"] = "VERIFIED_FINAL_DEVELOPMENT_CLOSURE_KILL"
    packet["packet_status"] = "COMPLETE_ACCOUNTING_FINAL_KILLED_NOT_ADMITTED"
    packet["imported_from_external_tree"] = {
        "tree": str(EXTERNAL_TREE),
        "imported_on": imported_on,
        "external_content_hash": closure["lineage"]["external_packet_content_hash"],
    }
    packet["content_hash"] = _observed_content_hash(packet)
    target = repo / IDENTITY_PACKET_DIR / f"{key}.json"
    target.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "hypothesis_key": key,
        "family": packet.get("research_family_key"),
        "disposition": DISPOSITION_MAP[external_disposition],
        "closure": str(closure_path.relative_to(repo)),
        "packet": str(target.relative_to(repo)),
        "evidence_files_copied": len(copied),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--external", type=Path, default=EXTERNAL_TREE)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    keys = forward_identities_without_packets(repo)
    print(f"forward identities without a canonical packet: {len(keys)}")
    if args.dry_run or not keys:
        return 0
    imported_on = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    rows = [
        import_identity(k, external=args.external, repo=repo, imported_on=imported_on) for k in keys
    ]
    remaining = forward_identities_without_packets(repo)
    reviews_path = repo / REVIEWS
    reviews = json.loads(reviews_path.read_text(encoding="utf-8"))
    reviews.setdefault("external_packet_import", []).append(
        {
            "imported_on": imported_on,
            "script": "scripts/import_external_identity_packets.py",
            "identities_imported": len(rows),
            "closures_written": len(rows),
            "dispositions": sorted({r["disposition"] for r in rows}),
            "families": sorted({str(r["family"]) for r in rows}),
            "evidence_files_copied": sum(r["evidence_files_copied"] for r in rows),
            "remaining_forward_identities_without_packet": len(remaining),
            "union_count_changed": False,
            "authorization": AUTHORIZATION,
        }
    )
    reviews_path.write_text(
        json.dumps(reviews, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "imported": len(rows),
                "remaining_without_packet": len(remaining),
                "families": sorted({str(r["family"]) for r in rows}),
                "evidence_files_copied": sum(r["evidence_files_copied"] for r in rows),
            },
            indent=2,
        )
    )
    return 0 if not remaining else 1


if __name__ == "__main__":
    sys.exit(main())
