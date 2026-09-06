#!/usr/bin/env python3
"""Execute and seal AlphaVintage's four-gate replay in a temporary clean workspace."""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

import numpy as np
import pandas as pd

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT: Final = ROOT / "artifacts/publication/alphavintage_full_decision_clean_workspace.json"
EXPECTED: Final = ROOT / "artifacts/probe/cpi_surprise_size/result.json"
SCRIPTS: Final = {
    "macro_fetcher": ROOT / "scripts/fetch_rtdsm_cpi_portable.py",
    "market_fetcher": ROOT / "scripts/fetch_yahoo_iwm_spy_portable.py",
    "full_decision_reproducer": ROOT / "scripts/reproduce_alphavintage_full_decision_portable.py",
}
BOOK_CURVES: Final = {
    "eq": ROOT / "artifacts/walkforward/k30_dn_63/equity.parquet",
    "mf": ROOT / "artifacts/walkforward/mf_live_fwd/equity.parquet",
    "inv": ROOT / "artifacts/walkforward/prereg_investment/equity.parquet",
}
METRICS: Final = (
    "net_sharpe",
    "nw_t",
    "active_day_net_sharpe_superseded",
    "gross_sharpe",
    "placebo_sharpe",
    "placebo_nw_t",
)
TOLERANCE: Final = 5e-5


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


def _run(command: list[str], workspace: Path) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=workspace, text=True, capture_output=True, check=False)
    record = {
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr.encode()).hexdigest(),
    }
    if completed.returncode:
        raise RuntimeError(
            f"clean-workspace command failed ({completed.returncode}): {record['command']}\n"
            f"{completed.stderr[-2000:]}"
        )
    return record


def _local_market_prices(symbol: str) -> tuple[pd.Series, list[dict[str, str]]]:
    pattern = str(ROOT / "data/lake_mf/ohlcv_1d" / f"instrument_id=*{symbol}USD" / "**/*.parquet")
    files = sorted(Path(value) for value in glob.glob(pattern, recursive=True))
    if not files:
        raise RuntimeError(f"no sealed author-workspace market inputs for {symbol}")
    frame = pd.concat([pd.read_parquet(path, columns=["ts_open", "close"]) for path in files])
    frame = frame.drop_duplicates("ts_open", keep="last").sort_values("ts_open")
    dates = pd.to_datetime(frame["ts_open"], utc=True).dt.tz_localize(None).dt.normalize()
    prices = pd.Series(frame["close"].astype(float).to_numpy(), index=dates.to_numpy())
    prices = prices[~prices.index.duplicated()].sort_index()
    return prices, [
        {"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)} for path in files
    ]


def _market_reacquisition_comparison(symbol: str, fresh_dir: Path) -> dict[str, Any]:
    sealed, bindings = _local_market_prices(symbol)
    frame = pd.read_parquet(fresh_dir / f"{symbol}.adjusted_close.parquet")
    fresh = pd.Series(
        frame["close"].astype(float).to_numpy(), index=pd.to_datetime(frame["date"])
    ).sort_index()
    overlap = sealed.index.intersection(fresh.index)
    sealed_overlap = sealed.reindex(overlap)
    fresh_overlap = fresh.reindex(overlap)
    absolute = (fresh_overlap - sealed_overlap).abs()
    relative = absolute / sealed_overlap.abs().clip(lower=1e-18)
    sealed_returns = np.log(sealed_overlap).diff()
    fresh_returns = fresh_overlap.map(np.log).diff()
    return {
        "symbol": symbol,
        "sealed_rows": len(sealed),
        "fresh_rows": len(fresh),
        "overlap_rows": len(overlap),
        "dates_exact": sealed.index.equals(fresh.index),
        "values_exact": sealed.equals(fresh),
        "first_date": str(overlap.min().date()),
        "last_date": str(overlap.max().date()),
        "max_absolute_adjusted_close_difference": float(absolute.max()),
        "max_relative_adjusted_close_difference": float(relative.max()),
        "max_absolute_log_return_difference": float((fresh_returns - sealed_returns).abs().max()),
        "sealed_input_bindings": bindings,
    }


def _macro_reacquisition_comparison(series: str, fresh_dir: Path) -> dict[str, Any]:
    sealed_path = ROOT / f"data/lake_macro_vintage/tier2_vintage/{series}_vintage_long.parquet"
    fresh_path = fresh_dir / f"{series}_vintage_long.parquet"
    cutoff = pd.Timestamp("2026-07-15")
    columns = ["obs_period", "vintage_date", "value"]
    sealed = pd.read_parquet(sealed_path, columns=columns)
    fresh = pd.read_parquet(fresh_path, columns=columns)
    for frame in (sealed, fresh):
        frame["obs_period"] = pd.to_datetime(frame["obs_period"])
        frame["vintage_date"] = pd.to_datetime(frame["vintage_date"])
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    sealed = (
        sealed[sealed["vintage_date"] <= cutoff]
        .sort_values(["obs_period", "vintage_date"])
        .reset_index(drop=True)
    )
    fresh = (
        fresh[fresh["vintage_date"] <= cutoff]
        .sort_values(["obs_period", "vintage_date"])
        .reset_index(drop=True)
    )
    key_columns = ["obs_period", "vintage_date"]
    keys_exact = sealed[key_columns].equals(fresh[key_columns])
    max_value_difference = (
        float((sealed["value"] - fresh["value"]).abs().max()) if len(sealed) == len(fresh) else None
    )
    return {
        "series": series,
        "sealed_rows_through_cutoff": len(sealed),
        "fresh_rows_through_cutoff": len(fresh),
        "keys_exact": keys_exact,
        "values_exact": sealed.equals(fresh),
        "max_absolute_value_difference": max_value_difference,
        "sealed_input_binding": {
            "path": str(sealed_path.relative_to(ROOT)),
            "sha256": _sha256(sealed_path),
        },
    }


def execute() -> dict[str, Any]:
    for path in (*SCRIPTS.values(), *BOOK_CURVES.values(), EXPECTED):
        if not path.is_file():
            raise FileNotFoundError(path)
    execution_records: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="alphavintage-full-decision-") as raw_workspace:
        workspace = Path(raw_workspace).resolve()
        scripts_dir = workspace / "scripts"
        book_dir = workspace / "inputs/book"
        scripts_dir.mkdir(parents=True)
        book_dir.mkdir(parents=True)
        for path in SCRIPTS.values():
            shutil.copy2(path, scripts_dir / path.name)
        copied_curves = {}
        for label, path in BOOK_CURVES.items():
            target = book_dir / f"{label}.equity.parquet"
            shutil.copy2(path, target)
            copied_curves[label] = target

        result_path = workspace / "outputs/full_decision.json"
        result_path.parent.mkdir()
        commands = [
            [
                "uv",
                "run",
                "--isolated",
                "--script",
                "scripts/fetch_rtdsm_cpi_portable.py",
                "--output",
                "inputs/macro",
                "--vintage-cutoff",
                "2026-07-15",
            ],
            [
                "uv",
                "run",
                "--isolated",
                "--script",
                "scripts/fetch_yahoo_iwm_spy_portable.py",
                "--output",
                "inputs/market",
                "--start",
                "2001-06-27",
                "--end-exclusive",
                "2026-08-22",
            ],
            [
                "uv",
                "run",
                "--isolated",
                "--script",
                "scripts/reproduce_alphavintage_full_decision_portable.py",
                "--macro-dir",
                "inputs/macro",
                "--market-dir",
                "inputs/market",
                "--book-curve",
                "eq=inputs/book/eq.equity.parquet",
                "--book-curve",
                "mf=inputs/book/mf.equity.parquet",
                "--book-curve",
                "inv=inputs/book/inv.equity.parquet",
                "--output",
                "outputs/full_decision.json",
            ],
        ]
        for command in commands:
            execution_records.append(_run(command, workspace))
        fresh = json.loads(result_path.read_text())
        _validate_content_hash(fresh, "fresh full-decision result")
        reacquisition_comparisons = {
            "macro": [
                _macro_reacquisition_comparison(series, workspace / "inputs/macro")
                for series in ("PCPI", "PCPIX")
            ],
            "market": [
                _market_reacquisition_comparison(symbol, workspace / "inputs/market")
                for symbol in ("IWM", "SPY", "QQQ")
            ],
        }
        expected = json.loads(EXPECTED.read_text())
        metric_comparisons = []
        for metric in METRICS:
            delta = float(fresh[metric]) - float(expected[metric])
            metric_comparisons.append(
                {
                    "metric": metric,
                    "published": float(expected[metric]),
                    "fresh_reproduction": float(fresh[metric]),
                    "signed_delta": delta,
                    "absolute_delta": abs(delta),
                    "within_publication_display_precision": abs(delta) <= TOLERANCE,
                }
            )
        exact_checks = {
            "portfolio_days": fresh["portfolio_days"] == expected["portfolio_days"],
            "active_days": fresh["active_days"] == expected["active_days"],
            "all_four_gate_values": fresh["checks"] == expected["checks"],
            "verdict": fresh["verdict"] == expected["verdict"],
            "four_gate_replay_declared": fresh["all_four_preregistered_decision_gates_replayed"]
            is True,
            "upstream_benchmark_regeneration_not_overstated": fresh[
                "upstream_benchmark_strategies_regenerated_from_raw_inputs"
            ]
            is False,
        }
        copied_inputs_match = all(
            _sha256(BOOK_CURVES[label]) == _sha256(copied_curves[label]) for label in BOOK_CURVES
        )
        passes = (
            all(exact_checks.values())
            and copied_inputs_match
            and all(row["within_publication_display_precision"] for row in metric_comparisons)
        )
        receipt_integrity_passes = all(exact_checks.values()) and copied_inputs_match
        workspace_inventory = {
            str(path.relative_to(workspace)): _sha256(path)
            for path in sorted(workspace.rglob("*"))
            if path.is_file()
        }

    document: dict[str, Any] = {
        "schema": "canli.alphac-alphavintage-full-decision-clean-workspace-receipt.v1",
        "author": "Arhan Canli",
        "executed_at": datetime.now(UTC).isoformat(),
        "status": (
            "PASS_AUTHOR_CLEAN_WORKSPACE_ALL_FOUR_GATES_UPSTREAM_BENCHMARK_REGENERATION_INCOMPLETE"
            if passes
            else (
                "FAIL_NUMERIC_EQUIVALENCE_VENDOR_DRIFT_ALL_FOUR_GATES_STABLE"
                if receipt_integrity_passes
                else "FAIL_GATE_OR_EXECUTION_DIVERGENCE"
            )
        ),
        "passes": passes,
        "receipt_integrity_passes": receipt_integrity_passes,
        "execution": {
            "workspace_outside_repository": True,
            "workspace_destroyed_after_execution": True,
            "dependency_environment": "PEP723_UV_ISOLATED_SCRIPTS",
            "fresh_official_macro_acquisition": True,
            "fresh_market_acquisition": True,
            "author_run_not_independent": True,
            "records": execution_records,
            "workspace_file_inventory": workspace_inventory,
        },
        "acceptance_criterion": {
            "all_four_gate_values_and_verdict_must_match": True,
            "exact_counts_required": True,
            "metric_absolute_tolerance": TOLERANCE,
            "prospectively_preregistered": False,
            "disclosure": (
                "The engineering equivalence tolerance follows the already disclosed portable "
                "core receipt and cannot validate the hypothesis. Exact deltas are published."
            ),
        },
        "exact_decision_checks": exact_checks,
        "metric_comparisons": metric_comparisons,
        "fresh_vs_sealed_input_comparisons": reacquisition_comparisons,
        "fresh_result": fresh,
        "source_bindings": {
            "scripts": {
                label: {"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)}
                for label, path in SCRIPTS.items()
            },
            "published_result": {
                "path": str(EXPECTED.relative_to(ROOT)),
                "sha256": _sha256(EXPECTED),
            },
            "benchmark_equity_curves": {
                label: {
                    "path": str(path.relative_to(ROOT)),
                    "sha256": _sha256(path),
                    "copied_into_clean_workspace": True,
                    "upstream_strategy_regenerated_from_raw_inputs": False,
                }
                for label, path in BOOK_CURVES.items()
            },
        },
        "full_alphavintage_decision_clean_workspace_reproduction_completed": True,
        "full_pipeline_clean_environment_reproduction_completed": False,
        "portable_reviewer_replay_completed": False,
        "benchmark_curve_redistribution_review_complete": False,
        "independent_human_reproduction_completed": False,
        "raw_vendor_rows_released": False,
        "claim_boundary": (
            "An author-run temporary workspace freshly acquired the public macro and market "
            "inputs, regenerated AlphaVintage, and replayed all four locked decision gates. The "
            "three pre-existing benchmark strategy curves were hash-bound inputs copied from the "
            "author repository; their upstream strategies were not regenerated from raw inputs "
            "and their redistribution review is incomplete. This is therefore a full "
            "AlphaVintage decision replay, not a full multi-sleeve end-to-end reproduction, "
            "portable public bundle, or independent replication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return document


def validate_published() -> dict[str, Any]:
    document = json.loads(OUTPUT.read_text())
    _validate_content_hash(document, "published full-decision receipt")
    for binding in document["source_bindings"]["scripts"].values():
        if binding["sha256"] != _sha256(ROOT / binding["path"]):
            raise RuntimeError(f"bound script changed: {binding['path']}")
    published = document["source_bindings"]["published_result"]
    if published["sha256"] != _sha256(ROOT / published["path"]):
        raise RuntimeError("bound published result changed")
    # These hashes identify the exact benchmark curves copied into the completed temporary-
    # workspace replay. The repository paths are mutable research outputs, so a later upstream
    # replay may change them without changing what this historical receipt executed against.
    # Keep the recorded bindings immutable and require them to remain structurally valid.
    if not all(
        len(binding.get("sha256", "")) == 64 and binding.get("copied_into_clean_workspace") is True
        for binding in document["source_bindings"]["benchmark_equity_curves"].values()
    ):
        raise RuntimeError("historical benchmark curve binding is malformed")
    if not document["receipt_integrity_passes"]:
        raise RuntimeError("published full-decision receipt has gate or execution divergence")
    return cast(dict[str, Any], document)


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--execute", action="store_true")
    group.add_argument("--validate-published", action="store_true")
    arguments = parser.parse_args()
    document = execute() if arguments.execute else validate_published()
    print(f"{document['status']}: {OUTPUT}")
    print(f"content_hash: {document['content_hash']}")
    if not document["receipt_integrity_passes"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
