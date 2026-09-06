from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "seal_alphavintage_rtdsm_portable_fetch.py"


def _module():
    spec = importlib.util.spec_from_file_location("rtdsm_seal", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_published_rtdsm_receipt_is_current_and_fail_closed() -> None:
    module = _module()
    receipt = module.validate_published()
    assert receipt["status"] == "PASS_PUBLIC_MACRO_COMPONENT_PORTABLE"
    assert receipt["passes"] is True
    assert receipt["execution"]["workspace_outside_repository"] is True
    assert len(receipt["comparisons"]) == 2
    assert all(item["tables_equal"] for item in receipt["comparisons"])
    assert receipt["market_data_component_replayed"] is False
    assert receipt["alphavintage_result_recomputed"] is False
    assert receipt["independent_replication"] is False


_CUTOFF = pd.Timestamp("2020-01-01")
_PRE_CUTOFF_ROWS = [
    {"obs_period": pd.Timestamp("2019-01-01"), "vintage_date": pd.Timestamp("2019-02-01"),
     "value": 100.0},
    {"obs_period": pd.Timestamp("2019-01-01"), "vintage_date": pd.Timestamp("2019-03-01"),
     "value": 100.5},
    {"obs_period": pd.Timestamp("2019-02-01"), "vintage_date": pd.Timestamp("2019-03-01"),
     "value": 101.0},
]


def _seal_a_synthetic_receipt(
    module: Any, tmp_path: Path, rows: list[dict[str, Any]]
) -> tuple[Path, Path]:
    """Build a minimal, self-contained sealed receipt + local lake for one series ("PCPI").

    Isolated from the real repo's lake on purpose: it exercises `validate_published`'s slice
    logic against a controlled fixture instead of depending on whatever state the real,
    continuously-backfilled lake happens to be in today.
    """
    local_dir = tmp_path / "lake"
    local_dir.mkdir()
    frame = pd.DataFrame(rows).sort_values(["obs_period", "vintage_date"]).reset_index(drop=True)
    frame.to_parquet(local_dir / "PCPI_vintage_long.parquet")
    fetcher = module._fetch_module()
    slice_hash = fetcher._table_content_hash(frame)
    fetch_script = ROOT / "scripts" / "fetch_rtdsm_cpi_portable.py"
    document: dict[str, Any] = {
        "schema": "canli.alphac-alphavintage-rtdsm-portable-fetch.v1",
        "author": "Arhan Canli",
        "status": "PASS_PUBLIC_MACRO_COMPONENT_PORTABLE",
        "passes": True,
        "execution": {
            "workspace_outside_repository": True,
            "dependency_environment": "PEP723_UV_ISOLATED_SCRIPT",
            "network_source": "OFFICIAL_PHILADELPHIA_FED_RTDSM",
            "vintage_cutoff_inclusive": _CUTOFF.date().isoformat(),
        },
        "fresh_source_manifest": {},
        "comparisons": [
            {
                "series": "PCPI",
                "rows_local_at_cutoff": len(frame),
                "rows_fresh_fetch": len(frame),
                "local_table_content_hash": slice_hash,
                "fresh_table_content_hash": slice_hash,
                "tables_equal": True,
                "local_source": {
                    "path": "data/lake_macro_vintage/tier2_vintage/PCPI_vintage_long.parquet",
                    "sha256": module._sha256(local_dir / "PCPI_vintage_long.parquet"),
                },
            }
        ],
        "source_bindings": {
            "portable_fetcher": {
                "path": str(fetch_script.relative_to(ROOT)),
                "sha256": module._sha256(fetch_script),
            }
        },
        "raw_files_released": False,
        "market_data_component_replayed": False,
        "alphavintage_result_recomputed": False,
        "independent_replication": False,
        "claim_boundary": "synthetic fixture for validate_published slice-hash logic",
    }
    document["content_hash"] = module._content_hash(document)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return receipt_path, local_dir


def test_ordinary_post_cutoff_backfill_does_not_fail_validation(tmp_path: Path) -> None:
    """A row appended AFTER the sealed cutoff is an ordinary backfill: it must not fail
    validation, because the frozen pre-cutoff slice the receipt actually vouches for is
    unchanged."""
    module = _module()
    receipt_path, local_dir = _seal_a_synthetic_receipt(module, tmp_path, _PRE_CUTOFF_ROWS)
    backfilled = pd.concat(
        [
            pd.read_parquet(local_dir / "PCPI_vintage_long.parquet"),
            pd.DataFrame(
                [
                    {
                        "obs_period": pd.Timestamp("2020-06-01"),
                        "vintage_date": pd.Timestamp("2020-07-01"),
                        "value": 105.0,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    backfilled.to_parquet(local_dir / "PCPI_vintage_long.parquet")

    document = module.validate_published(output_path=receipt_path, local_dir=local_dir)
    assert document["passes"] is True


def test_changed_pre_cutoff_row_fails_validation_closed(tmp_path: Path) -> None:
    """A row DATED BEFORE the sealed cutoff that no longer matches what was sealed is real
    drift in the evidence the receipt vouches for, and must still fail closed."""
    module = _module()
    receipt_path, local_dir = _seal_a_synthetic_receipt(module, tmp_path, _PRE_CUTOFF_ROWS)
    mutated = pd.read_parquet(local_dir / "PCPI_vintage_long.parquet")
    mutated.loc[0, "value"] = 999.0
    mutated.to_parquet(local_dir / "PCPI_vintage_long.parquet")

    with pytest.raises(RuntimeError, match="pre-cutoff slice changed: PCPI"):
        module.validate_published(output_path=receipt_path, local_dir=local_dir)
