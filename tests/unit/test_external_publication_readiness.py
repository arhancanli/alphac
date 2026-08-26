from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "audit_external_publication_readiness.py"


def _module():
    spec = importlib.util.spec_from_file_location("external_publication_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_external_publication_registry_is_honest_and_source_bound() -> None:
    module = _module()
    report = module.build()

    assert report["passes"] is True
    assert report["external_submissions_claimed"] is False
    assert report["current_sleeves"] == 16
    assert report["lineage_monographs"] == 16
    assert report["registry_coverage_fraction"] == 1.0
    assert report["bundles_with_verified_checksums"] == 16
    assert report["bundles_with_complete_recorded_union_extract"] == 16
    assert report["released_result_objects"] == 34
    assert report["archival_pdfs_machine_validated"] == 16
    assert report["archival_pdfs_visually_inspected"] == 16
    assert report["archival_pdf_pages"] == 80
    assert report["latex_sources"] == 16
    assert report["normalized_bibliographies"] == 16
    assert report["manuscript_style"] == {
        "status": "PASS_MECHANICAL_STYLE_BOUNDARY",
        "papers_audited": 16,
        "papers_passing": 16,
        "ai_detector_used": False,
        "human_authorship_proved_by_mechanical_audit": False,
    }
    assert report["external_review"]["status"] == ("PREPARATION_ONLY_ZERO_EXTERNAL_REVIEWS")
    assert all(value == 0 for value in report["external_review"]["current_counts"].values())
    assert report["external_review"]["outreach_authorized"] is False
    assert report["external_review"]["flagship_commissioning_packets"] == 5
    assert report["external_review"]["unassigned_external_reviewer_roles"] == 10
    assert report["external_review"]["assigned_reviewers"] == 0
    assert report["external_review"]["completed_reviews"] == 0
    assert report["external_review"]["author_audit_worksheets"] == 16
    assert report["external_review"]["author_audits_completed"] == 0
    assert report["external_review"]["author_approvals"] == 0
    assert report["external_review"]["fresh_context_reader_packets"] == 16
    assert report["external_review"]["fresh_context_readers_assigned"] == 0
    assert report["external_review"]["fresh_context_reader_reviews_completed"] == 0
    assert (
        report["external_review"]["governed_templates"][
            "automation_may_invent_author_answers_or_approval"
        ]
        is False
    )
    assert report["data_rights"] == {
        "raw_row_free_bundles": 16,
        "source_mappings_complete": 16,
        "data_license_reviews_complete": 0,
        "public_terms_reviews_complete": 16,
        "external_publication_clearances_complete": 0,
        "redistribution_rights_cleared_for_all_sleeves": False,
    }
    assert report["isolated_frozen_dependency_replay"]["commands_executed"] == 13
    assert report["isolated_frozen_dependency_replay"]["sleeves_with_audit_command_executed"] == 14
    assert (
        report["isolated_frozen_dependency_replay"]["portable_clean_workspace_replays_completed"]
        == 0
    )
    assert report["bundle_files"] >= 250
    assert report["submission_blockers"] > 0
    assert report["source_bindings"]["bundles"]["alphavintage_macro_surprise"]["path"] == (
        "publication/alphavintage/v1.0.0/bundle_manifest.json"
    )
    assert report["content_hash"] == module._content_hash(report)


def test_published_readiness_receipt_matches_current_sources() -> None:
    module = _module()
    assert json.loads(module.OUTPUT.read_text()) == module.build()
