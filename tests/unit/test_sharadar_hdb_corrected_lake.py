from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "build_sharadar_hdb_corrected_lake.py"
RESULT = REPO / "artifacts" / "audit" / "sharadar_hdb_corrected_lake.json"


def _module():
    spec = importlib.util.spec_from_file_location("sharadar_hdb_corrected_lake_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_versioned_lake_quarantines_only_the_exact_zero_marker() -> None:
    module = _module()
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    assert payload["content_hash"] == module._content_hash(payload)
    assert payload["decision"] == "VERSIONED_LAKE_READY_FOR_EXACT_REPLAY"
    assert payload["hypotheses_spent"] == 0
    assert payload["return_data_opened"] is False
    assert payload["correction"]["rows_before"] == 4
    assert payload["correction"]["rows_after"] == 3
    assert payload["correction"]["rows_quarantined"] == 1
    assert payload["correction"]["cash_amount_imputed"] is False
    assert payload["correction"]["other_rows_changed"] is False
    corrected_lake = REPO / payload["corrected_lake"]
    assert all(
        (corrected_lake / dataset).is_dir() and not (corrected_lake / dataset).is_symlink()
        for dataset in ("corporate_actions", "fundamentals", "ohlcv_1d", "universe_membership")
    )

    base = REPO / payload["base_lake"] / module.RELATIVE_PARTITION
    corrected = REPO / payload["corrected_lake"] / module.RELATIVE_PARTITION
    assert module._sha256(base) == payload["correction"]["source_partition_sha256"]
    assert module._sha256(corrected) == payload["correction"]["corrected_partition_sha256"]
    assert base.stat().st_ino != corrected.stat().st_ino

    frame = pq.ParquetFile(corrected).read().to_pandas()
    assert not ((frame["action_type"] == "dividend") & (frame["cash_amount"] <= 0.0)).any()
    august = frame[
        (frame["action_type"] == "dividend")
        & (frame["ex_date"].dt.date.astype(str) == "2025-08-11")
    ]
    assert len(august) == 1
    assert float(august.iloc[0]["cash_amount"]) == 0.751
