#!/usr/bin/env python3
"""Fail closed on external-publication claims and report the exact sleeve-paper blockers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
REGISTRY: Final = ROOT / "config" / "external_publication_registry.json"
EVIDENCE_CATALOG: Final = ROOT / "config" / "sleeve_publication_evidence.json"
REPLAY_RECEIPT: Final = ROOT / "artifacts" / "audit" / "sleeve_publication_replay_verification.json"
ISOLATED_REPLAY_RECEIPT: Final = (
    ROOT / "artifacts" / "audit" / "sleeve_publication_isolated_replay_verification.json"
)
STANDARD: Final = ROOT / "docs" / "design" / "EXTERNAL_RESEARCH_PUBLICATION_STANDARD.md"
REVIEW_PROTOCOL: Final = ROOT / "config" / "external_review_protocol.json"
MANUSCRIPT_STYLE_AUDIT: Final = ROOT / "artifacts" / "audit" / "publication_manuscript_style.json"
REVIEWER_PACKETS: Final = ROOT / "artifacts" / "publication" / "external_reviewer_packets.json"
AUTHOR_AUDIT_WORKSHEETS: Final = (
    ROOT / "artifacts" / "publication" / "author_technical_audits.json"
)
AUTHOR_APPROVAL_PROTOCOL: Final = (
    ROOT / "docs" / "design" / "AUTHOR_TECHNICAL_APPROVAL_PROTOCOL.md"
)
AUTHOR_APPROVAL_VERIFIER: Final = ROOT / "scripts" / "verify_author_technical_approval.py"
FRESH_CONTEXT_READER_PACKETS: Final = (
    ROOT / "artifacts" / "publication" / "fresh_context_reader_packets.json"
)
OUTPUT: Final = ROOT / "artifacts" / "audit" / "external_publication_readiness.json"
VISUAL_RECEIPT: Final = ROOT / "artifacts" / "audit" / "archival_publication_visual_inspection.json"
DATA_RIGHTS_AUDIT: Final = ROOT / "artifacts" / "publication" / "all_sleeve_data_rights_audit.json"
LINEAGE_GLOB: Final = "*_LINEAGE.md"
REQUIRED_BUNDLE_FILES: Final = {
    "CITATION.cff",
    "CORRECTIONS.md",
    "LICENSE",
    "README.md",
    "SHA256SUMS",
    "bundle_manifest.json",
    "codemeta.json",
    "data_manifest.json",
    "paper.json",
    "paper.html",
    "paper.pdf",
    "paper.tex",
    "pdf_validation.json",
    "archival_visual_inspection_receipt.json",
    "paper.md",
    "reproduction.json",
    "references.bib",
    "ro-crate-metadata.json",
    "sbom.spdx.json",
    "trial_accounting.json",
}
ALLOWED_STATES: Final = {
    "SOURCE_ONLY",
    "BUNDLE_INCOMPLETE",
    "INTERNAL_READER_TESTED",
    "EXTERNAL_REPLICATION_READY",
    "SUBMISSION_READY",
    "SUBMITTED_PENDING",
    "PUBLIC_PREPRINT",
    "INDEPENDENTLY_REPLICATED",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _verify_checksums(bundle_dir: Path) -> list[str]:
    failures: list[str] = []
    checksum_path = bundle_dir / "SHA256SUMS"
    if not checksum_path.is_file():
        return ["SHA256SUMS_MISSING"]
    seen: set[str] = set()
    for line in checksum_path.read_text().splitlines():
        try:
            expected, name = line.split("  ", maxsplit=1)
        except ValueError:
            failures.append("SHA256SUMS_MALFORMED")
            continue
        target = bundle_dir / name
        seen.add(name)
        if not target.is_file():
            failures.append(f"CHECKSUM_TARGET_MISSING:{name}")
        elif _sha256(target) != expected:
            failures.append(f"CHECKSUM_MISMATCH:{name}")
    expected_names = {
        str(path.relative_to(bundle_dir))
        for path in bundle_dir.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    if seen != expected_names:
        failures.append("CHECKSUM_INVENTORY_MISMATCH")
    return failures


def build() -> dict[str, Any]:
    registry = json.loads(REGISTRY.read_text())
    failures: list[str] = []
    sleeves = registry.get("sleeves")
    if registry.get("schema") != "canli.alphac-external-publication-registry.v2":
        failures.append("UNEXPECTED_REGISTRY_SCHEMA")
    if not isinstance(sleeves, list):
        sleeves = []
        failures.append("SLEEVES_NOT_A_LIST")

    keys = [item.get("key") for item in sleeves]
    if len(set(keys)) != len(keys):
        failures.append("DUPLICATE_SLEEVE_KEY")
    registered_sources = {str(item.get("source_paper", "")) for item in sleeves}
    lineage_sources = {
        str(path.relative_to(ROOT))
        for path in (ROOT / "docs/research").glob(LINEAGE_GLOB)
        if path.is_file()
    }
    if registered_sources != lineage_sources:
        failures.append("REGISTRY_DOES_NOT_EXACTLY_COVER_ALL_LINEAGE_MONOGRAPHS")
    titles = [item.get("title") for item in sleeves]
    if len(set(titles)) != len(titles):
        failures.append("DUPLICATE_PAPER_TITLE")

    states: dict[str, int] = {}
    blockers = 0
    source_bindings: dict[str, dict[str, str]] = {}
    bundle_bindings: dict[str, dict[str, str]] = {}
    bundle_files = 0
    checksum_verified_bundles = 0
    complete_union_bundles = 0
    released_result_objects = 0
    archival_pdfs_machine_validated = 0
    archival_pdfs_visually_inspected = 0
    latex_sources = 0
    archival_pdf_pages = 0
    normalized_bibliographies = 0
    evidence_catalog = json.loads(EVIDENCE_CATALOG.read_text())["sleeves"]
    replay_receipt = json.loads(REPLAY_RECEIPT.read_text())
    isolated_replay_receipt = json.loads(ISOLATED_REPLAY_RECEIPT.read_text())
    visual_receipt = json.loads(VISUAL_RECEIPT.read_text())
    data_rights = json.loads(DATA_RIGHTS_AUDIT.read_text())
    review_protocol = json.loads(REVIEW_PROTOCOL.read_text())
    manuscript_style = json.loads(MANUSCRIPT_STYLE_AUDIT.read_text())
    reviewer_packets = json.loads(REVIEWER_PACKETS.read_text())
    author_audits = json.loads(AUTHOR_AUDIT_WORKSHEETS.read_text())
    fresh_context_readers = json.loads(FRESH_CONTEXT_READER_PACKETS.read_text())
    review_counts = review_protocol.get("current_counts", {})
    if (
        review_protocol.get("schema") != "canli.alphac-external-review-protocol.v1"
        or review_protocol.get("status") != "PREPARATION_ONLY_ZERO_EXTERNAL_REVIEWS"
        or review_protocol.get("outreach_authorized") is not False
        or review_protocol.get("external_account_actions_authorized") is not False
        or any(review_counts.values())
    ):
        failures.append("EXTERNAL_REVIEW_PROTOCOL_INVALID")
    reviewer_packet_body = {
        key: value for key, value in reviewer_packets.items() if key != "content_hash"
    }
    reviewer_packet_hash = (
        f"sha256:{hashlib.sha256(_canonical(reviewer_packet_body)).hexdigest()}"
    )
    if (
        reviewer_packets.get("content_hash") != reviewer_packet_hash
        or reviewer_packets.get("status")
        != "PASS_PREPARATION_ONLY_ZERO_REVIEWERS_ZERO_REVIEWS"
        or reviewer_packets.get("flagship_packets") != 5
        or reviewer_packets.get("review_roles") != 10
        or reviewer_packets.get("assigned_reviewers") != 0
        or reviewer_packets.get("completed_reviews") != 0
        or reviewer_packets.get("outreach_authorized") is not False
    ):
        failures.append("EXTERNAL_REVIEWER_PACKET_MANIFEST_INVALID")
    author_audit_body = {
        key: value for key, value in author_audits.items() if key != "content_hash"
    }
    author_audit_hash = f"sha256:{hashlib.sha256(_canonical(author_audit_body)).hexdigest()}"
    if (
        author_audits.get("content_hash") != author_audit_hash
        or author_audits.get("status") != "PASS_BLANK_WORKSHEETS_ZERO_AUTHOR_APPROVALS"
        or author_audits.get("worksheets") != len(sleeves)
        or author_audits.get("questions") != len(sleeves) * 5
        or author_audits.get("answers_completed") != 0
        or author_audits.get("author_audits_completed") != 0
        or author_audits.get("author_approvals") != 0
    ):
        failures.append("AUTHOR_TECHNICAL_AUDIT_WORKSHEET_MANIFEST_INVALID")
    fresh_context_reader_body = {
        key: value for key, value in fresh_context_readers.items() if key != "content_hash"
    }
    fresh_context_reader_hash = (
        f"sha256:{hashlib.sha256(_canonical(fresh_context_reader_body)).hexdigest()}"
    )
    if (
        fresh_context_readers.get("content_hash") != fresh_context_reader_hash
        or fresh_context_readers.get("status")
        != "PASS_BLANK_PACKETS_ZERO_READERS_ZERO_REVIEWS"
        or fresh_context_readers.get("papers") != len(sleeves)
        or fresh_context_readers.get("questions") != len(sleeves) * 9
        or fresh_context_readers.get("answers_completed") != 0
        or fresh_context_readers.get("readers_assigned") != 0
        or fresh_context_readers.get("reviews_completed") != 0
    ):
        failures.append("FRESH_CONTEXT_READER_PACKET_MANIFEST_INVALID")
    manuscript_style_body = {
        key: value for key, value in manuscript_style.items() if key != "content_hash"
    }
    manuscript_style_hash = (
        f"sha256:{hashlib.sha256(_canonical(manuscript_style_body)).hexdigest()}"
    )
    style_records = {
        str(record.get("registry_key")): record
        for record in manuscript_style.get("records", [])
        if isinstance(record, dict)
    }
    if (
        manuscript_style.get("content_hash") != manuscript_style_hash
        or manuscript_style.get("status") != "PASS_MECHANICAL_STYLE_BOUNDARY"
        or manuscript_style.get("passes") is not True
        or manuscript_style.get("papers_audited") != len(sleeves)
        or manuscript_style.get("papers_passing") != len(sleeves)
        or manuscript_style.get("authorship_boundary", {}).get(
            "human_authorship_proved_by_this_audit"
        )
        is not False
    ):
        failures.append("MANUSCRIPT_STYLE_AUDIT_INVALID")
    data_rights_body = {key: value for key, value in data_rights.items() if key != "content_hash"}
    data_rights_hash = f"sha256:{hashlib.sha256(_canonical(data_rights_body)).hexdigest()}"
    if (
        data_rights.get("content_hash") != data_rights_hash
        or data_rights.get("status")
        != "PASS_RAW_ROW_EXCLUSION_PUBLIC_TERMS_REVIEW_COMPLETE_CLEARANCE_INCOMPLETE"
        or data_rights.get("counts", {}).get("audited_sleeves") != len(sleeves)
        or data_rights.get("counts", {}).get("raw_row_free_bundles") != len(sleeves)
        or data_rights.get("counts", {}).get("source_mapping_complete") != len(sleeves)
        or data_rights.get("counts", {}).get("data_license_reviews_complete") != 0
        or data_rights.get("counts", {}).get("public_terms_reviews_complete")
        != len(sleeves)
        or data_rights.get("counts", {}).get(
            "external_publication_clearances_complete"
        )
        != 0
        or data_rights.get("redistribution_rights_cleared_for_all_sleeves") is not False
    ):
        failures.append("ALL_SLEEVE_DATA_RIGHTS_AUDIT_INVALID")
    visual_body = {key: value for key, value in visual_receipt.items() if key != "content_hash"}
    visual_hash = f"sha256:{hashlib.sha256(_canonical(visual_body)).hexdigest()}"
    if (
        visual_receipt.get("content_hash") != visual_hash
        or visual_receipt.get("status") != "PASS_INTERNAL_VISUAL_INSPECTION_NOT_INDEPENDENT_REVIEW"
        or visual_receipt.get("papers_inspected") != len(sleeves)
    ):
        failures.append("ARCHIVAL_VISUAL_INSPECTION_RECEIPT_INVALID")
    visual_records = {
        str(record.get("registry_key")): record
        for record in visual_receipt.get("papers", [])
        if isinstance(record, dict)
    }
    replay_body = {key: value for key, value in replay_receipt.items() if key != "content_hash"}
    replay_hash = f"sha256:{hashlib.sha256(_canonical(replay_body)).hexdigest()}"
    if (
        replay_receipt.get("content_hash") != replay_hash
        or replay_receipt.get("passes") is not True
    ):
        failures.append("INTERNAL_AUDIT_REPLAY_RECEIPT_INVALID")
    isolated_replay_body = {
        key: value for key, value in isolated_replay_receipt.items() if key != "content_hash"
    }
    isolated_replay_hash = f"sha256:{hashlib.sha256(_canonical(isolated_replay_body)).hexdigest()}"
    if (
        isolated_replay_receipt.get("content_hash") != isolated_replay_hash
        or isolated_replay_receipt.get("passes") is not True
        or isolated_replay_receipt.get("dependency_environment") != "UV_ISOLATED_FROZEN"
        or isolated_replay_receipt.get("portable_clean_workspace_replay_completed") is not False
        or isolated_replay_receipt.get("raw_input_portability_established") is not False
        or isolated_replay_receipt.get("independent_replication") is not False
    ):
        failures.append("ISOLATED_DEPENDENCY_REPLAY_RECEIPT_INVALID")
    for item in sleeves:
        key = str(item.get("key"))
        state = item.get("state")
        states[str(state)] = states.get(str(state), 0) + 1
        if state not in ALLOWED_STATES:
            failures.append(f"{key}:INVALID_STATE")
        if item.get("author") != "Arhan Canli":
            failures.append(f"{key}:AUTHOR_MISMATCH")
        item_blockers = item.get("submission_blockers")
        if not isinstance(item_blockers, list):
            failures.append(f"{key}:BLOCKERS_NOT_A_LIST")
            item_blockers = []
        blockers += len(item_blockers)
        if state in {"SOURCE_ONLY", "BUNDLE_INCOMPLETE"} and not item_blockers:
            failures.append(f"{key}:INCOMPLETE_STATE_WITHOUT_BLOCKERS")
        if any(field in item for field in ("doi", "external_url", "submitted_at")):
            failures.append(f"{key}:UNVERIFIED_EXTERNAL_CLAIM_PRESENT")

        source = ROOT / str(item.get("source_paper", ""))
        if not source.is_file():
            failures.append(f"{key}:SOURCE_PAPER_MISSING")
            continue
        text = source.read_text()
        if "Arhan Canli" not in text:
            failures.append(f"{key}:SOURCE_BYLINE_MISSING")
        if "not peer reviewed" not in text.lower():
            failures.append(f"{key}:PREPRINT_BOUNDARY_MISSING")
        source_bindings[key] = {
            "path": str(source.relative_to(ROOT)),
            "sha256": _sha256(source),
        }
        style_record = style_records.get(key, {})
        if (
            style_record.get("path") != str(source.relative_to(ROOT))
            or style_record.get("sha256") != _sha256(source)
            or style_record.get("passes_mechanical_audit") is not True
        ):
            failures.append(f"{key}:MANUSCRIPT_STYLE_BINDING_INVALID")

        bundle_manifest_value = item.get("bundle_manifest")
        if not bundle_manifest_value:
            failures.append(f"{key}:BUNDLE_MANIFEST_NOT_DECLARED")
            continue
        bundle_manifest = ROOT / str(bundle_manifest_value)
        if not bundle_manifest.is_file():
            failures.append(f"{key}:BUNDLE_MANIFEST_MISSING")
            continue
        bundle_dir = bundle_manifest.parent
        names = {path.name for path in bundle_dir.iterdir() if path.is_file()}
        missing = REQUIRED_BUNDLE_FILES - names
        if missing:
            failures.append(f"{key}:REQUIRED_BUNDLE_FILES_MISSING:{','.join(sorted(missing))}")
        bundle_files += sum(1 for path in bundle_dir.rglob("*") if path.is_file())
        checksum_failures = _verify_checksums(bundle_dir)
        failures.extend(f"{key}:{failure}" for failure in checksum_failures)
        if not checksum_failures:
            checksum_verified_bundles += 1
        bundle = json.loads(bundle_manifest.read_text())
        if bundle.get("registry_key") != key:
            failures.append(f"{key}:BUNDLE_REGISTRY_KEY_MISMATCH")
        if bundle.get("status") != state:
            failures.append(f"{key}:BUNDLE_STATE_MISMATCH")
        if bundle.get("remaining_blockers") != item_blockers:
            failures.append(f"{key}:BUNDLE_BLOCKERS_DIVERGE_FROM_REGISTRY")
        if bundle.get("external_submission_claimed") is not False:
            failures.append(f"{key}:BUNDLE_OVERSTATES_EXTERNAL_STATUS")
        archival = bundle.get("archival_assets", {})
        pdf_asset = archival.get("pdf", {})
        pdf_path = bundle_dir / str(pdf_asset.get("path", ""))
        html_asset = archival.get("html", {})
        latex_asset = archival.get("latex", {})
        if (
            not pdf_path.is_file()
            or pdf_asset.get("sha256") != _sha256(pdf_path)
            or pdf_asset.get("machine_validation") != "PASS"
        ):
            failures.append(f"{key}:ARCHIVAL_PDF_BINDING_INVALID")
        else:
            archival_pdfs_machine_validated += 1
        for asset_name, asset in (("HTML", html_asset), ("LATEX", latex_asset)):
            asset_path = bundle_dir / str(asset.get("path", ""))
            if not asset_path.is_file() or asset.get("sha256") != _sha256(asset_path):
                failures.append(f"{key}:ARCHIVAL_{asset_name}_BINDING_INVALID")
        if (bundle_dir / str(latex_asset.get("path", ""))).is_file():
            latex_sources += 1
        bibliography_assets = archival.get("bibliography", {})
        bibliography_bib = bundle_dir / "references.bib"
        bibliography_binding = bibliography_assets.get("references.bib", {})
        if not bibliography_bib.is_file() or bibliography_binding.get("sha256") != _sha256(
            bibliography_bib
        ):
            failures.append(f"{key}:NORMALIZED_BIBLIOGRAPHY_BINDING_INVALID")
        elif key == "alphavintage_macro_surprise":
            normalized_bibliographies += 1
        else:
            references_json = bundle_dir / "references.json"
            bibliography_json_binding = bibliography_assets.get("references.json", {})
            references = (
                json.loads(references_json.read_text()) if references_json.is_file() else {}
            )
            if (
                references.get("status") != "COMPLETE_NORMALIZED_BIBLIOGRAPHY"
                or references.get("unresolved_references") != []
                or bibliography_json_binding.get("sha256") != _sha256(references_json)
            ):
                failures.append(f"{key}:NORMALIZED_BIBLIOGRAPHY_INVALID")
            else:
                normalized_bibliographies += 1
        validation = json.loads((bundle_dir / "pdf_validation.json").read_text())
        if validation.get("passes") is not True or validation.get("registry_key") != key:
            failures.append(f"{key}:ARCHIVAL_PDF_MACHINE_VALIDATION_INVALID")
        renderer_binding = validation.get("source_bindings", {}).get("renderer", {})
        renderer_path = ROOT / str(renderer_binding.get("path", ""))
        if not renderer_path.is_file() or renderer_binding.get("sha256") != _sha256(renderer_path):
            failures.append(f"{key}:ARCHIVAL_RENDERER_BINDING_INVALID")
        archival_pdf_pages += int(validation.get("pages", 0))
        visual_record = visual_records.get(key, {})
        if (
            visual_record.get("pdf_sha256") != pdf_asset.get("sha256")
            or visual_record.get("pdf_validation_sha256")
            != _sha256(bundle_dir / "pdf_validation.json")
            or visual_record.get("pages_inspected") != validation.get("pages")
        ):
            failures.append(f"{key}:ARCHIVAL_VISUAL_RECORD_BINDING_INVALID")
        local_visual = bundle_dir / "archival_visual_inspection_receipt.json"
        visual_asset = pdf_asset.get("visual_inspection", {})
        if (
            not local_visual.is_file()
            or local_visual.read_bytes() != VISUAL_RECEIPT.read_bytes()
            or visual_asset.get("status")
            != "PASS_INTERNAL_VISUAL_INSPECTION_NOT_INDEPENDENT_REVIEW"
            or visual_asset.get("sha256") != _sha256(local_visual)
        ):
            failures.append(f"{key}:ARCHIVAL_PDF_VISUAL_INSPECTION_INVALID")
        else:
            archival_pdfs_visually_inspected += 1
        trial_accounting = json.loads((bundle_dir / "trial_accounting.json").read_text())
        union_complete = trial_accounting.get("complete_recorded_union_extracted") is True or (
            trial_accounting.get("sleeve_complete_union_extracted") is True
        )
        if not union_complete:
            failures.append(f"{key}:COMPLETE_RECORDED_UNION_NOT_EXTRACTED")
        else:
            complete_union_bundles += 1
        if key in evidence_catalog:
            data_manifest = json.loads((bundle_dir / "data_manifest.json").read_text())
            results = data_manifest.get("released_result_objects", [])
            if len(results) != len(evidence_catalog[key]["result_objects"]):
                failures.append(f"{key}:RELEASED_RESULT_OBJECT_COUNT_MISMATCH")
            for result in results:
                bundled = bundle_dir / str(result.get("bundle_path", ""))
                if not bundled.is_file() or _sha256(bundled) != result.get("sha256"):
                    failures.append(f"{key}:RELEASED_RESULT_OBJECT_HASH_MISMATCH")
            released_result_objects += len(results)
        bundle_bindings[key] = {
            "path": str(bundle_manifest.relative_to(ROOT)),
            "sha256": _sha256(bundle_manifest),
        }

    no_submission_claimed = (
        registry.get("status") == "PREPARATION_ONLY_NO_EXTERNAL_SUBMISSIONS_CLAIMED"
    )
    if not no_submission_claimed:
        failures.append("REGISTRY_OVERSTATES_EXTERNAL_STATUS")
    if visual_receipt.get("pages_inspected") != archival_pdf_pages:
        failures.append("ARCHIVAL_VISUAL_INSPECTION_PAGE_COUNT_MISMATCH")

    document: dict[str, Any] = {
        "schema": "canli.alphac-external-publication-readiness-audit.v1",
        "author": "Arhan Canli",
        "status": "PASS_FAIL_CLOSED_PREPARATION_LEDGER" if not failures else "FAIL",
        "passes": not failures,
        "external_submissions_claimed": False,
        "current_sleeves": len(sleeves),
        "lineage_monographs": len(lineage_sources),
        "registry_coverage_fraction": (
            len(registered_sources & lineage_sources) / len(lineage_sources)
            if lineage_sources
            else 0.0
        ),
        "bundles_with_verified_checksums": checksum_verified_bundles,
        "bundles_with_complete_recorded_union_extract": complete_union_bundles,
        "released_result_objects": released_result_objects,
        "archival_pdfs_machine_validated": archival_pdfs_machine_validated,
        "archival_pdfs_visually_inspected": archival_pdfs_visually_inspected,
        "archival_pdf_pages": archival_pdf_pages,
        "latex_sources": latex_sources,
        "normalized_bibliographies": normalized_bibliographies,
        "data_rights": {
            "raw_row_free_bundles": data_rights.get("counts", {}).get("raw_row_free_bundles"),
            "source_mappings_complete": data_rights.get("counts", {}).get(
                "source_mapping_complete"
            ),
            "data_license_reviews_complete": data_rights.get("counts", {}).get(
                "data_license_reviews_complete"
            ),
            "public_terms_reviews_complete": data_rights.get("counts", {}).get(
                "public_terms_reviews_complete"
            ),
            "external_publication_clearances_complete": data_rights.get(
                "counts", {}
            ).get("external_publication_clearances_complete"),
            "redistribution_rights_cleared_for_all_sleeves": False,
        },
        "manuscript_style": {
            "status": manuscript_style.get("status"),
            "papers_audited": manuscript_style.get("papers_audited"),
            "papers_passing": manuscript_style.get("papers_passing"),
            "ai_detector_used": manuscript_style.get("authorship_boundary", {}).get(
                "ai_detector_used"
            ),
            "human_authorship_proved_by_mechanical_audit": False,
        },
        "external_review": {
            "status": review_protocol.get("status"),
            "current_counts": review_counts,
            "governed_templates": review_protocol.get("governed_templates"),
            "outreach_authorized": False,
            "external_account_actions_authorized": False,
            "flagship_commissioning_packets": reviewer_packets.get("flagship_packets"),
            "unassigned_external_reviewer_roles": reviewer_packets.get("review_roles"),
            "assigned_reviewers": reviewer_packets.get("assigned_reviewers"),
            "completed_reviews": reviewer_packets.get("completed_reviews"),
            "author_audit_worksheets": author_audits.get("worksheets"),
            "author_audits_completed": author_audits.get("author_audits_completed"),
            "author_approvals": author_audits.get("author_approvals"),
            "author_approval_workflow": {
                "status": "AVAILABLE_ZERO_SELF_ATTESTED_APPROVALS",
                "approval_receipts_imported": author_audits.get("author_approvals"),
                "software_proves_author_identity": False,
                "automation_may_complete_response": False,
            },
            "fresh_context_reader_packets": fresh_context_readers.get("papers"),
            "fresh_context_readers_assigned": fresh_context_readers.get("readers_assigned"),
            "fresh_context_reader_reviews_completed": fresh_context_readers.get(
                "reviews_completed"
            ),
        },
        "internal_audit_replay": {
            "status": replay_receipt.get("status"),
            "commands_executed": replay_receipt.get("commands_executed"),
            "sleeves_with_audit_command_executed": replay_receipt.get(
                "sleeves_with_audit_command_executed"
            ),
            "sleeves_deferred": replay_receipt.get("sleeves_deferred"),
            "clean_environment_replays_completed": 0,
            "independent_replications_completed": 0,
        },
        "isolated_frozen_dependency_replay": {
            "status": isolated_replay_receipt.get("status"),
            "dependency_environment": isolated_replay_receipt.get("dependency_environment"),
            "commands_executed": isolated_replay_receipt.get("commands_executed"),
            "sleeves_with_audit_command_executed": isolated_replay_receipt.get(
                "sleeves_with_audit_command_executed"
            ),
            "sleeves_deferred": isolated_replay_receipt.get("sleeves_deferred"),
            "portable_clean_workspace_replays_completed": 0,
            "raw_input_portability_established": False,
            "independent_replications_completed": 0,
        },
        "bundle_files": bundle_files,
        "state_counts": states,
        "submission_blockers": blockers,
        "failures": failures,
        "source_bindings": {
            "registry": {"path": str(REGISTRY.relative_to(ROOT)), "sha256": _sha256(REGISTRY)},
            "standard": {"path": str(STANDARD.relative_to(ROOT)), "sha256": _sha256(STANDARD)},
            "external_review_protocol": {
                "path": str(REVIEW_PROTOCOL.relative_to(ROOT)),
                "sha256": _sha256(REVIEW_PROTOCOL),
                "status": review_protocol.get("status"),
            },
            "manuscript_style_audit": {
                "path": str(MANUSCRIPT_STYLE_AUDIT.relative_to(ROOT)),
                "sha256": _sha256(MANUSCRIPT_STYLE_AUDIT),
                "content_hash": manuscript_style.get("content_hash"),
            },
            "external_reviewer_packets": {
                "path": str(REVIEWER_PACKETS.relative_to(ROOT)),
                "sha256": _sha256(REVIEWER_PACKETS),
                "content_hash": reviewer_packets.get("content_hash"),
            },
            "author_technical_audit_worksheets": {
                "path": str(AUTHOR_AUDIT_WORKSHEETS.relative_to(ROOT)),
                "sha256": _sha256(AUTHOR_AUDIT_WORKSHEETS),
                "content_hash": author_audits.get("content_hash"),
            },
            "author_technical_approval_protocol": {
                "path": str(AUTHOR_APPROVAL_PROTOCOL.relative_to(ROOT)),
                "sha256": _sha256(AUTHOR_APPROVAL_PROTOCOL),
            },
            "author_technical_approval_verifier": {
                "path": str(AUTHOR_APPROVAL_VERIFIER.relative_to(ROOT)),
                "sha256": _sha256(AUTHOR_APPROVAL_VERIFIER),
            },
            "fresh_context_reader_packets": {
                "path": str(FRESH_CONTEXT_READER_PACKETS.relative_to(ROOT)),
                "sha256": _sha256(FRESH_CONTEXT_READER_PACKETS),
                "content_hash": fresh_context_readers.get("content_hash"),
            },
            "evidence_catalog": {
                "path": str(EVIDENCE_CATALOG.relative_to(ROOT)),
                "sha256": _sha256(EVIDENCE_CATALOG),
            },
            "internal_audit_replay_receipt": {
                "path": str(REPLAY_RECEIPT.relative_to(ROOT)),
                "sha256": _sha256(REPLAY_RECEIPT),
                "content_hash": replay_receipt.get("content_hash"),
            },
            "isolated_dependency_replay_receipt": {
                "path": str(ISOLATED_REPLAY_RECEIPT.relative_to(ROOT)),
                "sha256": _sha256(ISOLATED_REPLAY_RECEIPT),
                "content_hash": isolated_replay_receipt.get("content_hash"),
            },
            "archival_visual_inspection_receipt": {
                "path": str(VISUAL_RECEIPT.relative_to(ROOT)),
                "sha256": _sha256(VISUAL_RECEIPT),
                "content_hash": visual_receipt.get("content_hash"),
            },
            "all_sleeve_data_rights_audit": {
                "path": str(DATA_RIGHTS_AUDIT.relative_to(ROOT)),
                "sha256": _sha256(DATA_RIGHTS_AUDIT),
                "content_hash": data_rights.get("content_hash"),
            },
            "papers": source_bindings,
            "bundles": bundle_bindings,
            "audit_script": {
                "path": str(Path(__file__).resolve().relative_to(ROOT)),
                "sha256": _sha256(Path(__file__).resolve()),
            },
        },
        "claim_boundary": (
            "This proves only that the preparation ledger is honest and source-bound. It proves "
            "no submission, DOI, peer review, citation, moderation outcome or replication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def main() -> int:
    document = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{document['status']}: {OUTPUT}")
    print(f"content_hash: {document['content_hash']}")
    return 0 if document["passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
