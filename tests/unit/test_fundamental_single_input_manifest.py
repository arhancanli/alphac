from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _module():
    path = REPO / "scripts" / "build_fundamental_single_input_manifest.py"
    spec = importlib.util.spec_from_file_location("fundamental_single_input_manifest_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_partition_aggregation_is_deterministic_and_content_sensitive(tmp_path: Path) -> None:
    module = _module()
    first = tmp_path / "dataset" / "instrument_id=A" / "year=2024" / "data.parquet"
    second = tmp_path / "dataset" / "instrument_id=B" / "year=2025" / "data.parquet"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    left = module.aggregate_partitions([second, first], workers=1)
    right = module.aggregate_partitions([first, second], workers=2)
    assert left == right
    assert left["files"] == 2
    first.write_bytes(b"changed")
    changed = module.aggregate_partitions([first, second], workers=1)
    assert changed["root_sha256"] != left["root_sha256"]


def test_generated_manifest_commits_the_complete_selected_snapshot() -> None:
    path = (
        REPO
        / "artifacts"
        / "probe"
        / "fundamental_single_replays"
        / "1d2924f28fe31a9a"
        / "input_data_manifest.json"
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["summary"] == {
        "partition_bytes": 2_095_594_112,
        "partition_files": 223_185,
    }
    assert manifest["instrument_metadata"]["distinct_instruments"] == 6_820
    assert set(manifest["datasets"]) == set(_module().DATASETS)
    assert manifest["content_hash"].startswith("sha256:")


def test_only_base_or_exact_authorized_corrected_lake_is_accepted(tmp_path: Path) -> None:
    module = _module()
    base = module._authorized_data_environment(module.LAKE)
    assert base["kind"] == "FROZEN_ORIGINAL_SHARADAR_LAKE"

    correction = json.loads(module.CORRECTED_LAKE_MANIFEST.read_text())
    corrected = module._authorized_data_environment(module.REPO / correction["corrected_lake"])
    assert corrected["versioned_correction_content_hash"] == correction["content_hash"]
    assert corrected["cash_amount_imputed"] is False
    assert corrected["rows_quarantined"] == 1

    arbitrary = tmp_path / "data" / "lake_sharadar"
    arbitrary.mkdir(parents=True)
    with pytest.raises(ValueError, match="not the authorized HDB correction"):
        module._authorized_data_environment(arbitrary)
