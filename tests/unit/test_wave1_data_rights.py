from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "audit_wave1_data_rights.py"


def _module():
    spec = importlib.util.spec_from_file_location("wave1_data_rights", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wave1_raw_vendor_rows_are_excluded_and_sources_are_mapped() -> None:
    module = _module()
    report = module.build()
    assert report["status"] == "PASS_CONSERVATIVE_EXCLUSION"
    assert report["wave1_papers"] == 5
    assert report["source_classes"] == 10
    assert report["raw_vendor_rows_released"] is False
    assert report["failures"] == []
    assert all(not record["bundle_raw_tabular_files"] for record in report["records"])
    assert all(record["source_dependencies"] for record in report["records"])
    alphavintage = next(
        record
        for record in report["records"]
        if record["registry_key"] == "alphavintage_macro_surprise"
    )
    assert alphavintage["consumed_market_symbols"] == ["IWM", "SPY", "QQQ"]
    assert alphavintage["portable_reproduction_status"].startswith("AUTHOR_RUN_CORE_")
    crypto = next(
        record
        for record in report["records"]
        if record["registry_key"] == "alphaforge_crypto_carry"
    )
    assert {item["path"] for item in crypto["derived_objects_withheld"]} == {
        "artifacts/walkforward/crypto_carry_wk/equity.parquet",
        "artifacts/probe/crypto_carry_frozen_current_code_replay/equity.parquet",
    }
    assert all(
        item["public_bundle_path"] is None
        for item in crypto["derived_objects_withheld"]
    )
    assert report["content_hash"] == module._content_hash(report)


def test_published_wave1_rights_audit_matches_current_sources() -> None:
    module = _module()
    assert json.loads(module.OUTPUT.read_text()) == module.build()
