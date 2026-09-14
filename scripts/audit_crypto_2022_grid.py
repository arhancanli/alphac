"""Timestamp-only audit of carry extension inputs; no prices, rates or returns."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROD = Path("/Users/arhancanli/alphaforge")
OUT = ROOT / "evidence/crypto-2022-input-grid-20260913"


def main():
    config_path = PROD / "artifacts/walkforward/crypto_carry_wk/walkforward.json"
    config = json.loads(config_path.read_text())["config"]
    member_path = ROOT / "evidence/historical-extension-inputs-20260913/membership_rows.parquet"
    membership = pd.read_parquet(member_path)
    membership = membership[membership.sleeve == "crypto_carry_wk"]
    start = int(pd.Timestamp("2021-01-01", tz="UTC").timestamp() * 1000)
    end = int(pd.Timestamp("2023-01-01", tz="UTC").timestamp() * 1000)
    grid = np.arange(start, end, 3600000, dtype=np.int64)
    hashes = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [config_path, member_path, Path(__file__)]
    }
    rows = []
    gaps = []
    for iid in config["instrument_ids"]:
        active = np.zeros(len(grid), dtype=bool)
        for row in membership[membership.instrument_id == iid].itertuples():
            low = int(row.effective_from.timestamp() * 1000)
            high = int(row.effective_to.timestamp() * 1000) if pd.notna(row.effective_to) else end
            active |= (grid >= low) & (grid < high)
        expected = grid[active]
        for table, col in [("ohlcv", "ts_open"), ("funding", "ts_funding")]:
            frames = []
            for year in [2021, 2022]:
                path = (
                    PROD
                    / "data/lake"
                    / table
                    / f"instrument_id={iid}"
                    / f"year={year}"
                    / "data.parquet"
                )
                if not path.exists():
                    continue
                hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
                cols = [col] if table == "ohlcv" else [col, "available_at"]
                frames.append(pd.read_parquet(path, columns=cols))
            data = (
                pd.concat(frames, ignore_index=True)
                if frames
                else pd.DataFrame(columns=[col, "available_at"])
            )
            timestamps = data[col].astype("int64").to_numpy()
            duplicates = int(pd.Series(timestamps).duplicated().sum())
            missing = (
                np.setdiff1d(expected, timestamps)
                if table == "ohlcv"
                else np.array([], dtype=np.int64)
            )
            unique = np.sort(np.unique(timestamps))
            wide_gaps = np.diff(unique) > 8 * 3600000
            late = 0
            max_lag = None
            if table == "funding" and len(data):
                available = data.available_at.astype("int64").to_numpy()
                lag = available - timestamps
                late = int((lag > 0).sum())
                max_lag = int(lag.max())
            for t in missing:
                gaps.append({"instrument": iid, "table": table, "missing_active_hour": int(t)})
            rows.append(
                {
                    "instrument": iid,
                    "table": table,
                    "rows": len(data),
                    "duplicate_timestamps": duplicates,
                    "active_expected_hours": len(expected),
                    "missing_active_hourly_marks": len(missing),
                    "observed_gaps_over_8_hours": int(wide_gaps.sum())
                    if table == "funding"
                    else None,
                    "funding_available_after_event_rows": late if table == "funding" else None,
                    "funding_max_available_lag_ms": max_lag,
                }
            )
    pd.DataFrame(rows).to_csv(OUT / "instrument_checks.csv", index=False)
    pd.DataFrame(gaps).to_csv(OUT / "missing_active_hours.csv", index=False)
    (OUT / "manifest.json").write_text(
        json.dumps(
            {
                "source_sha256": hashes,
                "scope": "2021training coverage and2022evaluation; unchanged6048hour training. "
                "Funding >8hour gaps diagnostic only, not certified cadence. "
                "This script opens timestamps only.",
            },
            indent=2,
        )
        + "\n"
    )
    f = pd.DataFrame(rows)
    print(
        f.groupby("table")[
            [
                "rows",
                "duplicate_timestamps",
                "active_expected_hours",
                "missing_active_hourly_marks",
                "observed_gaps_over_8_hours",
                "funding_available_after_event_rows",
            ]
        ]
        .sum()
        .to_string()
    )
    print(
        f[(f.missing_active_hourly_marks > 0) | (f.duplicate_timestamps > 0)].to_string(index=False)
    )


if __name__ == "__main__":
    main()
