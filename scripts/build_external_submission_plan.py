#!/usr/bin/env python3
"""Build a fail-closed, repository-specific release queue for every sleeve paper."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
REGISTRY: Final = ROOT / "config" / "external_publication_registry.json"
REQUIREMENTS: Final = ROOT / "config" / "scholarly_repository_requirements.json"
REVIEW_PROTOCOL: Final = ROOT / "config" / "external_review_protocol.json"
READINESS: Final = ROOT / "artifacts" / "audit" / "external_publication_readiness.json"
DATA_RIGHTS: Final = ROOT / "artifacts" / "publication" / "all_sleeve_data_rights_audit.json"
REVIEWER_PACKETS: Final = ROOT / "artifacts" / "publication" / "external_reviewer_packets.json"
AUTHOR_AUDITS: Final = ROOT / "artifacts" / "publication" / "author_technical_audits.json"
FRESH_READERS: Final = ROOT / "artifacts" / "publication" / "fresh_context_reader_packets.json"
OUTPUT: Final = ROOT / "artifacts" / "publication" / "external_submission_plan.json"
MARKDOWN: Final = ROOT / "docs" / "design" / "EXTERNAL_SUBMISSION_PLAN.md"

# Editorial priorities, not claims about investment quality.
FIRST_WAVE: Final = (
    "alphavintage_macro_surprise",
    "alphaforge_crypto_carry",
    "alphamax_equity_momentum",
    "alphatrend_managed_futures",
    "crypto_multifactor_engine",
)

KEYWORDS: Final = {
    "alphaforge_crypto_carry": [
        "crypto perpetual futures",
        "funding rate",
        "carry",
        "trial accounting",
        "research reproducibility",
    ],
    "alphamax_equity_momentum": [
        "equity momentum",
        "walk-forward validation",
        "trial accounting",
        "corporate actions",
        "research reproducibility",
    ],
    "alphatrend_managed_futures": [
        "managed futures",
        "trend following",
        "diversification",
        "forward evidence",
        "research reproducibility",
    ],
    "crypto_defensive": [
        "cryptocurrency",
        "defensive factors",
        "null result",
        "sleeve admission",
        "research reproducibility",
    ],
    "crypto_momentum": [
        "cryptocurrency momentum",
        "walk-forward validation",
        "failed replication",
        "trial accounting",
        "research reproducibility",
    ],
    "crypto_multifactor_engine": [
        "cryptocurrency factors",
        "probability of backtest overfitting",
        "capacity",
        "no-deploy decision",
        "research reproducibility",
    ],
    "crypto_reversal": [
        "cryptocurrency reversal",
        "short-horizon returns",
        "negative result",
        "trial accounting",
        "research reproducibility",
    ],
    "crypto_vrp": [
        "cryptocurrency volatility",
        "variance risk premium",
        "proxy design",
        "null result",
        "research reproducibility",
    ],
    "energy_inventory": [
        "petroleum inventories",
        "commodity returns",
        "scarcity",
        "negative result",
        "research reproducibility",
    ],
    "equity_insider_activity": [
        "insider purchases",
        "event study",
        "equity returns",
        "negative result",
        "research reproducibility",
    ],
    "equity_low_beta": [
        "low beta anomaly",
        "defensive equities",
        "negative result",
        "trial accounting",
        "research reproducibility",
    ],
    "equity_narrative_change": [
        "risk factor disclosure",
        "text analysis",
        "preregistration",
        "null result",
        "research reproducibility",
    ],
    "equity_quality": [
        "equity quality",
        "fundamental factors",
        "multiple testing",
        "negative result",
        "research reproducibility",
    ],
    "equity_value_investment": [
        "equity value",
        "corporate issuance",
        "investment factors",
        "multiple testing",
        "research reproducibility",
    ],
    "macro_economic_trend": [
        "macroeconomic trend",
        "point-in-time data",
        "multiple testing",
        "negative result",
        "research reproducibility",
    ],
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
    requirements = json.loads(REQUIREMENTS.read_text())
    review_protocol = json.loads(REVIEW_PROTOCOL.read_text())
    readiness = json.loads(READINESS.read_text())
    data_rights = json.loads(DATA_RIGHTS.read_text())
    reviewer_packets = json.loads(REVIEWER_PACKETS.read_text())
    author_audits = json.loads(AUTHOR_AUDITS.read_text())
    fresh_readers = json.loads(FRESH_READERS.read_text())
    if readiness.get("passes") is not True:
        raise RuntimeError("External-publication readiness audit must pass before planning")
    if requirements.get("schema") != "canli.alphac-scholarly-repository-requirements.v1":
        raise RuntimeError("Unexpected scholarly repository requirements schema")
    if (
        review_protocol.get("schema") != "canli.alphac-external-review-protocol.v1"
        or review_protocol.get("status") != "PREPARATION_ONLY_ZERO_EXTERNAL_REVIEWS"
        or any(review_protocol.get("current_counts", {}).values())
    ):
        raise RuntimeError("External-review protocol is not in the expected fail-closed state")
    if (
        data_rights.get("status")
        != "PASS_RAW_ROW_EXCLUSION_PUBLIC_TERMS_REVIEW_COMPLETE_CLEARANCE_INCOMPLETE"
        or data_rights.get("counts", {}).get("source_mapping_complete") != 16
        or data_rights.get("counts", {}).get("data_license_reviews_complete") != 0
        or data_rights.get("counts", {}).get("public_terms_reviews_complete") != 16
        or data_rights.get("counts", {}).get("external_publication_clearances_complete") != 0
    ):
        raise RuntimeError("All-sleeve data-rights audit is not in the expected fail-closed state")
    if (
        reviewer_packets.get("content_hash") != _content_hash(reviewer_packets)
        or reviewer_packets.get("flagship_packets") != 5
        or reviewer_packets.get("assigned_reviewers") != 0
        or reviewer_packets.get("completed_reviews") != 0
    ):
        raise RuntimeError("External reviewer packets are not in the expected fail-closed state")
    if (
        author_audits.get("content_hash") != _content_hash(author_audits)
        or author_audits.get("worksheets") != 16
        or author_audits.get("author_audits_completed") != 0
        or author_audits.get("author_approvals") != 0
    ):
        raise RuntimeError("Author audit worksheets are not in the expected fail-closed state")
    if (
        fresh_readers.get("content_hash") != _content_hash(fresh_readers)
        or fresh_readers.get("papers") != 16
        or fresh_readers.get("readers_assigned") != 0
        or fresh_readers.get("reviews_completed") != 0
    ):
        raise RuntimeError("Fresh-context reader packets are not in the expected fail-closed state")
    rights_by_key = {record["registry_key"]: record for record in data_rights["records"]}
    reviewer_packet_by_key = {
        record["registry_key"]: record for record in reviewer_packets["records"]
    }
    author_audit_by_key = {
        record["registry_key"]: record for record in author_audits["records"]
    }
    fresh_reader_by_key = {
        record["registry_key"]: record for record in fresh_readers["records"]
    }

    records: list[dict[str, Any]] = []
    for sleeve in registry["sleeves"]:
        key = sleeve["key"]
        rights = rights_by_key[key]
        author_audit = author_audit_by_key[key]
        fresh_reader = fresh_reader_by_key[key]
        reviewer_packet = reviewer_packet_by_key.get(key)
        manifest_path = ROOT / sleeve["bundle_manifest"]
        bundle_dir = manifest_path.parent
        paper_path = bundle_dir / "paper.json"
        pdf_path = bundle_dir / "paper.pdf"
        paper = json.loads(paper_path.read_text())
        keywords = paper.get("keywords") or KEYWORDS.get(key, [])
        metadata_blockers: list[str] = []
        if len(paper.get("abstract", "").strip()) < 250:
            metadata_blockers.append("ABSTRACT_REQUIRES_REPOSITORY_GRADE_EXPANSION")
        if len(keywords) < 5:
            metadata_blockers.append("AT_LEAST_FIVE_KEYWORDS_REQUIRED")
        if not paper.get("authors") or paper["authors"][0].get("full_name") != "Arhan Canli":
            metadata_blockers.append("AUTHOR_METADATA_INVALID")
        metadata_blockers.extend(
            [
                "OWNER_RELEASE_AUTHORIZATION_REQUIRED",
                "REPOSITORY_LICENSE_SELECTION_REQUIRED",
                "RELEASE_DATE_MUST_BE_SET_AT_PUBLICATION",
            ]
        )

        wave = 1 if key in FIRST_WAVE else 2
        review_requirements = list(review_protocol["minimum_review_plan"]["all_sleeve_records"])
        review_blockers = [
            "AUTHOR_TECHNICAL_AUDIT_AND_MANUSCRIPT_APPROVAL_REQUIRED",
            "FRESH_CONTEXT_HUMAN_READER_REVIEW_REQUIRED",
        ]
        if wave == 1:
            review_requirements.extend(
                review_protocol["minimum_review_plan"]["flagship_manuscripts"]
            )
            review_requirements = list(dict.fromkeys(review_requirements))
            review_blockers.extend(
                [
                    "TWO_EXTERNAL_DOMAIN_REVIEWS_REQUIRED",
                    "INDEPENDENT_HUMAN_REPLICATION_REQUIRED",
                ]
            )
        targets = [
            {
                "platform": "ZENODO",
                "object": "PAPER_PREPRINT",
                "purpose": "CITABLE_ARCHIVAL_PAPER_RECORD",
                "doi_expected_only_after_publish": True,
            },
            {
                "platform": "ZENODO",
                "object": "REPRODUCIBILITY_BUNDLE",
                "purpose": "DISTINCT_CODE_DATA_PROVENANCE_RECORD",
                "doi_expected_only_after_publish": True,
            },
        ]
        inherited_blockers = [
            (
                "ACCOUNT_SPECIFIC_LICENSE_OR_WRITTEN_PUBLICATION_PERMISSION_REQUIRED"
                if blocker == "REDISTRIBUTION_SAFE_RAW_DATA_INVENTORY_INCOMPLETE"
                else blocker
            )
            for blocker in sleeve["submission_blockers"]
        ]
        if rights["external_publication_clearance_complete"] is not True:
            inherited_blockers.append(
                "ACCOUNT_SPECIFIC_LICENSE_OR_WRITTEN_PUBLICATION_PERMISSION_REQUIRED"
            )
        blockers = list(dict.fromkeys([*inherited_blockers, *metadata_blockers, *review_blockers]))
        records.append(
            {
                "registry_key": key,
                "bundle_slug": sleeve["bundle_slug"],
                "version": paper["version"],
                "wave": wave,
                "editorial_priority": FIRST_WAVE.index(key) + 1 if key in FIRST_WAVE else None,
                "title": paper["title"],
                "abstract": paper["abstract"],
                "keywords": keywords,
                "author": "Arhan Canli",
                "affiliation": "Canli Capital / AlphaC Algorithms",
                "capital_kind": paper["capital_kind"],
                "peer_reviewed": False,
                "submission_claimed": False,
                "review": {
                    "state": "ZERO_EXTERNAL_REVIEWS",
                    "required_claim_levels": review_requirements,
                    "external_domain_reviews_completed": 0,
                    "independent_replications_completed": 0,
                    "formal_peer_review_claimed": False,
                    "author_audit": {
                        "path": str(
                            Path(author_audits["worksheet_root"]) / author_audit["worksheet"]
                        ),
                        "sha256": author_audit["worksheet_sha256"],
                        "answers_completed": author_audit["answers_completed"],
                        "approved": author_audit["approved"],
                    },
                    "fresh_context_reader": {
                        "path": str(
                            Path(fresh_readers["packet_root"]) / fresh_reader["packet"]
                        ),
                        "sha256": fresh_reader["packet_sha256"],
                        "reader_assigned": fresh_reader["reader_assigned"],
                        "review_completed": fresh_reader["review_completed"],
                    },
                    "external_reviewer_packet": (
                        {
                            "path": str(
                                Path(reviewer_packets["packet_root"])
                                / reviewer_packet["packet"]
                            ),
                            "sha256": reviewer_packet["packet_sha256"],
                            "assigned_reviewers": reviewer_packet["assigned_reviewers"],
                            "completed_reviews": reviewer_packet["completed_reviews"],
                        }
                        if reviewer_packet is not None
                        else None
                    ),
                },
                "data_rights": {
                    "source_mapping_complete": rights["source_mapping_complete"],
                    "raw_third_party_rows_released": rights["raw_third_party_rows_released"],
                    "data_manifest_license_review_complete": rights[
                        "data_manifest_license_review_complete"
                    ],
                    "source_public_terms_review_complete": rights[
                        "source_public_terms_review_complete"
                    ],
                    "external_publication_clearance_complete": rights[
                        "external_publication_clearance_complete"
                    ],
                    "source_classes": [
                        source["source_key"] for source in rights["source_dependencies"]
                    ],
                },
                "public_canonical": f"https://canlicapital.com/publication/{sleeve['bundle_slug']}/v{paper['version']}/paper",
                "source_objects": {
                    "paper_json": {
                        "path": str(paper_path.relative_to(ROOT)),
                        "sha256": _sha256(paper_path),
                    },
                    "paper_pdf": {
                        "path": str(pdf_path.relative_to(ROOT)),
                        "sha256": _sha256(pdf_path),
                    },
                    "bundle_manifest": {
                        "path": str(manifest_path.relative_to(ROOT)),
                        "sha256": _sha256(manifest_path),
                    },
                },
                "planned_targets": targets,
                "release_state": "BLOCKED_PREPARATION_ONLY" if blockers else "SUBMISSION_READY",
                "blockers": blockers,
            }
        )

    records.sort(
        key=lambda item: (item["wave"], item["editorial_priority"] or 999, item["bundle_slug"])
    )
    document: dict[str, Any] = {
        "schema": "canli.alphac-external-submission-plan.v1",
        "owner_and_author": "Arhan Canli",
        "status": "PREPARATION_ONLY_NO_EXTERNAL_SUBMISSIONS_CLAIMED",
        "strategy": {
            "wave_1": (
                "Five methodologically strongest sleeve papers: separate Zenodo paper and "
                "reproducibility records, followed by expert review and an eligible open-review "
                "route where one exists."
            ),
            "wave_2": (
                "Remaining sleeve papers: separate Zenodo paper and reproducibility records "
                "after editorial depth and evidence review."
            ),
            "methodology_flagship": (
                "A separate cross-sleeve paper on fail-closed quantitative research governance "
                "remains to be authored and scope-checked for arXiv q-fin. OSF Preprints is "
                "excluded pending a paper-specific human-authorship and provider-scope review."
            ),
            "duplicate_identifier_policy": (
                "Never mint two identifiers for the same object; paper and reproducibility "
                "bundle are distinct related objects."
            ),
            "requirements_observed_on": requirements["observed_on"],
            "ssrn_route": requirements["repositories"]["SSRN"]["route"],
            "osf_preprints_route": requirements["repositories"]["OSF_PREPRINTS"]["route"],
            "open_review_routes": list(review_protocol["candidate_open_routes"]),
        },
        "counts": {
            "papers": len(records),
            "wave_1": sum(item["wave"] == 1 for item in records),
            "wave_2": sum(item["wave"] == 2 for item in records),
            "submission_ready": sum(
                item["release_state"] == "SUBMISSION_READY" for item in records
            ),
            "blocked": sum(item["release_state"] != "SUBMISSION_READY" for item in records),
            "planned_external_records": sum(len(item["planned_targets"]) for item in records),
        },
        "records": records,
        "source_bindings": {
            "repository_requirements": {
                "path": str(REQUIREMENTS.relative_to(ROOT)),
                "sha256": _sha256(REQUIREMENTS),
                "observed_on": requirements["observed_on"],
            },
            "all_sleeve_data_rights_audit": {
                "path": str(DATA_RIGHTS.relative_to(ROOT)),
                "sha256": _sha256(DATA_RIGHTS),
                "content_hash": data_rights["content_hash"],
                "source_mappings_complete": data_rights["counts"]["source_mapping_complete"],
                "data_license_reviews_complete": data_rights["counts"][
                    "data_license_reviews_complete"
                ],
                "public_terms_reviews_complete": data_rights["counts"][
                    "public_terms_reviews_complete"
                ],
                "external_publication_clearances_complete": data_rights["counts"][
                    "external_publication_clearances_complete"
                ],
            },
            "external_review_protocol": {
                "path": str(REVIEW_PROTOCOL.relative_to(ROOT)),
                "sha256": _sha256(REVIEW_PROTOCOL),
                "status": review_protocol["status"],
                "current_counts": review_protocol["current_counts"],
                "governed_templates": review_protocol["governed_templates"],
            },
            "external_reviewer_packets": {
                "path": str(REVIEWER_PACKETS.relative_to(ROOT)),
                "sha256": _sha256(REVIEWER_PACKETS),
                "content_hash": reviewer_packets["content_hash"],
                "flagship_packets": reviewer_packets["flagship_packets"],
                "assigned_reviewers": reviewer_packets["assigned_reviewers"],
                "completed_reviews": reviewer_packets["completed_reviews"],
            },
            "author_technical_audits": {
                "path": str(AUTHOR_AUDITS.relative_to(ROOT)),
                "sha256": _sha256(AUTHOR_AUDITS),
                "content_hash": author_audits["content_hash"],
                "worksheets": author_audits["worksheets"],
                "author_audits_completed": author_audits["author_audits_completed"],
                "author_approvals": author_audits["author_approvals"],
            },
            "fresh_context_reader_packets": {
                "path": str(FRESH_READERS.relative_to(ROOT)),
                "sha256": _sha256(FRESH_READERS),
                "content_hash": fresh_readers["content_hash"],
                "papers": fresh_readers["papers"],
                "readers_assigned": fresh_readers["readers_assigned"],
                "reviews_completed": fresh_readers["reviews_completed"],
            },
        },
        "claim_boundary": (
            "This is a local preparation queue. It proves no submission, acceptance, DOI, "
            "peer review, citation, external review, or independent replication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def _render_markdown(document: dict[str, Any]) -> str:
    lines = [
        "# ALPHAC external submission plan",
        "",
        "**Owner and author:** Arhan Canli  ",
        "**Status:** preparation only; no external submission is claimed",
        "",
        (
            "This queue turns the 16 sealed sleeve papers into repository-specific release "
            "objects. Every row remains blocked until its listed evidence and metadata "
            "requirements are closed."
        ),
        "",
        "| Wave | Paper | Planned venues | State | Open blockers |",
        "|---:|---|---|---|---:|",
    ]
    for item in document["records"]:
        venues = ", ".join(target["platform"] for target in item["planned_targets"])
        lines.append(
            f"| {item['wave']} | {item['title']} | {venues} | "
            f"{item['release_state']} | {len(item['blockers'])} |"
        )
    lines.extend(
        [
            "",
            "## Release order",
            "",
            (
                "Wave 1 prioritizes AlphaVintage, crypto carry, AlphaMax, AlphaTrend and the "
                "crypto multi-factor engine because their correction, complete-union accounting, "
                "operational boundary or no-deploy evidence makes the methodological contribution "
                "clearest. Wave 2 preserves every remaining positive, null and killed sleeve as "
                "citable research without pretending that volume equals validation."
            ),
            "",
            (
                "The authoritative metadata, hashes, target objects and exact blocker lists are "
                "in `artifacts/publication/external_submission_plan.json`."
            ),
            "",
            "## Repository-policy correction",
            "",
            (
                "The requirements were rechecked against official repository guidance on "
                f"{document['strategy']['requirements_observed_on']}. Zenodo remains the archival "
                "route for distinct paper and reproducibility objects; SSRN is excluded pending "
                "direct author-eligibility confirmation or a policy change; arXiv remains a "
                "possible route only for a "
                "separately authored, topical methodology paper. OSF Preprints is not a default "
                "route and is excluded pending a paper-specific human-authorship and provider-"
                "scope review."
            ),
            "",
            "## Non-negotiable boundary",
            "",
            document["claim_boundary"],
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    document = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    MARKDOWN.write_text(_render_markdown(document))
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "counts": document["counts"],
                "content_hash": document["content_hash"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
