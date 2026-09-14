"""Bind source semantics and cross-check normalized ETF actions; no strategy trial."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from alphaforge.validation.trend_action_normalization import normalize_actions

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evidence/alphatrend-sharadar-direct-20260912"
OUT = ROOT / "evidence/alphatrend-action-validation-20260912"
POLYGON = ROOT / "evidence/alphatrend-action-capture-20260912"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(name, value):
    with (OUT / name).open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def main():
    actions = pd.read_parquet(SOURCE / "vendor_actions.parquet")
    receipts = json.loads((SOURCE / "acquisition.json").read_text())["responses"]
    observed = max(int(pd.Timestamp(r["received_at"]).value // 1_000_000) for r in receipts)
    files = [
        Path(__file__),
        ROOT / "src/alphaforge/validation/trend_action_normalization.py",
        SOURCE / "vendor_actions.parquet",
        SOURCE / "acquisition.json",
        OUT / "actiontypes_json_response.bin",
        *sorted(SOURCE.glob("funds_*.parquet")),
        *sorted(POLYGON.glob("*_dividends.bin")),
    ]
    bindings = {str(p): sha(p) for p in files}
    write(
        "protocol.json",
        {
            "scope": "ACTION_UNITS_AND_PRICE_CONSISTENCY_NO_STRATEGY_RETURNS",
            "split_factor_comparison": "descriptive error; not price-gap-only approval",
            "new_hypotheses": 0,
            "union_hypotheses": 238,
            "bindings": bindings,
        },
    )
    normalized = normalize_actions(actions, observed_ms=observed)
    normalized.to_parquet(OUT / "normalized_actions.parquet", index=False)
    split_checks = []
    dividend_checks = []
    for symbol in sorted(actions.ticker.unique()):
        frame = pd.read_parquet(SOURCE / ("funds_" + symbol + ".parquet")).sort_values("date")
        factor = (frame.closeunadj / frame.close).to_numpy()
        dates = frame.date.to_numpy()
        for row in normalized[normalized.symbol == symbol].itertuples():
            date = pd.Timestamp(row.session_ms, unit="ms").strftime("%Y-%m-%d")
            positions = np.flatnonzero(dates == date)
            if len(positions) != 1 or positions[0] == 0:
                raise ValueError("Missing action-date or prior-session price")
            pos = int(positions[0])
            if row.kind == "split":
                implied = float(factor[pos - 1] / factor[pos])
                split_checks.append(
                    {
                        "symbol": symbol,
                        "date": date,
                        "source_ratio": row.raw_value,
                        "price_factor_ratio": implied,
                        "relative_error_bps": (implied / row.raw_value - 1) * 10000,
                    }
                )
            else:
                dividend_checks.append(
                    {
                        "symbol": symbol,
                        "date": date,
                        "raw_cash": row.raw_value,
                        "source_cash": row.source_value,
                        "raw_cash_to_previous_close": row.raw_value
                        / float(frame.closeunadj.iloc[pos - 1]),
                    }
                )
    pd.DataFrame(split_checks).to_parquet(OUT / "split_checks.parquet", index=False)
    pd.DataFrame(dividend_checks).to_parquet(OUT / "dividend_checks.parquet", index=False)
    comparisons = []
    for path in sorted(POLYGON.glob("*_dividends.bin")):
        body = json.loads(path.read_bytes())
        for record in body["results"]:
            match = [
                r
                for r in dividend_checks
                if r["symbol"] == record["ticker"] and r["date"] == record["ex_dividend_date"]
            ]
            if len(match) != 1:
                raise ValueError("Missing or ambiguous cross-vendor dividend")
            cash = match[0]["raw_cash"]
            comparisons.append(
                {
                    "symbol": record["ticker"],
                    "date": record["ex_dividend_date"],
                    "sharadar_cash": cash,
                    "polygon_cash": record["cash_amount"],
                    "absolute_difference": abs(cash - record["cash_amount"]),
                }
            )
    pd.DataFrame(comparisons).to_parquet(OUT / "polygon_dividend_checks.parquet", index=False)
    result = {
        "normalized_events": len(normalized),
        "splits": len(split_checks),
        "dividends": len(dividend_checks),
        "dividends_rebased": int(
            ((normalized.kind == "dividend") & (normalized.later_split_product != 1)).sum()
        ),
        "max_split_factor_relative_error_bps": max(
            abs(r["relative_error_bps"]) for r in split_checks
        ),
        "max_cash_to_previous_close": max(r["raw_cash_to_previous_close"] for r in dividend_checks),
        "polygon_dividends_matched": len(comparisons),
        "polygon_max_cash_difference": max(r["absolute_difference"] for r in comparisons),
        "lifecycle_rows_preserved_separately": int(
            (~actions.action.isin(["split", "dividend"])).sum()
        ),
        "payment_dates_available": False,
        "historical_observation_times_proven": False,
        "engine_integrated": False,
        "new_hypotheses": 0,
        "union_hypotheses": 238,
    }
    for name, digest in bindings.items():
        assert sha(Path(name)) == digest
    write("result.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
