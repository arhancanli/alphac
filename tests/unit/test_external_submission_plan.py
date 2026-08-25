from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_external_submission_plan.py"


def _module():
    spec = importlib.util.spec_from_file_location("external_submission_plan", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plan_covers_every_sleeve_and_fails_closed() -> None:
    module = _module()
    plan = module.build()
    assert plan["status"] == "PREPARATION_ONLY_NO_EXTERNAL_SUBMISSIONS_CLAIMED"
    assert plan["counts"] == {
        "papers": 16,
        "wave_1": 5,
        "wave_2": 11,
        "submission_ready": 0,
        "blocked": 16,
        "planned_external_records": 32,
    }
    assert len({record["registry_key"] for record in plan["records"]}) == 16
    assert all(record["author"] == "Arhan Canli" for record in plan["records"])
    assert all(record["submission_claimed"] is False for record in plan["records"])
    assert all(record["peer_reviewed"] is False for record in plan["records"])
    assert all(record["review"]["state"] == "ZERO_EXTERNAL_REVIEWS" for record in plan["records"])
    assert all(
        record["review"]["author_audit"]["answers_completed"] == 0
        for record in plan["records"]
    )
    assert all(record["review"]["author_audit"]["approved"] is False for record in plan["records"])
    assert all(
        record["review"]["fresh_context_reader"]["reader_assigned"] is False
        for record in plan["records"]
    )
    assert all(
        record["review"]["fresh_context_reader"]["review_completed"] is False
        for record in plan["records"]
    )
    assert all(
        record["review"]["external_reviewer_packet"] is not None
        for record in plan["records"]
        if record["wave"] == 1
    )
    assert all(
        record["review"]["external_reviewer_packet"] is None
        for record in plan["records"]
        if record["wave"] == 2
    )
    assert all(
        record["review"]["formal_peer_review_claimed"] is False for record in plan["records"]
    )
    assert all(record["blockers"] for record in plan["records"])
    assert all(record["data_rights"]["source_mapping_complete"] for record in plan["records"])
    assert all(
        record["data_rights"]["data_manifest_license_review_complete"] is False
        for record in plan["records"]
    )
    assert all(
        "SOURCE_SPECIFIC_LICENSE_AND_REDISTRIBUTION_REVIEW_INCOMPLETE" in record["blockers"]
        for record in plan["records"]
    )
    assert not any(
        "REDISTRIBUTION_SAFE_RAW_DATA_INVENTORY_INCOMPLETE" in record["blockers"]
        for record in plan["records"]
    )
    assert all(
        "OWNER_RELEASE_AUTHORIZATION_REQUIRED" in record["blockers"] for record in plan["records"]
    )
    assert all(
        "AUTHOR_TECHNICAL_AUDIT_AND_MANUSCRIPT_APPROVAL_REQUIRED" in record["blockers"]
        for record in plan["records"]
    )
    assert all(
        "FRESH_CONTEXT_HUMAN_READER_REVIEW_REQUIRED" in record["blockers"]
        for record in plan["records"]
    )
    assert all(
        "TWO_EXTERNAL_DOMAIN_REVIEWS_REQUIRED" in record["blockers"]
        for record in plan["records"]
        if record["wave"] == 1
    )
    assert plan["strategy"]["requirements_observed_on"] == "2026-08-24"
    assert plan["strategy"]["osf_preprints_route"].startswith("EXCLUDED_PENDING_")
    assert plan["strategy"]["ssrn_route"].startswith("EXCLUDED_PENDING_")
    assert all(
        target["platform"] != "SSRN"
        for record in plan["records"]
        for target in record["planned_targets"]
    )
    assert plan["source_bindings"]["repository_requirements"]["observed_on"] == "2026-08-24"
    rights = plan["source_bindings"]["all_sleeve_data_rights_audit"]
    assert rights["source_mappings_complete"] == 16
    assert rights["data_license_reviews_complete"] == 0
    review = plan["source_bindings"]["external_review_protocol"]
    assert review["status"] == "PREPARATION_ONLY_ZERO_EXTERNAL_REVIEWS"
    assert all(value == 0 for value in review["current_counts"].values())
    assert review["governed_templates"]["automation_may_invent_author_answers_or_approval"] is False
    readers = plan["source_bindings"]["fresh_context_reader_packets"]
    assert readers["papers"] == 16
    assert readers["readers_assigned"] == 0
    assert readers["reviews_completed"] == 0
    assert plan["content_hash"] == module._content_hash(plan)


def test_published_plan_matches_current_sources() -> None:
    module = _module()
    assert json.loads(module.OUTPUT.read_text()) == module.build()
