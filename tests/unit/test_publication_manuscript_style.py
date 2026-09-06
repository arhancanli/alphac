from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "audit_publication_manuscript_style.py"


def _module():
    spec = importlib.util.spec_from_file_location("publication_manuscript_style", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_publication_manuscripts_pass_mechanical_style_boundary() -> None:
    module = _module()
    report = module.build()

    assert report["passes"] is True
    assert report["papers_audited"] == 16
    assert report["papers_passing"] == 16
    assert report["failed_registry_keys"] == []
    assert report["authorship_boundary"] == {
        "ai_detector_used": False,
        "ai_detector_evasion_claimed": False,
        "human_authorship_proved_by_this_audit": False,
        "final_human_approval_required": True,
    }
    assert report["content_hash"] == module._content_hash(report)


def test_published_style_receipt_matches_current_sources() -> None:
    module = _module()
    assert json.loads(module.OUTPUT.read_text()) == module.build()


def test_external_review_protocol_does_not_overclaim_review() -> None:
    protocol = json.loads((ROOT / "config/external_review_protocol.json").read_text())

    assert protocol["status"] == "PREPARATION_ONLY_ZERO_EXTERNAL_REVIEWS"
    assert protocol["outreach_authorized"] is False
    assert protocol["external_account_actions_authorized"] is False
    assert all(value == 0 for value in protocol["current_counts"].values())
    assert protocol["authorship_policy"]["ai_detector_score_is_authorship_evidence"] is False
    templates = protocol["governed_templates"]
    assert templates["automation_may_invent_author_answers_or_approval"] is False
    for key in (
        "author_technical_audit",
        "fresh_context_reader",
        "external_reviewer_brief",
        "author_response_matrix",
        "review_acquisition_plan",
    ):
        assert (ROOT / templates[key]).is_file()

    assert protocol["candidate_open_routes"]["ARXIV"]["review_claimed"] is False
    assert protocol["candidate_open_routes"]["ZENODO"]["review_claimed"] is False
    assert protocol["candidate_open_routes"]["OPENREVIEW"]["review_claimed"] is False
