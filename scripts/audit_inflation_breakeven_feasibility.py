#!/usr/bin/env python3
"""Audit inflation-breakeven source feasibility without opening any return data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parent.parent
LAKE: Final[Path] = REPO / "data" / "lake_macro_vintage"
META: Final[Path] = LAKE / "meta.json"
ARRIVAL_LOG: Final[Path] = LAKE / "arrival_log.jsonl"
PROTOCOL: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_INFLATION_BREAKEVEN_RELATIVE_VALUE.md"
)
LITERATURE: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_INFLATION_BREAKEVEN_RELATIVE_VALUE.md"
)
OUT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "inflation_breakeven_relative_value" / "result.json"
)
SIGNALS: Final[dict[str, Path]] = {
    maturity: LAKE / "tier1_daily" / f"T{maturity}YIE.parquet"
    for maturity in ("2", "5", "10")
}
CPI: Final[Path] = LAKE / "tier2_vintage" / "PCPI_first_release.parquet"
EXECUTION_ROOTS: Final[tuple[Path, ...]] = (
    REPO / "data" / "lake_fixed_income" / "tips",
    REPO / "data" / "lake_rates" / "tips",
    REPO / "data" / "lake_treasury_securities",
    REPO / "data" / "inflation_swaps",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _next_business_day(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values) + pd.offsets.BDay(1)


def _signal_inventory(path: Path) -> dict[str, Any]:
    frame = pd.read_parquet(path)
    required = ["obs_date", "value", "publication_date"]
    if list(frame.columns) != required:
        raise ValueError(f"unexpected signal schema: {path}")
    dates = pd.to_datetime(frame["obs_date"])
    publications = pd.to_datetime(frame["publication_date"])
    return {
        "path": str(path.relative_to(REPO)),
        "sha256": sha256_file(path),
        "rows": len(frame),
        "first_observation": dates.min().date().isoformat(),
        "last_observation": dates.max().date().isoformat(),
        "unique_dates": bool(dates.is_unique),
        "sorted_dates": bool(dates.is_monotonic_increasing),
        "null_cells": int(frame.isna().sum().sum()),
        "publication_is_next_business_day": bool(
            (publications == _next_business_day(dates)).all()
        ),
    }


def build() -> dict[str, Any]:
    meta = json.loads(META.read_text(encoding="utf-8"))
    available = {row["series"] for row in meta["series"]}
    signal_inventory = {
        maturity: _signal_inventory(path)
        for maturity, path in SIGNALS.items()
        if path.is_file()
    }
    evidence_date = max(row["last_observation"] for row in signal_inventory.values())
    aligned = pd.concat(
        {
            maturity: pd.read_parquet(SIGNALS[maturity]).set_index("obs_date")["value"]
            for maturity in ("5", "10")
        },
        axis=1,
        join="inner",
    )
    cpi = pd.read_parquet(CPI)
    true_cpi = cpi[cpi["is_true_first_release"]]
    # Search only the declared institutional-input roots. Recursively walking the entire market
    # lake is both needlessly expensive and semantically weak: an unrelated filename containing
    # "tips" is not an executable fixed-income data contract.
    execution_files = sorted(
        str(path.relative_to(REPO))
        for root in EXECUTION_ROOTS
        if root.is_dir()
        for path in root.rglob("*")
        if path.is_file()
    )
    arrivals = [
        json.loads(line)
        for line in ARRIVAL_LOG.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    signal_vintage_arrivals = [
        row for row in arrivals if row.get("series") in {"T2YIE", "T5YIE", "T10YIE"}
    ]
    gates = {
        "aligned_5y_10y_signal_at_least_three_years": len(aligned) >= 756,
        "aligned_5y_10y_signal_has_no_nulls": int(aligned.isna().sum().sum()) == 0,
        "all_atlas_maturities_present": {"T2YIE", "T5YIE", "T10YIE"} <= available,
        "historical_signal_vintages_preserved": len(signal_vintage_arrivals) > 1,
        "at_least_300_true_cpi_first_releases": len(true_cpi) >= 300,
        "executable_instrument_history_present": bool(execution_files),
    }
    payload: dict[str, Any] = {
        "schema": "canli.alphac-inflation-breakeven-feasibility.v1",
        "evidence_date": evidence_date,
        "author": "Arhan Canli",
        "stage": "signal_and_execution_source_audit_no_prices_no_returns",
        "decision": "PASS_TO_RETURN_PREREGISTRATION" if all(gates.values()) else "DATA_GATED",
        "return_data_opened": False,
        "market_return_files_opened": [],
        "return_hypotheses_spent": 0,
        "protocol": {
            "path": str(PROTOCOL.relative_to(REPO)),
            "sha256": sha256_file(PROTOCOL),
        },
        "literature_review": {
            "path": str(LITERATURE.relative_to(REPO)),
            "sha256": sha256_file(LITERATURE),
        },
        "source_contract": {
            "meta_path": str(META.relative_to(REPO)),
            "meta_sha256": sha256_file(META),
            "arrival_log_path": str(ARRIVAL_LOG.relative_to(REPO)),
            "arrival_log_sha256": sha256_file(ARRIVAL_LOG),
            "current_snapshot_is_not_historical_vintage_proof": True,
        },
        "signal_inventory": signal_inventory,
        "aligned_5y_10y": {
            "rows": len(aligned),
            "first_observation": pd.Timestamp(aligned.index.min()).date().isoformat(),
            "last_observation": pd.Timestamp(aligned.index.max()).date().isoformat(),
            "null_cells": int(aligned.isna().sum().sum()),
        },
        "cpi_vintage_inventory": {
            "path": str(CPI.relative_to(REPO)),
            "sha256": sha256_file(CPI),
            "rows": len(cpi),
            "true_first_releases": len(true_cpi),
            "first_true_release": pd.Timestamp(true_cpi["publication_date"].min())
            .date()
            .isoformat(),
            "last_true_release": pd.Timestamp(true_cpi["publication_date"].max())
            .date()
            .isoformat(),
        },
        "execution_source_inventory": {
            "declared_roots": [str(path.relative_to(REPO)) for path in EXECUTION_ROOTS],
            "matching_files": execution_files,
            "required_but_absent": [
                "matched_nominal_and_tips_security_identifiers",
                "cashflows_and_index_ratios",
                "executable_prices_or_quotes",
                "bid_ask_and_depth",
                "financing_and_carry_inputs",
                "inflation_swap_history_or_named_alternative",
            ],
        },
        "gates": gates,
        "failed_gates": [name for name, passed in gates.items() if not passed],
        "supersedes_reachability_claim": (
            "OBTAINABLE_FROM_DATA_THIS_REPO_ALREADY_HOLDS is too broad. The held files support "
            "5Y/10Y signal-source depth and vintage CPI, not the complete point-in-time, "
            "instrument-level, executable identity."
        ),
        "claim_boundary": (
            "No sign, horizon, return, Sharpe, drawdown, correlation, capacity, execution "
            "quality, or sleeve-admission claim is authorized."
        ),
    }
    payload["content_hash"] = content_hash(payload)
    return payload


def main() -> int:
    payload = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": payload["decision"], "gates": payload["gates"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
