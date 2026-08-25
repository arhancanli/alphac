from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_stanford_evidence_map.py"


def _module():
    spec = importlib.util.spec_from_file_location("stanford_evidence", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stanford_evidence_map_is_compact_factual_and_fail_closed() -> None:
    module = _module()
    report = module.build()
    assert report["applicant_and_project_author"] == "Arhan Canli"
    assert report["status"] == "FACTUAL_PORTFOLIO_EVIDENCE_NOT_AN_ADMISSIONS_CLAIM"
    assert report["application_ready"]["activity_description_characters"] <= 150
    governance = report["evidence"]["research_governance"]["facts"]
    assert governance["legacy_hypothesis_identities"] == 228
    assert governance["prospective_hypothesis_identities"] == 1
    assert governance["total_hypothesis_identities"] == 229
    assert governance["prospective_trial_disposition"] == "INCOMPLETE"
    assert governance["prospective_trial_admitted"] is False
    scholarly = report["evidence"]["scholarly_objects"]["facts"]
    assert scholarly["sleeve_papers"] == 16
    assert scholarly["deterministic_review_archives"] == 16
    assert scholarly["raw_input_archive_members"] == 0
    assert scholarly["source_mappings_complete"] == 16
    assert scholarly["data_license_reviews_complete"] == 0
    assert scholarly["full_clean_workspace_reproductions"] == 0
    assert scholarly["portable_core_only_reproductions"] == 0
    assert scholarly["portable_full_decision_reproductions"] == 1
    assert scholarly["upstream_strategy_curve_replays"] == 3
    assert scholarly["independent_human_reproductions"] == 0
    forward_truth = report["evidence"]["forward_truth"]["facts"]
    assert forward_truth["provenance_passes"] is True
    assert forward_truth["sharpe_status"] == "IMMATURE_RECORD_TOO_SHORT"
    assert "independent replication" in report["what_not_to_claim"]
    assert report["content_hash"] == module._content_hash(report)


def test_published_stanford_evidence_matches_current_sources() -> None:
    module = _module()
    assert json.loads(module.OUTPUT.read_text()) == module.build()
