from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "reconstruct_energy_inventory_source_provenance.py"


def _module():
    spec = importlib.util.spec_from_file_location("energy_inventory_provenance", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_energy_inventory_source_mapping_is_evidence_bound_and_narrow() -> None:
    module = _module()
    report = module.build()
    assert report["status"] == "PASS_LOCAL_SOURCE_IDENTITY_RECONSTRUCTED"
    assert report["source_identity"] == "YAHOO_FINANCE_MARKET_DATA"
    assert report["source_mapping_complete"] is True
    assert report["redistribution_rights_established"] is False
    assert report["independent_attestation_completed"] is False
    assert report["loader_binding"]["exact_historical_loader_bytes_proven"] is False
    assert report["failures"] == []
    lake = report["persisted_lake_reconciliation"]
    assert lake["ingestion_timestamp_within_execution_window"] is True
    assert all(row["matches_execution_stdout"] for row in lake["coverage"])
    assert all(row["partition_bindings_valid"] for row in lake["coverage"])
    assert report["content_hash"] == module._content_hash(report)


def test_persisted_energy_inventory_provenance_matches_current_sources() -> None:
    module = _module()
    assert json.loads(module.OUTPUT.read_text()) == module.build()
