from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "audit_all_sleeve_data_rights.py"


def _module():
    spec = importlib.util.spec_from_file_location("all_sleeve_data_rights", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_sleeves_exclude_raw_rows_without_claiming_rights_clearance() -> None:
    module = _module()
    report = module.build()
    assert report["status"] == (
        "PASS_RAW_ROW_EXCLUSION_PUBLIC_TERMS_REVIEW_COMPLETE_CLEARANCE_INCOMPLETE"
    )
    assert report["counts"] == {
        "planned_sleeves": 16,
        "audited_sleeves": 16,
        "raw_row_free_bundles": 16,
        "source_mapping_complete": 16,
        "data_license_reviews_complete": 0,
        "public_terms_reviews_complete": 16,
        "external_publication_clearances_complete": 0,
        "policy_source_classes": 10,
    }
    assert report["raw_third_party_rows_released"] is False
    assert report["redistribution_rights_cleared_for_all_sleeves"] is False
    assert report["failures"] == []
    assert all(not record["bundle_raw_input_files"] for record in report["records"])
    assert all(record["source_dependencies"] for record in report["records"])
    assert all(record["source_public_terms_review_complete"] for record in report["records"])
    assert not any(
        record["external_publication_clearance_complete"] for record in report["records"]
    )
    assert not any(record["unresolved_source_dependencies"] for record in report["records"])
    assert report["content_hash"] == module._content_hash(report)


def test_mixed_legacy_namespaces_are_disclosed_instead_of_relabelled() -> None:
    report = _module().build()
    by_key = {record["registry_key"]: record for record in report["records"]}
    for key in ("crypto_defensive", "equity_low_beta", "equity_quality", "equity_value_investment"):
        notes = " ".join(by_key[key]["mapping_notes"])
        assert "BINANCE" in notes and "XUSE" in notes
    vrp_sources = {item["source_key"] for item in by_key["crypto_vrp"]["source_dependencies"]}
    assert vrp_sources == {"BINANCE_EXCHANGE_MARKET_DATA", "DERIBIT_MARKET_DATA"}
    energy_sources = {
        item["source_key"] for item in by_key["energy_inventory"]["source_dependencies"]
    }
    assert energy_sources == {"EIA_PUBLIC_DATA", "YAHOO_FINANCE_MARKET_DATA"}


def test_persisted_all_sleeve_audit_matches_current_sources() -> None:
    module = _module()
    assert json.loads(module.OUTPUT.read_text()) == module.build()
