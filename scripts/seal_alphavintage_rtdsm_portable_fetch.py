#!/usr/bin/env python3
"""Seal a successful standalone RTDSM fetch against AlphaVintage's local CPI inputs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Final

import pandas as pd

ROOT: Final = Path(__file__).resolve().parents[1]
FETCH_SCRIPT: Final = ROOT / "scripts" / "fetch_rtdsm_cpi_portable.py"
OUTPUT: Final = ROOT / "artifacts" / "publication" / "alphavintage_rtdsm_portable_fetch.json"
LOCAL_DIR: Final = ROOT / "data" / "lake_macro_vintage" / "tier2_vintage"
SERIES: Final = ("PCPI", "PCPIX")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _fetch_module():
    spec = importlib.util.spec_from_file_location("portable_rtdsm", FETCH_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load portable RTDSM fetcher")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(fetched_dir: Path) -> dict[str, Any]:
    manifest_path = fetched_dir / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest_body = {key: value for key, value in manifest.items() if key != "content_hash"}
    expected_manifest_hash = f"sha256:{hashlib.sha256(_canonical(manifest_body)).hexdigest()}"
    if manifest.get("content_hash") != expected_manifest_hash:
        raise RuntimeError("Fetched source manifest content hash is invalid")
    cutoff = pd.Timestamp(manifest["vintage_cutoff_inclusive"])
    fetcher = _fetch_module()
    comparisons = []
    for name in SERIES:
        local_path = LOCAL_DIR / f"{name}_vintage_long.parquet"
        fetched_path = fetched_dir / f"{name}_vintage_long.parquet"
        local = pd.read_parquet(local_path)
        local = local[local["vintage_date"] <= cutoff]
        local = local.sort_values(["obs_period", "vintage_date"]).reset_index(drop=True)
        fetched = pd.read_parquet(fetched_path)
        fetched = fetched.sort_values(["obs_period", "vintage_date"]).reset_index(drop=True)
        local_hash = fetcher._table_content_hash(local)
        fetched_hash = fetcher._table_content_hash(fetched)
        comparisons.append(
            {
                "series": name,
                "rows_local_at_cutoff": len(local),
                "rows_fresh_fetch": len(fetched),
                "local_table_content_hash": local_hash,
                "fresh_table_content_hash": fetched_hash,
                "tables_equal": local.equals(fetched),
                "local_source": {
                    "path": str(local_path.relative_to(ROOT)),
                    "sha256": _sha256(local_path),
                },
            }
        )
    passed = all(
        item["tables_equal"]
        and item["rows_local_at_cutoff"] == item["rows_fresh_fetch"]
        and item["local_table_content_hash"] == item["fresh_table_content_hash"]
        for item in comparisons
    )
    document: dict[str, Any] = {
        "schema": "canli.alphac-alphavintage-rtdsm-portable-fetch.v1",
        "author": "Arhan Canli",
        "status": "PASS_PUBLIC_MACRO_COMPONENT_PORTABLE" if passed else "FAIL",
        "passes": passed,
        "execution": {
            "workspace_outside_repository": not fetched_dir.resolve().is_relative_to(ROOT),
            "dependency_environment": "PEP723_UV_ISOLATED_SCRIPT",
            "network_source": "OFFICIAL_PHILADELPHIA_FED_RTDSM",
            "vintage_cutoff_inclusive": manifest["vintage_cutoff_inclusive"],
        },
        "fresh_source_manifest": manifest,
        "comparisons": comparisons,
        "source_bindings": {
            "portable_fetcher": {
                "path": str(FETCH_SCRIPT.relative_to(ROOT)),
                "sha256": _sha256(FETCH_SCRIPT),
            }
        },
        "raw_files_released": False,
        "market_data_component_replayed": False,
        "alphavintage_result_recomputed": False,
        "independent_replication": False,
        "claim_boundary": (
            "This proves portable reacquisition and exact normalized-table equality for the "
            "Philadelphia Fed headline/core CPI vintage inputs through the declared cutoff. It "
            "does not replay licensed IWM/SPY data, recompute AlphaVintage returns, establish "
            "redistribution rights, or constitute independent replication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def validate_published() -> dict[str, Any]:
    document = json.loads(OUTPUT.read_text())
    if document.get("content_hash") != _content_hash(document):
        raise RuntimeError("Published receipt content hash is invalid")
    fetch_binding = document["source_bindings"]["portable_fetcher"]
    if fetch_binding["sha256"] != _sha256(ROOT / fetch_binding["path"]):
        raise RuntimeError("Portable fetcher changed after the receipt")
    for comparison in document["comparisons"]:
        binding = comparison["local_source"]
        if binding["sha256"] != _sha256(ROOT / binding["path"]):
            raise RuntimeError(f"Local CPI source changed: {comparison['series']}")
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetched-dir", type=Path)
    parser.add_argument("--validate-published", action="store_true")
    arguments = parser.parse_args()
    if arguments.validate_published:
        document = validate_published()
    elif arguments.fetched_dir:
        document = build(arguments.fetched_dir.resolve())
        OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    else:
        parser.error("provide --fetched-dir or --validate-published")
    print(f"{document['status']}: {OUTPUT}")
    print(f"content_hash: {document['content_hash']}")
    if not document["passes"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
