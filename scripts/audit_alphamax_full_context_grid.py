"""Full declared context coverage against explicitly modeled latest listing boundaries."""

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
SOURCE = ROOT / "evidence/alphamax-warmup-dependencies-20260913"
OUT = ROOT / "evidence/alphamax-full-context-grid-20260913"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(exist_ok=False)
    dep = json.loads((SOURCE / "summary.json").read_text())
    metadata_path = SOURCE / "instrument_versions.json"
    assert sha(metadata_path) == dep["metadata_snapshot_sha256"]
    metadata = json.loads(metadata_path.read_text())
    latest = {row["instrument_id"]: row for row in metadata}
    build = PROD / "artifacts/audit/sharadar_corporate_action_corrected_lake.json"
    lake = PROD / json.loads(build.read_text())["corrected_lake"]
    start = int(pd.Timestamp(dep["shared_context_start"], tz="UTC").timestamp() * 1000)
    end = 1672531200000
    grid = np.array(
        calendar_for(AssetClass.EQUITY).expected_bar_opens(start, end, Timeframe.D1), dtype=np.int64
    )
    bindings = {
        str(p): sha(p) for p in [SOURCE / "summary.json", metadata_path, build, Path(__file__)]
    }
    rows, gaps = [], []
    for iid, meta in sorted(latest.items()):
        low = max(start, meta["listed_ts"])
        high = min(end, meta["delisted_ts"] or end)
        expected = grid[(grid >= low) & (grid < high)]
        frames = []
        for year in range(2010, 2023):
            path = lake / "ohlcv_1d" / f"instrument_id={iid}" / f"year={year}" / "data.parquet"
            if path.exists():
                bindings[str(path)] = sha(path)
                frames.append(pd.read_parquet(path, columns=["ts_open"]))
        if frames:
            frame = pd.concat(frames, ignore_index=True)
            timestamps = frame.ts_open.astype("datetime64[ms, UTC]").astype("int64").to_numpy()
            timestamps = timestamps[(timestamps >= start) & (timestamps < end)]
        else:
            timestamps = np.array([], dtype=np.int64)
        observed = np.unique(timestamps)
        missing = np.setdiff1d(expected, observed)
        for ts in missing:
            kind = (
                "no_history"
                if not len(observed)
                else "before_first"
                if ts < observed[0]
                else "after_last"
                if ts > observed[-1]
                else "interior"
            )
            gaps.append(
                {
                    "instrument_id": iid,
                    "ts_open": int(ts),
                    "date": str(pd.to_datetime(ts, unit="ms").date()),
                    "kind": kind,
                }
            )
        rows.append(
            {
                "instrument_id": iid,
                "expected_sessions": len(expected),
                "observed_sessions": len(observed),
                "missing_sessions": len(missing),
                "duplicate_timestamps": len(timestamps) - len(observed),
                "observations_outside_modeled_listing": len(np.setdiff1d(observed, expected)),
                "listed_ts": meta["listed_ts"],
                "delisted_ts": meta["delisted_ts"],
            }
        )
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT / "instrument_coverage.csv", index=False)
    missing_frame = pd.DataFrame(gaps, columns=["instrument_id", "ts_open", "date", "kind"])
    missing_frame.to_csv(OUT / "missing_sessions.csv", index=False)
    summary = {
        "start": start,
        "end": end,
        "context_sessions": len(grid),
        "instrument_count": len(rows),
        "expected_sessions": int(frame.expected_sessions.sum()),
        "missing_sessions": len(gaps),
        "duplicates": int(frame.duplicate_timestamps.sum()),
        "gaps_by_kind": missing_frame.groupby("kind").size().to_dict(),
        "observations_outside_modeled_listing": int(
            frame.observations_outside_modeled_listing.sum()
        ),
        "listing_policy": "Latest retained metadata, modeled retrospective boundaries, not historical observation evidence.",
        "source_sha256": bindings,
        "new_strategy_returns": 0,
        "replay_ready": False,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "source_sha256"}))
    print(
        frame[frame.missing_sessions > 0]
        .sort_values("missing_sessions", ascending=False)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
