#!/usr/bin/env python3
"""Seal a fresh AlphaVintage core replay without overstating independence or scope."""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
from pathlib import Path
from typing import Any, Final, cast

import numpy as np
import pandas as pd

ROOT: Final = Path(__file__).resolve().parents[1]
FETCH_SCRIPT: Final = ROOT / "scripts" / "fetch_yahoo_iwm_spy_portable.py"
REPRODUCE_SCRIPT: Final = ROOT / "scripts" / "reproduce_alphavintage_core_portable.py"
EXPECTED_RESULT: Final = ROOT / "artifacts" / "probe" / "cpi_surprise_size" / "result.json"
OUTPUT: Final = ROOT / "artifacts" / "publication" / "alphavintage_core_portable_reproduction.json"
SYMBOLS: Final = ("IWM", "SPY", "QQQ")
METRICS: Final = (
    "net_sharpe",
    "nw_t",
    "active_day_net_sharpe_superseded",
    "gross_sharpe",
    "placebo_sharpe",
    "placebo_nw_t",
)
DISPLAY_PRECISION_TOLERANCE: Final = 5e-5


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _validate_content_hash(document: dict[str, Any], label: str) -> None:
    if document.get("content_hash") != _content_hash(document):
        raise RuntimeError(f"{label} content hash is invalid")


def _local_market_files(symbol: str) -> list[Path]:
    pattern = str(
        ROOT / "data" / "lake_mf" / "ohlcv_1d" / f"instrument_id=*{symbol}USD" / "**" / "*.parquet"
    )
    files = sorted(Path(path) for path in glob.glob(pattern, recursive=True))
    if not files:
        raise RuntimeError(f"no local market files for {symbol}")
    return files


def _local_prices(symbol: str) -> tuple[pd.Series, list[dict[str, str]]]:
    files = _local_market_files(symbol)
    frame = pd.concat([pd.read_parquet(path, columns=["ts_open", "close"]) for path in files])
    frame = frame.drop_duplicates("ts_open", keep="last").sort_values("ts_open")
    dates = pd.to_datetime(frame["ts_open"], utc=True).dt.tz_localize(None).dt.normalize()
    series = pd.Series(frame["close"].astype(float).to_numpy(), index=dates.to_numpy())
    series = series[~series.index.duplicated()].sort_index()
    bindings = [{"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)} for path in files]
    return series, bindings


def _fresh_prices(path: Path) -> pd.Series:
    frame = pd.read_parquet(path)
    return pd.Series(
        frame["close"].astype(float).to_numpy(), index=pd.to_datetime(frame["date"])
    ).sort_index()


def _market_comparison(symbol: str, fetched_dir: Path) -> dict[str, Any]:
    local, bindings = _local_prices(symbol)
    fresh = _fresh_prices(fetched_dir / f"{symbol}.adjusted_close.parquet")
    overlap = local.index.intersection(fresh.index)
    local_overlap = local.reindex(overlap)
    fresh_overlap = fresh.reindex(overlap)
    absolute = (fresh_overlap - local_overlap).abs()
    relative = absolute / local_overlap.abs().clip(lower=1e-18)
    local_returns = np.log(local_overlap).diff()
    fresh_returns = np.log(fresh_overlap).diff()
    return {
        "symbol": symbol,
        "local_rows": len(local),
        "fresh_rows": len(fresh),
        "overlap_rows": len(overlap),
        "dates_exact": local.index.equals(fresh.index),
        "first_date": str(overlap.min().date()),
        "last_date": str(overlap.max().date()),
        "max_absolute_adjusted_close_difference": float(absolute.max()),
        "max_relative_adjusted_close_difference": float(relative.max()),
        "max_absolute_log_return_difference": float((fresh_returns - local_returns).abs().max()),
        "tables_byte_or_value_exact": bool(local.equals(fresh)),
        "local_file_bindings": bindings,
    }


def build(fetched_dir: Path, fresh_result_path: Path) -> dict[str, Any]:
    source_manifest = json.loads((fetched_dir / "source_manifest.json").read_text())
    fresh_result = json.loads(fresh_result_path.read_text())
    _validate_content_hash(source_manifest, "fresh Yahoo source manifest")
    _validate_content_hash(fresh_result, "fresh AlphaVintage core result")
    expected = json.loads(EXPECTED_RESULT.read_text())

    metric_comparisons = []
    for metric in METRICS:
        published = float(expected[metric])
        reproduced = float(fresh_result[metric])
        delta = reproduced - published
        metric_comparisons.append(
            {
                "metric": metric,
                "published": published,
                "fresh_reproduction": reproduced,
                "signed_delta": delta,
                "absolute_delta": abs(delta),
                "within_publication_display_precision": abs(delta) <= DISPLAY_PRECISION_TOLERANCE,
            }
        )

    exact_decision_checks = {
        "portfolio_days": fresh_result["portfolio_days"] == expected["portfolio_days"],
        "active_days": fresh_result["active_days"] == expected["active_days"],
        "verdict": fresh_result["verdict_from_significance_gate"] == expected["verdict"],
        "significance_gate": fresh_result["significance_gate_passes"]
        == expected["checks"]["b_nw_t_ge_1p5"],
        "placebo_gate": fresh_result["placebo_gate_passes"] == expected["checks"]["d_placebo_dead"],
    }
    market_comparisons = [_market_comparison(symbol, fetched_dir) for symbol in SYMBOLS]
    passed = (
        all(exact_decision_checks.values())
        and all(item["within_publication_display_precision"] for item in metric_comparisons)
        and all(item["dates_exact"] for item in market_comparisons)
        and not fresh_result["full_diversification_checks_replayed"]
    )
    document: dict[str, Any] = {
        "schema": "canli.alphac-alphavintage-core-portable-reproduction-receipt.v1",
        "author": "Arhan Canli",
        "status": (
            "PASS_DECISION_REPRODUCTION_NUMERICALLY_NEAR_IDENTICAL_CORE_ONLY" if passed else "FAIL"
        ),
        "passes": passed,
        "execution": {
            "workspace_outside_repository": not fetched_dir.resolve().is_relative_to(ROOT),
            "dependency_environment": "PEP723_UV_ISOLATED_SCRIPTS",
            "macro_source": "OFFICIAL_PHILADELPHIA_FED_RTDSM_FRESH_FETCH",
            "market_source": "YAHOO_FINANCE_FRESH_FETCH",
        },
        "acceptance_criterion": {
            "exact_counts_and_gate_decision_required": True,
            "metric_absolute_tolerance": DISPLAY_PRECISION_TOLERANCE,
            "tolerance_interpretation": "one half-unit at four-decimal publication precision",
            "prospectively_preregistered": False,
            "disclosure": (
                "This engineering equivalence tolerance was selected after observing vendor "
                "drift. It cannot validate the hypothesis or convert this into an independent "
                "replication. Exact deltas are reported so readers need not rely on the label."
            ),
        },
        "exact_decision_checks": exact_decision_checks,
        "metric_comparisons": metric_comparisons,
        "market_input_comparisons": market_comparisons,
        "fresh_source_manifest": source_manifest,
        "fresh_result": fresh_result,
        "source_bindings": {
            "market_fetcher": {
                "path": str(FETCH_SCRIPT.relative_to(ROOT)),
                "sha256": _sha256(FETCH_SCRIPT),
            },
            "core_reproducer": {
                "path": str(REPRODUCE_SCRIPT.relative_to(ROOT)),
                "sha256": _sha256(REPRODUCE_SCRIPT),
            },
            "published_result": {
                "path": str(EXPECTED_RESULT.relative_to(ROOT)),
                "sha256": _sha256(EXPECTED_RESULT),
            },
        },
        "macro_portable_fetch_receipt": (
            "artifacts/publication/alphavintage_rtdsm_portable_fetch.json"
        ),
        "raw_vendor_files_released": False,
        "full_diversification_checks_replayed": False,
        "independent_human_reproduction_completed": False,
        "claim_boundary": (
            "A standalone implementation using freshly reacquired public macro and market inputs "
            "reproduced AlphaVintage's core signal, return, cost, significance and placebo "
            "decision to the exact deltas reported here. Yahoo adjusted histories drifted by tiny "
            "amounts, so this is not byte-exact. The separate three-sleeve diversification checks "
            "were not replayed, raw vendor rows are not redistributed, and this author-run check "
            "is not independent replication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def validate_published() -> dict[str, Any]:
    document = json.loads(OUTPUT.read_text())
    _validate_content_hash(document, "published AlphaVintage core receipt")
    for binding in document["source_bindings"].values():
        if binding["sha256"] != _sha256(ROOT / binding["path"]):
            raise RuntimeError(f"bound source changed: {binding['path']}")
    # The local market paths were mutable comparison inputs at the time of this author-run
    # receipt. Later Yahoo acquisitions must not silently reinterpret that historical run as a
    # replay against today's lake. Their recorded hashes remain part of the sealed receipt, while
    # current-path equality is deliberately not a validity condition.
    if not all(
        len(binding.get("sha256", "")) == 64
        for comparison in document["market_input_comparisons"]
        for binding in comparison["local_file_bindings"]
    ):
        raise RuntimeError("historical local market input binding is malformed")
    if not document["passes"]:
        raise RuntimeError("published AlphaVintage core receipt does not pass")
    return cast(dict[str, Any], document)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetched-dir", type=Path)
    parser.add_argument("--fresh-result", type=Path)
    parser.add_argument("--validate-published", action="store_true")
    arguments = parser.parse_args()
    if arguments.validate_published:
        document = validate_published()
    elif arguments.fetched_dir and arguments.fresh_result:
        document = build(arguments.fetched_dir.resolve(), arguments.fresh_result.resolve())
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    else:
        parser.error("provide --fetched-dir and --fresh-result, or --validate-published")
    print(f"{document['status']}: {OUTPUT}")
    print(f"content_hash: {document['content_hash']}")
    if not document["passes"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
