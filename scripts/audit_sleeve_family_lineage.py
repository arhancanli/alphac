#!/usr/bin/env python3
"""Verify the ALPHAC atlas lineage registry against authoritative local ledgers."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).parents[1]
REGISTRY: Final = ROOT / "config" / "sleeve_family_lineage.json"
DISCOVERY: Final = ROOT / "config" / "sleeve_discovery.json"
CURRENT_BOOK: Final = ROOT.parent / "meridian" / "public" / "paper-state.json"
KILL_LEDGER: Final = (
    ROOT.parent / "meridian" / "public" / "glassbox" / "kill_log.json"
)
OUT: Final = ROOT / "artifacts" / "discovery" / "sleeve_family_lineage_audit.json"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _kill_names(kill_log: dict[str, Any]) -> set[str]:
    sections = ("killed_strategies", "screen_stage_kills")
    return {
        str(row["name"])
        for section in sections
        for row in kill_log.get(section, [])
        if row.get("name")
    }


def _current_ids(paper_state: dict[str, Any]) -> set[str]:
    return {
        str(row["key"])
        for row in paper_state.get("book", {}).get("sleeves", [])
        if row.get("key")
    }


def _candidate_ids(discovery: dict[str, Any]) -> set[str]:
    return {
        str(row["id"])
        for row in discovery.get("candidates", [])
        if row.get("id")
    }


def _feasibility_review_ids(discovery: dict[str, Any]) -> set[str]:
    return {
        str(row["id"])
        for row in discovery.get("feasibility_reviews", [])
        if row.get("id")
    }


def evidence_resolves(
    reference: str,
    *,
    root: Path,
    kill_names: set[str],
    candidate_ids: set[str],
    feasibility_review_ids: set[str],
) -> bool:
    if reference.startswith("public_kill_ledger#screen_stage_kills:"):
        return reference.rsplit(":", 1)[-1] in kill_names
    if reference.startswith("config/sleeve_discovery.json#candidates:"):
        return reference.rsplit(":", 1)[-1] in candidate_ids
    if reference.startswith("config/sleeve_discovery.json#feasibility_reviews:"):
        return reference.rsplit(":", 1)[-1] in feasibility_review_ids
    return (root / reference).is_file()


def audit_lineage(
    registry: dict[str, Any],
    kill_log: dict[str, Any],
    paper_state: dict[str, Any],
    discovery: dict[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    kill_names = _kill_names(kill_log)
    current_ids = _current_ids(paper_state)
    candidate_ids = _candidate_ids(discovery)
    feasibility_review_ids = _feasibility_review_ids(discovery)
    registered_current = {str(row["id"]) for row in registry["current_sleeves"]}
    family_results: list[dict[str, Any]] = []

    for family_id, record in sorted(registry["families"].items()):
        classification = str(record["classification"])
        aliases = [str(alias) for alias in record.get("aliases", [])]
        evidence = [str(item) for item in record.get("evidence", [])]
        direct_outcome = record.get("return_outcome")
        has_direct_outcome = isinstance(direct_outcome, dict)
        alias_required = (
            classification in {"RETIRED_KILLED", "DUPLICATE_OVERLAP"}
            and not has_direct_outcome
        )
        direct_outcome_valid = not has_direct_outcome or (
            classification == "RETIRED_KILLED"
            and direct_outcome.get("return_data_opened") is True
            and int(direct_outcome.get("return_hypotheses_spent", 0)) >= 1
            and direct_outcome.get("verdict") == "KILL"
            and direct_outcome.get("technically_eligible") is False
            and isinstance(direct_outcome.get("return_identity_id"), str)
            and len(direct_outcome["return_identity_id"]) >= 3
            and evidence_resolves(
                str(direct_outcome.get("result", "")),
                root=root,
                kill_names=kill_names,
                candidate_ids=candidate_ids,
                feasibility_review_ids=feasibility_review_ids,
            )
        )
        gates = {
            "aliases_required_when_historical": not alias_required or bool(aliases),
            "historical_aliases_exist_in_kill_ledger": not alias_required
            or all(alias in kill_names for alias in aliases),
            "evidence_declared_when_non_novel": classification == "NOVEL_ATLAS"
            or bool(evidence),
            "evidence_resolves": all(
                evidence_resolves(
                    item,
                    root=root,
                    kill_names=kill_names,
                    candidate_ids=candidate_ids,
                    feasibility_review_ids=feasibility_review_ids,
                )
                for item in evidence
            ),
            "novel_family_has_no_historical_alias": classification != "NOVEL_ATLAS"
            or not aliases,
            "forward_experiment_is_explicit": "forward_experiment" not in record
            or record["forward_experiment"].get("status") == "FORWARD_ONLY",
            "direct_return_outcome_valid": direct_outcome_valid,
        }
        family_results.append(
            {
                "family_id": family_id,
                "classification": classification,
                "aliases": aliases,
                "evidence": evidence,
                "gates": gates,
                "pass": all(gates.values()),
            }
        )

    current_gate = registered_current == current_ids
    failed = [row["family_id"] for row in family_results if not row["pass"]]
    classifications = Counter(row["classification"] for row in family_results)
    unresolved_kill_names = sorted(
        kill_names
        - {
            alias
            for row in registry["families"].values()
            for alias in row.get("aliases", [])
        }
    )
    family_return_outcomes = [
        record["return_outcome"]
        for record in registry["families"].values()
        if isinstance(record.get("return_outcome"), dict)
    ]
    return {
        "schema": "canli.alphac-sleeve-family-lineage-audit.v1",
        "stage": "NO_RETURN_IDENTITY_LINEAGE",
        "claim_boundary": (
            "This audit proves registry consistency against the enumerated internal ledgers. "
            "It does not prove global economic novelty, returns, or sleeve admission."
        ),
        "summary": {
            "decision": "PASS" if current_gate and not failed else "FAIL_CLOSED",
            "families_audited": len(family_results),
            "family_failures": len(failed),
            "current_book_exact_match": current_gate,
            "current_sleeves": len(current_ids),
            "kill_ledger_identities": len(kill_names),
            "kill_identities_mapped_to_atlas": len(kill_names) - len(unresolved_kill_names),
            "kill_identities_outside_atlas": len(unresolved_kill_names),
            "classifications": dict(sorted(classifications.items())),
            "return_data_opened": 0,
            "return_hypotheses_spent": 0,
            "family_return_data_opened": sum(
                bool(outcome.get("return_data_opened"))
                for outcome in family_return_outcomes
            ),
            "family_return_hypotheses_spent": sum(
                int(outcome.get("return_hypotheses_spent", 0))
                for outcome in family_return_outcomes
            ),
        },
        "failed_families": failed,
        "current_book": {
            "actual": sorted(current_ids),
            "registered": sorted(registered_current),
        },
        "unmapped_kill_identities": unresolved_kill_names,
        "family_results": family_results,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    paths = {
        "registry": Path(args.registry),
        "kill_ledger": Path(args.kill_ledger),
        "current_book": Path(args.current_book),
        "discovery": Path(args.discovery),
    }
    payload = audit_lineage(
        json.loads(paths["registry"].read_text()),
        json.loads(paths["kill_ledger"].read_text()),
        json.loads(paths["current_book"].read_text()),
        json.loads(paths["discovery"].read_text()),
    )
    payload["source_sha256"] = {
        name: file_sha256(path) for name, path in paths.items()
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["content_hash"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    payload["generated_at"] = datetime.now(UTC).isoformat()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default=str(REGISTRY))
    parser.add_argument("--kill-ledger", default=str(KILL_LEDGER))
    parser.add_argument("--current-book", default=str(CURRENT_BOOK))
    parser.add_argument("--discovery", default=str(DISCOVERY))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    payload = run(args)
    print(json.dumps({**payload["summary"], "content_hash": payload["content_hash"]}, indent=2))
    return 0 if payload["summary"]["decision"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
