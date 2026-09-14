"""Audit active historical session coverage; no strategy signals or returns."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from alphaforge.core.calendar import calendar_for
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass

ROOT = Path(__file__).resolve().parents[1]
PROD = Path("/Users/arhancanli/alphaforge")
SOURCE = ROOT / "evidence/alphamax-2022-membership-scope-20260913/active_intervals.parquet"
OUT = ROOT / "evidence/alphamax-2022-grid-20260913"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ms(value):
    return int(value.timestamp() * 1000)


def main():
    OUT.mkdir(exist_ok=False)
    membership = pd.read_parquet(SOURCE)
    start, end = 1577836800000, 1672531200000
    grid = np.array(
        calendar_for(AssetClass.EQUITY).expected_bar_opens(start, end, Timeframe.D1), dtype=np.int64
    )
    rows, gaps = [], []
    bindings = {str(SOURCE): sha(SOURCE), str(Path(__file__)): sha(Path(__file__))}
    for iid, intervals in membership.groupby("instrument_id"):
        active = np.zeros(len(grid), dtype=bool)
        for interval in intervals.itertuples():
            active |= (grid >= ms(interval.effective_from)) & (
                grid < (ms(interval.effective_to) if pd.notna(interval.effective_to) else end)
            )
        expected = grid[active]
        frames = []
        for year in [2020, 2021, 2022]:
            path = (
                PROD
                / "data/lake/ohlcv_1d"
                / f"instrument_id={iid}"
                / f"year={year}"
                / "data.parquet"
            )
            if path.exists():
                bindings[str(path)] = sha(path)
                frames.append(pd.read_parquet(path, columns=["ts_open", "quality_flags"]))
        frame = (
            pd.concat(frames, ignore_index=True)
            if frames
            else pd.DataFrame(columns=["ts_open", "quality_flags"])
        )
        timestamps = (
            pd.to_datetime(frame.ts_open, utc=True)
            .astype("datetime64[ms, UTC]")
            .astype("int64")
            .to_numpy()
        )
        observed = np.unique(timestamps)
        missing = np.setdiff1d(expected, observed)
        for value in missing:
            kind = (
                "no_partition"
                if not len(observed)
                else "before_first"
                if value < observed[0]
                else "after_last"
                if value > observed[-1]
                else "interior"
            )
            gaps.append(
                {
                    "instrument_id": iid,
                    "ts_open": int(value),
                    "day": str(pd.to_datetime(value, unit="ms").date()),
                    "kind": kind,
                }
            )
        rows.append(
            {
                "instrument_id": iid,
                "expected_active_sessions": len(expected),
                "observed_rows": len(timestamps),
                "duplicate_timestamps": len(timestamps) - len(observed),
                "missing_active_sessions": len(missing),
                "outside_xnys_sessions": len(np.setdiff1d(observed, grid)),
                "nonzero_quality_flags": int((frame.quality_flags.fillna(0) != 0).sum()),
            }
        )
    pd.DataFrame(rows).to_csv(OUT / "instrument_coverage.csv", index=False)
    missing_frame = pd.DataFrame(gaps, columns=["instrument_id", "ts_open", "day", "kind"])
    missing_frame.to_csv(OUT / "missing_sessions.csv", index=False)
    summary = {
        "source_sha256": bindings,
        "scope": "XNYS2020-2022 intersect retained active membership intervals",
        "instruments": len(rows),
        "calendar_sessions": len(grid),
        "expected_active_sessions": sum(r["expected_active_sessions"] for r in rows),
        "missing_active_sessions": len(gaps),
        "duplicates": sum(r["duplicate_timestamps"] for r in rows),
        "outside_calendar_rows": sum(r["outside_xnys_sessions"] for r in rows),
        "gaps_by_kind": missing_frame.groupby("kind").size().to_dict(),
        "prices_corporate_actions_or_historical_availability_certified": False,
        "new_strategy_returns": 0,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "source_sha256"}))
    print(
        pd.DataFrame(rows)
        .sort_values("missing_active_sessions", ascending=False)
        .head(12)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
