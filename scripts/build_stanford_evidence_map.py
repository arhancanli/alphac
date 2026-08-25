#!/usr/bin/env python3
"""Build a compact, source-bound Stanford CS portfolio evidence map."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
SOURCES: Final = {
    "admission_v7": ROOT / "config" / "admission_v7_promotion.json",
    "trial_packets": ROOT / "artifacts" / "research" / "trial_packet_manifest.json",
    "publication": ROOT / "artifacts" / "audit" / "external_publication_readiness.json",
    "all_sleeve_archives": (
        ROOT / "artifacts" / "publication" / "all_sleeve_review_archives.json"
    ),
    "source_rights": (
        ROOT / "artifacts" / "publication" / "all_sleeve_data_rights_audit.json"
    ),
    "clean_reproduction": (
        ROOT / "artifacts" / "publication" / "clean_workspace_reproduction_audit.json"
    ),
    "broker": ROOT / "artifacts" / "engineering" / "alpaca_broker_reconciliation.json",
    "forward": ROOT / "artifacts" / "engineering" / "forward_evidence_maturity.json",
    "mutation": ROOT / "artifacts" / "engineering" / "mutation_ledger.json",
    "legacy_closure": ROOT / "artifacts" / "research" / "legacy_research_epoch_closure.json",
    "prospective_trial": ROOT / "artifacts" / "research" / "crypto_carry_portable_v1_result.json",
}
OUTPUT: Final = ROOT / "artifacts" / "portfolio" / "stanford_cs_evidence_map.json"
MARKDOWN: Final = ROOT / "docs" / "design" / "STANFORD_CS_PORTFOLIO_EVIDENCE.md"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def build() -> dict[str, Any]:
    source = {key: json.loads(path.read_text()) for key, path in SOURCES.items()}
    trials = source["trial_packets"]["summary"]
    publication = source["publication"]
    archives = source["all_sleeve_archives"]
    source_rights = source["source_rights"]
    clean_reproduction = source["clean_reproduction"]
    broker = source["broker"]["summary"]
    forward = source["forward"]
    mutation = source["mutation"]
    closure = source["legacy_closure"]["summary"]
    prospective = source["prospective_trial"]
    objective = source["admission_v7"]["active_contract"]["objective"]

    activity = (
        "Built ALPHAC: 228 retired legacy identities, 1 prospective trial, broker evidence, "
        "corrections, and 16 checksum-bound papers."
    )
    if len(activity) > 150:
        raise RuntimeError("Activity description exceeds 150 characters")

    document: dict[str, Any] = {
        "schema": "canli.alphac-stanford-cs-evidence-map.v1",
        "applicant_and_project_author": "Arhan Canli",
        "status": "FACTUAL_PORTFOLIO_EVIDENCE_NOT_AN_ADMISSIONS_CLAIM",
        "one_sentence_thesis": (
            "Arhan Canli built ALPHAC to test whether quantitative-finance claims can be made "
            "publicly falsifiable through point-in-time data, complete trial accounting, "
            "broker reconciliation, deterministic evidence and visible corrections."
        ),
        "application_ready": {
            "activity_description_max_150_characters": activity,
            "activity_description_characters": len(activity),
            "short_description": (
                "Designed and implemented a quantitative-research and publication system spanning "
                "data engineering, statistical validation, paper execution, provenance, testing "
                "and public web interfaces. Published negative results and corrections alongside "
                "surviving hypotheses so every performance claim can be traced to evidence."
            ),
            "memorable_lesson": (
                "The project became stronger when its validation system disproved attractive "
                "results; the contribution is the machinery that makes those reversals visible."
            ),
        },
        "evidence": {
            "systems_and_provenance": {
                "claim": "Broker and publication claims are connected to hash-bound evidence.",
                "facts": {
                    "alpaca_sleeves_expected": broker["expected_alpaca_sleeves"],
                    "alpaca_sleeves_reconciled": broker["reconciled_alpaca_sleeves"],
                    "dedicated_accounts_unique": broker["unique_dedicated_accounts"],
                    "broker_reconciliation_passes": broker["passes"],
                    "publication_bundle_files": publication["bundle_files"],
                },
                "boundary": (
                    "Alpaca accounts are paper accounts; broker reconciliation is not funded "
                    "performance."
                ),
            },
            "statistical_judgment": {
                "claim": (
                    "Admission v7 separates incremental decisions from portfolio-maturity claims."
                ),
                "facts": {
                    "honest_forward_sharpe_target": objective["honest_forward_sharpe_target"],
                    "expected_maximum_drawdown_target": objective["portfolio_max_drawdown_target"],
                    "target_sleeves": objective["target_total_sleeves"],
                    "average_pairwise_correlation_objective": objective[
                        "average_pairwise_correlation_objective"
                    ],
                    "prospective_gate_audit_read_candidate_returns": source["admission_v7"][
                        "active_contract"
                    ]["gate_power_audit"]["candidate_return_artifacts_read"],
                },
                "boundary": (
                    "Targets are objectives, not achieved results; legacy trials cannot be "
                    "regraded."
                ),
            },
            "testing_and_correctness": {
                "claim": "Published-claim guards were mutation-tested with a negative control.",
                "facts": {
                    "guards_mutated": mutation["guards_mutated"],
                    "guards_not_yet_mutated": len(mutation["guards_not_yet_mutated"]),
                    "negative_controls": len(mutation["negative_controls"]),
                    "mutation_findings": len(mutation["findings"]),
                },
                "boundary": (
                    "Mutation coverage applies to the enumerated published-claim guards, not "
                    "every program path."
                ),
            },
            "research_governance": {
                "claim": (
                    "Every recorded legacy identity has a public packet and unresolved debt "
                    "remains visible."
                ),
                "facts": {
                    "legacy_hypothesis_identities": trials["distinct_hypothesis_identities"],
                    "prospective_hypothesis_identities": prospective["identity"][
                        "hypotheses_spent"
                    ],
                    "total_hypothesis_identities": (
                        trials["distinct_hypothesis_identities"]
                        + prospective["identity"]["hypotheses_spent"]
                    ),
                    "research_families": trials["distinct_research_families"],
                    "published_identity_packets": trials["published_identity_packets"],
                    "complete_packets": trials["complete_trial_packets"],
                    "incomplete_packets": trials["incomplete_trial_packets"],
                    "retired_identities": closure["retired_identities"],
                    "legacy_identities_eligible_for_admission": closure["eligible_for_admission"],
                    "prospective_trial_disposition": prospective["disposition"]["value"],
                    "prospective_trial_admitted": prospective["disposition"]["admitted"],
                },
                "boundary": (
                    "Publishing an incomplete packet does not make it complete or reproducible."
                ),
            },
            "scholarly_objects": {
                "claim": (
                    "Each sleeve has an authored archival research object and evidence bundle."
                ),
                "facts": {
                    "sleeve_papers": publication["current_sleeves"],
                    "pdf_pages_visually_inspected": publication["archival_pdf_pages"],
                    "released_exact_result_objects": publication["released_result_objects"],
                    "normalized_bibliographies": publication["normalized_bibliographies"],
                    "deterministic_review_archives": archives["counts"]["archives_passed"],
                    "raw_input_archive_members": archives["counts"]["raw_input_members"],
                    "source_mappings_complete": source_rights["counts"][
                        "source_mapping_complete"
                    ],
                    "data_license_reviews_complete": source_rights["counts"][
                        "data_license_reviews_complete"
                    ],
                    "full_clean_workspace_reproductions": clean_reproduction["counts"][
                        "full_clean_workspace_reproductions_completed"
                    ],
                    "portable_core_only_reproductions": clean_reproduction["counts"][
                        "portable_core_only_reproductions_completed"
                    ],
                    "portable_full_decision_reproductions": clean_reproduction["counts"][
                        "portable_full_decision_reproductions_completed"
                    ],
                    "upstream_strategy_curve_replays": clean_reproduction["counts"][
                        "upstream_strategy_curve_replays_completed"
                    ],
                    "independent_human_reproductions": clean_reproduction["counts"][
                        "independent_human_reproductions_completed"
                    ],
                },
                "boundary": (
                    "Archive integrity is not result replay or rights clearance; no DOI, external "
                    "submission, peer review or independent replication is claimed."
                ),
            },
            "forward_truth": {
                "claim": "The project refuses to infer success from an immature forward record.",
                "facts": {
                    "daily_return_observations": forward["record"]["daily_return_observations"],
                    "cumulative_return": forward["record"]["cumulative_return"],
                    "sharpe_status": forward["sharpe_evidence"].get(
                        "underlying_status", forward["sharpe_evidence"]["status"]
                    ),
                    "current_sleeves": forward["diversification_evidence"]["current_sleeves"],
                    "target_sleeves": forward["diversification_evidence"]["target_total_sleeves"],
                    "provenance_passes": forward["provenance_gate"]["passes"],
                },
                "boundary": (
                    "The forward Sharpe, drawdown and diversification objectives are not "
                    "established."
                ),
            },
        },
        "ninety_second_project_map": [
            "Question: can a quantitative claim be made independently falsifiable?",
            (
                "System: point-in-time inputs -> registered trial -> realistic simulation -> "
                "gate -> paper account -> signed evidence -> public paper."
            ),
            (
                "Decision quality: attractive results were corrected, killed or kept provisional "
                "when evidence failed."
            ),
            (
                "Public output: trial packets, papers, machine-readable artifacts, corrections "
                "and broker-separated paper evidence."
            ),
            (
                "Open burden: longer forward evidence, ten additional distinct sleeves, portable "
                "raw-input replay and independent review."
            ),
        ],
        "what_not_to_claim": [
            "funded or client performance",
            "a statistically established forward Sharpe",
            "peer review or repository acceptance",
            "independent replication",
            "Stanford endorsement",
            "that automation proves Arhan's unaided personal contribution",
        ],
        "source_bindings": {
            key: {"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)}
            for key, path in SOURCES.items()
        },
        "claim_boundary": (
            "This is a source-bound portfolio evidence map. It supports concise factual writing "
            "but does not prove admissions impact, external use, independent review or unaided "
            "authorship."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def _render(document: dict[str, Any]) -> str:
    evidence = document["evidence"]
    lines = [
        "# ALPHAC — Stanford CS portfolio evidence",
        "",
        "**Applicant and project author:** Arhan Canli  ",
        "**Status:** factual evidence map, not an admissions claim",
        "",
        document["one_sentence_thesis"],
        "",
        "## Application-ready core",
        "",
        (
            "**Activity description "
            f"({document['application_ready']['activity_description_characters']} characters):** "
            f"{document['application_ready']['activity_description_max_150_characters']}"
        ),
        "",
        document["application_ready"]["short_description"],
        "",
        f"**Memorable lesson:** {document['application_ready']['memorable_lesson']}",
        "",
        "## Evidence, not adjectives",
        "",
    ]
    for section in evidence.values():
        lines.extend([f"### {section['claim']}", ""])
        for key, value in section["facts"].items():
            lines.append(f"- `{key}`: {value}")
        lines.extend(["", f"Boundary: {section['boundary']}", ""])
    lines.extend(["## Ninety-second project map", ""])
    lines.extend(
        f"{index}. {item}" for index, item in enumerate(document["ninety_second_project_map"], 1)
    )
    lines.extend(["", "## Claims deliberately excluded", ""])
    lines.extend(f"- {item}" for item in document["what_not_to_claim"])
    lines.extend(["", document["claim_boundary"], ""])
    return "\n".join(lines)


def main() -> None:
    document = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    MARKDOWN.write_text(_render(document))
    print(f"wrote {OUTPUT}")
    print(f"content_hash: {document['content_hash']}")


if __name__ == "__main__":
    main()
