"""Scope retained corporate-action repair evidence to AlphaMax inputs; no returns."""

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROD = Path("/Users/arhancanli/alphaforge")
OUT = ROOT / "evidence/alphamax-corporate-action-route-20260913"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(exist_ok=False)
    membership = ROOT / "evidence/alphamax-2022-membership-scope-20260913/active_intervals.parquet"
    ids = set(pd.read_parquet(membership).instrument_id)
    build = PROD / "artifacts/audit/sharadar_corporate_action_corrected_lake.json"
    validation = PROD / "artifacts/audit/sharadar_corrected_corporate_action_validation.json"
    authority = PROD / "artifacts/audit/sharadar_dividend_basis_resolution.json"
    corrected = PROD / json.loads(build.read_text())["corrected_lake"]
    prior = json.loads(validation.read_text())
    failures = pd.DataFrame(prior["split_gate"]["failures"])
    failures = failures[failures.instrument_id.isin(ids)].copy()
    failures["date_utc"] = pd.to_datetime(failures.ex_date, utc=True)
    in_window = failures[(failures.date_utc >= "2020-01-01") & (failures.date_utc < "2023-01-01")]
    failures.to_csv(OUT / "all_date_split_failures_active_names.csv", index=False)
    in_window.to_csv(OUT / "window_split_failures.csv", index=False)
    columns = [
        "instrument_id",
        "ts_open",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "n_trades",
        "quality_flags",
    ]
    results = []
    bindings = {str(p): sha(p) for p in [membership, build, validation, authority, Path(__file__)]}
    for iid in sorted(ids):
        for year in [2020, 2021, 2022]:
            rel = Path("ohlcv_1d") / f"instrument_id={iid}" / f"year={year}" / "data.parquet"
            a = PROD / "data/lake" / rel
            b = corrected / rel
            if not a.exists() and not b.exists():
                continue
            equal = False
            if a.exists() and b.exists():
                left = (
                    pd.read_parquet(a, columns=columns)
                    .sort_values("ts_open")
                    .reset_index(drop=True)
                )
                right = (
                    pd.read_parquet(b, columns=columns)
                    .sort_values("ts_open")
                    .reset_index(drop=True)
                )
                try:
                    pd.testing.assert_frame_equal(left, right, check_dtype=False, check_exact=True)
                    equal = True
                except AssertionError:
                    pass
            results.append(
                {
                    "instrument_id": iid,
                    "year": year,
                    "current_exists": a.exists(),
                    "corrected_exists": b.exists(),
                    "economic_rows_exact_equal": equal,
                }
            )
            for p in [a, b]:
                if p.exists():
                    bindings[str(p)] = sha(p)
    pd.DataFrame(results).to_csv(OUT / "price_partition_comparison.csv", index=False)
    report = {
        "scope": "Retained333active-window names,2020-2022price records excluding ingestion timestamps",
        "partitions_compared": len(results),
        "equal_partitions": sum(x["economic_rows_exact_equal"] for x in results),
        "differences": [x for x in results if not x["economic_rows_exact_equal"]],
        "prior_global_decision": prior["decision"],
        "prior_dividend_gate_passed": prior["dividend_gate"]["passed"],
        "split_failures_all_dates_active_names": len(failures),
        "split_failures_in_window": len(in_window),
        "window_failure_names": sorted(set(in_window.instrument_id)),
        "source_sha256": bindings,
        "historical_availability_certified": False,
        "new_strategy_returns": 0,
        "replay_ready": False,
    }
    (OUT / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps({k: v for k, v in report.items() if k not in ["source_sha256", "differences"]})
    )
    print(
        in_window[["instrument_id", "ex_date", "classification", "stored_ratio"]].to_string(
            index=False
        )
    )


if __name__ == "__main__":
    main()
