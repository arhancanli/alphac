from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _module():
    path = REPO / "scripts" / "audit_tender_offer_reachability.py"
    spec = importlib.util.spec_from_file_location("tender_offer_reachability_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_incomplete_frozen_accuracy_set_does_not_authorize_parser_work() -> None:
    module = _module()
    payload = module.build()
    assert payload["decision"] == "CEILING_NOT_MEASURED"
    assert payload["parser_work_authorized"] is False
    assert payload["return_data_opened"] is False
    assert payload["market_return_files_opened"] == []
    assert payload["return_hypotheses_spent"] == 0
    assert payload["locked_sample"] == {
        "documents": 100,
        "item4_sections_extracted": 94,
        "frozen_accuracy_documents": 30,
        "completed_accuracy_labels": 0,
        "all_label_document_hashes_match": True,
    }
    assert payload["observed_parser_result"]["unique_price_sections"] == 10
    assert payload["observed_parser_result"]["multiple_price_sections"] == 70
    assert payload["observed_parser_result"]["resolved_recommendation_sections"] == 21
    assert payload["content_hash"] == module.content_hash(payload)


def test_persisted_reachability_result_matches_current_frozen_inputs() -> None:
    module = _module()
    assert json.loads(module.OUT.read_text()) == module.build()
