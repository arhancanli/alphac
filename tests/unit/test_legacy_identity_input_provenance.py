from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "reconstruct_legacy_identity_input_provenance.py"


def _module():
    spec = importlib.util.spec_from_file_location("legacy_identity_provenance", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_identity_sources_are_mapped_without_inventing_row_lineage() -> None:
    module = _module()
    report = module.build()
    assert report["status"] == "PASS_SOURCE_CLASS_MAPPING_EXACT_ROW_LINEAGE_INCOMPLETE"
    assert report["counts"] == {
        "families": 5,
        "identities": 46,
        "mixed_namespace_identities": 10,
        "source_class_mappings_complete": 46,
        "exact_historical_input_row_bindings_complete": 0,
    }
    assert report["source_class_mapping_complete"] is True
    assert report["exact_historical_input_row_lineage_complete"] is False
    assert report["independent_attestation_completed"] is False
    assert report["failures"] == []
    assert all(row["config_hash_recoverable_in_current_ledger"] for row in report["records"])
    assert all(not row["exact_historical_input_row_hashes_available"] for row in report["records"])
    assert report["content_hash"] == module._content_hash(report)


def test_mixed_identities_remain_explicitly_mixed() -> None:
    report = _module().build()
    mixed = [row for row in report["records"] if len(row["instrument_namespaces"]) > 1]
    assert len(mixed) == 10
    assert all(row["instrument_namespaces"] == ["BINANCE", "XUSE"] for row in mixed)
    assert all(
        row["source_classes"]
        == ["BINANCE_EXCHANGE_MARKET_DATA", "MASSIVE_POLYGON_MARKET_DATA"]
        for row in mixed
    )


def test_persisted_legacy_identity_provenance_matches_current_sources() -> None:
    module = _module()
    assert json.loads(module.OUTPUT.read_text()) == module.build()
