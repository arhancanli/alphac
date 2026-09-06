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
    "submission_worksheets": (
        ROOT / "artifacts" / "publication" / "repository_submission_worksheets.json"
    ),
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
    "external_review": ROOT / "artifacts" / "publication" / "external_reviewer_packets.json",
    "external_review_protocol": ROOT / "config" / "external_review_protocol.json",
    "foundry_deployment": ROOT / "config" / "foundry_deployment_manifest.json",
}
BINDING_ONLY_SOURCES: Final = {
    "publication_standard": ROOT / "docs" / "design" / "EXTERNAL_RESEARCH_PUBLICATION_STANDARD.md",
    "governing_plan": (
        ROOT
        / "docs"
        / "design"
        / "CANLI_CAPITAL_PRODUCT_FOUNDRY_AND_AUTHORITY_PLAN_2026_08_26.md"
    ),
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
    submission_worksheets = source["submission_worksheets"]
    archives = source["all_sleeve_archives"]
    source_rights = source["source_rights"]
    clean_reproduction = source["clean_reproduction"]
    broker = source["broker"]["summary"]
    forward = source["forward"]
    mutation = source["mutation"]
    closure = source["legacy_closure"]["summary"]
    prospective = source["prospective_trial"]
    external_review = source["external_review"]
    external_review_protocol = source["external_review_protocol"]
    foundry_deployment = source["foundry_deployment"]
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
        "contribution_map": {
            "status": "SELF_DISCLOSED_SOURCE_BOUND_NOT_INDEPENDENTLY_ATTESTED",
            "arhan_canli": {
                "role": (
                    "Founder, named author, project owner and final accountable human for "
                    "methodology, claims, corrections and publication decisions."
                ),
                "responsibilities": [
                    "sets the project direction and accepts responsibility for what is published",
                    "must personally approve author answers and manuscript-specific claims",
                    "controls external submissions and responses to reviewers",
                    "must be able to explain and defend every major research and system decision",
                ],
                "credit_boundary": (
                    "Named authorship records responsibility. It does not prove that Arhan typed "
                    "every line without assistance."
                ),
            },
            "ai_assisted_tooling": {
                "role": (
                    "Reviewed development assistance across implementation, testing, technical "
                    "drafting, publication preparation and quality assurance."
                ),
                "not_permitted_to_claim": [
                    "authorship",
                    "independent review",
                    "author approval",
                    "scientific judgment independent of Arhan",
                ],
                "venue_disclosure_required": external_review_protocol["authorship_policy"][
                    "venue_specific_ai_disclosure_required"
                ],
            },
            "libraries_services_and_data": {
                "role": (
                    "Open-source software, market-data providers, Alpaca paper accounts, "
                    "DigitalOcean and web infrastructure supply capabilities and inputs."
                ),
                "credit_boundary": (
                    "Their use is not evidence that they endorse, reviewed or validated ALPHAC."
                ),
            },
            "external_validation": {
                "assigned_reviewers": external_review["assigned_reviewers"],
                "completed_reviews": external_review["completed_reviews"],
                "independent_replications": external_review_protocol["current_counts"][
                    "independent_replications"
                ],
                "boundary": external_review["claim_boundary"],
            },
            "not_established": [
                "unaided authorship",
                "line-by-line historical attribution",
                "independent confirmation of the contribution map",
                "external adoption or admissions impact",
            ],
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
                    "sleeve_papers": submission_worksheets["counts"]["sleeve_papers"],
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
                    "public_terms_reviews_complete": source_rights["counts"][
                        "public_terms_reviews_complete"
                    ],
                    "external_publication_clearances_complete": source_rights["counts"][
                        "external_publication_clearances_complete"
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
        "ninety_second_walkthrough": {
            "total_seconds": 90,
            "status": "SCRIPT_AND_SHOT_MAP_READY_VIDEO_NOT_RECORDED",
            "chapters": [
                {
                    "start_second": 0,
                    "end_second": 12,
                    "label": "The question",
                    "screen": "/founder#walkthrough",
                    "narration": (
                        "Most quant projects publish the winning curve. I wanted to know whether "
                        "the evidence could stay public even when it proved me wrong."
                    ),
                },
                {
                    "start_second": 12,
                    "end_second": 28,
                    "label": "Freeze the attempt",
                    "screen": "/trials",
                    "narration": (
                        "ALPHAC records every attempt before judging it. The public union now "
                        f"contains {trials['distinct_hypothesis_identities']} legacy identities "
                        f"and one prospective identity, including failures and incomplete packets."
                    ),
                },
                {
                    "start_second": 28,
                    "end_second": 45,
                    "label": "Keep the reversal",
                    "screen": "/progress",
                    "narration": (
                        "When a flattering result breaks, the system keeps the original claim, "
                        "the defect, the correction and the test that prevents the same mistake."
                    ),
                },
                {
                    "start_second": 45,
                    "end_second": 61,
                    "label": "Observe the broker",
                    "screen": "/measurements/alpaca-broker-reconciliation",
                    "narration": (
                        "Three dedicated Alpaca paper accounts reconcile against the published "
                        "record. They contain no client capital and prove no funded performance."
                    ),
                },
                {
                    "start_second": 61,
                    "end_second": 76,
                    "label": "Publish the proof",
                    "screen": "/verify",
                    "narration": (
                        "A signed append-only record connects public claims to artifacts and "
                        "corrections. Verification proves integrity, not that the strategy will "
                        "win."
                    ),
                },
                {
                    "start_second": 76,
                    "end_second": 90,
                    "label": "End with the burden",
                    "screen": "/founder#open-burden",
                    "narration": (
                        "The forward record has only "
                        f"{forward['record']['daily_return_observations']} "
                        f"daily observations, external reviews remain at zero, and Foundry is "
                        f"{foundry_deployment['status'].lower().replace('_', ' ')}. The open "
                        "burden "
                        f"is part of the result."
                    ),
                },
            ],
            "claim_boundary": (
                "This is a timed production script and evidence path. It is not a recorded video, "
                "proof that a viewer watched it or evidence of admissions impact."
            ),
        },
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
            for key, path in (SOURCES | BINDING_ONLY_SOURCES).items()
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
        "# ALPHAC: Stanford CS portfolio evidence",
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
    contribution = document["contribution_map"]
    lines.extend(["## Contribution boundary", ""])
    lines.extend(
        [
            f"**Arhan Canli:** {contribution['arhan_canli']['role']}",
            "",
            f"**AI-assisted tooling:** {contribution['ai_assisted_tooling']['role']}",
            "",
            (
                "**Libraries, services and data:** "
                f"{contribution['libraries_services_and_data']['role']}"
            ),
            "",
            (
                "**External validation:** "
                f"{contribution['external_validation']['completed_reviews']} completed reviews; "
                f"{contribution['external_validation']['independent_replications']} independent "
                "replications."
            ),
            "",
            contribution["arhan_canli"]["credit_boundary"],
            "",
        ]
    )
    lines.extend(["## Ninety-second walkthrough", ""])
    walkthrough = document["ninety_second_walkthrough"]
    for chapter in walkthrough["chapters"]:
        lines.extend(
            [
                (
                    f"### {chapter['start_second']:02d} to "
                    f"{chapter['end_second']:02d} seconds: "
                    f"{chapter['label']}"
                ),
                "",
                f"Screen: `{chapter['screen']}`",
                "",
                chapter["narration"],
                "",
            ]
        )
    lines.extend([walkthrough["claim_boundary"], ""])
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
