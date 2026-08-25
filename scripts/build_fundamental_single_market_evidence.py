#!/usr/bin/env python3
"""Measure execution-cost stress and ADV-scaled capacity from preserved fill records."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parent.parent
IDENTITY: Final[str] = "1d2924f28fe31a9a"
RUN: Final[Path] = REPO / "artifacts" / "walkforward" / "single_gross_profitability"
MARKET_ROOT: Final[Path] = REPO / "data" / "lake_sharadar" / "ohlcv_1d"
OUT: Final[Path] = REPO / "artifacts" / "probe" / "fundamental_single_replays" / IDENTITY
ANNUALIZATION: Final[int] = 365
PARTICIPATION_LEVELS: Final[dict[str, float]] = {
    "1bp": 0.0001,
    "5bp": 0.0005,
    "10bp": 0.001,
    "1pct": 0.01,
}
CANDIDATES: Final[dict[str, str]] = {
    "single_gross_profitability": "1d2924f28fe31a9a",
    "single_book_to_price": "a238c1a5ecc5d1e3",
    "single_earnings_yield": "e86109044ab18734",
    "single_sales_to_price": "2d966892fb5db520",
    "single_operating_margin": "e5f48adc25065ce9",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _sharpe(returns: pd.Series) -> float:
    deviation = float(returns.std(ddof=1))
    return float(returns.mean() / deviation * math.sqrt(ANNUALIZATION))


def capacity_summary(
    fill_evidence: pd.DataFrame,
    *,
    levels: dict[str, float] = PARTICIPATION_LEVELS,
) -> dict[str, Any]:
    required = {"ts", "prior_equity", "raw_notional", "adv_quote"}
    missing = required - set(fill_evidence)
    if missing:
        raise ValueError(f"capacity input is missing columns: {sorted(missing)}")
    output: dict[str, Any] = {}
    missing_adv = fill_evidence["adv_quote"].isna() | (fill_evidence["adv_quote"] <= 0)
    output["fill_observations"] = len(fill_evidence)
    output["fills_missing_point_in_time_adv"] = int(missing_adv.sum())
    output["missing_adv_treatment"] = "ZERO_CAPACITY_FAIL_CLOSED"
    for name, participation in levels.items():
        limits = (
            fill_evidence["prior_equity"]
            * participation
            * fill_evidence["adv_quote"]
            / fill_evidence["raw_notional"]
        ).where(~missing_adv, 0.0)
        daily = limits.groupby(fill_evidence["ts"]).min()
        output[f"p05_usd_at_{name}_adv"] = float(daily.quantile(0.05))
        output[f"median_usd_at_{name}_adv"] = float(daily.median())
    return output


def _load_fills(run: Path = RUN) -> pd.DataFrame:
    paths = sorted((run / "legs").glob("*/fills.parquet"))
    if len(paths) != 86:
        raise ValueError(f"expected 86 preserved legs, found {len(paths)}")
    fills = pd.concat(
        [
            pd.read_parquet(
                path,
                columns=[
                    "ts",
                    "instrument_id",
                    "qty",
                    "price",
                    "notional",
                    "fee",
                    "reason",
                ],
            )
            for path in paths
        ],
        ignore_index=True,
    )
    if fills.empty or fills["instrument_id"].isna().any():
        raise ValueError("preserved fills are empty or malformed")
    return fills


def _market_for_symbol(
    symbol: str, minimum_year: int, maximum_year: int
) -> tuple[pd.DataFrame, list[Path]]:
    root = MARKET_ROOT / f"instrument_id={symbol}"
    paths = [
        root / f"year={year}" / "data.parquet"
        for year in range(minimum_year - 1, maximum_year + 1)
    ]
    paths = [path for path in paths if path.is_file()]
    if not paths:
        return pd.DataFrame(), []
    frame = pd.concat(
        [
            pd.read_parquet(
                path,
                columns=["ts_open", "open", "close", "volume", "quote_volume"],
            )
            for path in paths
        ],
        ignore_index=True,
    )
    timestamps = pd.to_datetime(frame["ts_open"], utc=True)
    if getattr(timestamps.dtype, "unit", None) != "ms":
        timestamps = timestamps.dt.as_unit("ms")
    frame["ts"] = timestamps.astype("int64")
    quote = frame["quote_volume"].astype(float)
    fallback = frame["close"].astype(float) * frame["volume"].astype(float)
    frame["dollar_volume"] = quote.where(np.isfinite(quote) & (quote > 0), fallback)
    frame = frame.sort_values("ts").drop_duplicates("ts", keep="last")
    frame["adv_quote"] = (
        frame["dollar_volume"].shift(1).rolling(21, min_periods=10).median()
    )
    return frame.set_index("ts"), paths


def build_evidence(
    run_name: str = "single_gross_profitability",
    identity: str = IDENTITY,
) -> dict[str, Any]:
    run = REPO / "artifacts" / "walkforward" / run_name
    fills = _load_fills(run)
    equity_frame = pd.read_parquet(run / "equity.parquet").sort_values("ts")
    equity = pd.Series(
        equity_frame["equity"].to_numpy(dtype=float),
        index=equity_frame["ts"].to_numpy(dtype=np.int64),
    )
    original_returns = equity.pct_change().dropna()
    years = pd.to_datetime(fills["ts"], unit="ms", utc=True).dt.year
    minimum_year = int(years.min())
    maximum_year = int(years.max())
    rows: list[pd.DataFrame] = []
    source_paths: set[Path] = set()
    for symbol, selected in fills.groupby("instrument_id", sort=True):
        market, paths = _market_for_symbol(str(symbol), minimum_year, maximum_year)
        source_paths.update(paths)
        joined = selected.merge(
            market[["open", "adv_quote"]],
            left_on="ts",
            right_index=True,
            how="left",
        )
        rows.append(joined)
    evidence = pd.concat(rows, ignore_index=True)
    prior_timestamps = np.searchsorted(equity.index.to_numpy(), evidence["ts"], side="left") - 1
    prior_timestamps = np.maximum(prior_timestamps, 0)
    evidence["prior_equity"] = equity.iloc[prior_timestamps].to_numpy(dtype=float)
    invalid_open = evidence["open"].isna() | (evidence["open"] <= 0)
    if invalid_open.any():
        reasons = set(evidence.loc[invalid_open, "reason"])
        if reasons != {"forced_flat"}:
            sample = evidence.loc[
                invalid_open, ["ts", "instrument_id", "price", "reason"]
            ].head(10)
            raise ValueError(
                f"{int(invalid_open.sum())} non-administrative fills lack their exact open: "
                f"{sample.to_dict(orient='records')}"
            )
        evidence.loc[invalid_open, "open"] = evidence.loc[
            invalid_open, "price"
        ].to_numpy(dtype=float)
    evidence["raw_notional"] = evidence["qty"].abs() * evidence["open"]
    evidence["modeled_execution_cost"] = (
        evidence["qty"].abs() * (evidence["price"] - evidence["open"]).abs()
        + evidence["fee"]
    )
    daily_cost = evidence.groupby("ts")["modeled_execution_cost"].sum()
    aligned_cost = daily_cost.reindex(original_returns.index, fill_value=0.0)
    prior_equity = equity.shift(1).reindex(original_returns.index)
    stressed_returns = original_returns - aligned_cost / prior_equity

    capacity = capacity_summary(evidence)
    manifest_rows = [
        {
            "path": str(path.relative_to(REPO)),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(source_paths)
    ]
    manifest_root = hashlib.sha256(
        json.dumps(manifest_rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    result: dict[str, Any] = {
        "schema": "canli.alphac-fundamental-single-market-evidence.v1",
        "evidence_date": "2026-08-22",
        "author": "Arhan Canli",
        "hypothesis_key": identity,
        "run_name": run_name,
        "execution_stress": {
            "definition": (
                "2x the persisted commission, spread, impact, and latency costs; general-"
                "collateral borrow remains at the original 50bp annual setting"
            ),
            "original_annualized_sharpe": _sharpe(original_returns),
            "stressed_annualized_sharpe": _sharpe(stressed_returns),
            "recorded_commission_usd": float(evidence["fee"].sum()),
            "modeled_execution_cost_usd": float(evidence["modeled_execution_cost"].sum()),
            "fills": len(evidence),
            "administrative_forced_flat_fills": int(invalid_open.sum()),
            "forced_flat_reference_rule": (
                "raw reference equals persisted last-close fill price; only taker commission is "
                "stressed, matching BacktestEngine._force_flat"
            ),
        },
        "capacity": capacity,
        "market_input_manifest": {
            "scope": "all OHLCV partitions opened for preserved executed symbols",
            "files": len(manifest_rows),
            "bytes": sum(item["bytes"] for item in manifest_rows),
            "merkle_style_root_sha256": manifest_root,
            "leaves": manifest_rows,
        },
        "verdict": "KILL",
        "claim_boundary": (
            "Capacity is an execution-record scaling estimate, not executable AUM. Missing ADV "
            "is assigned zero capacity. This artifact does not replace the full replay input "
            "manifest or claim live liquidity."
        ),
    }
    result["content_hash"] = _content_hash(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "run_name", nargs="?", default="single_gross_profitability", choices=CANDIDATES
    )
    args = parser.parse_args()
    identity = CANDIDATES[args.run_name]
    result = build_evidence(args.run_name, identity)
    out = REPO / "artifacts" / "probe" / "fundamental_single_replays" / identity
    out.mkdir(parents=True, exist_ok=True)
    (out / "market_evidence.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary = {
        "execution_stress": result["execution_stress"],
        "capacity": result["capacity"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
