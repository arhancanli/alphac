"""Stream data-quality counts only; no strategy P&L or return selection."""

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import databento as db
import databento_dbn as dbn
import numpy as np
import pandas as pd


def audit(path):
    counts = Counter()
    instruments = set()
    minimum, maximum = None, None
    day = path.name[:10]
    window_start = datetime.fromisoformat(day + "T12:05:00").replace(
        tzinfo=ZoneInfo("America/New_York")
    )
    window_end = window_start + timedelta(minutes=1)
    event_counts = {crop: Counter() for crop in ("ZC", "ZW", "ZS")}
    for frame in db.DBNStore.from_file(path).to_df(count=100000):
        counts["records"] += len(frame)
        instruments.update(frame["instrument_id"].unique().tolist())
        minimum = (
            frame["ts_event"].min() if minimum is None else min(minimum, frame["ts_event"].min())
        )
        maximum = (
            frame["ts_event"].max() if maximum is None else max(maximum, frame["ts_event"].max())
        )
        bid, ask = frame["bid_px_00"], frame["ask_px_00"]
        finite = np.isfinite(bid) & np.isfinite(ask)
        valid = (
            finite & (bid > 0) & (ask > bid) & (frame["bid_sz_00"] > 0) & (frame["ask_sz_00"] > 0)
        )
        counts["two_sided_positive_uncrossed"] += int(valid.sum())
        counts["missing_or_nonfinite_top"] += int((~finite).sum())
        counts["locked_or_crossed_top"] += int((finite & (ask <= bid)).sum())
        counts["receive_precedes_event"] += int(
            (pd.Series(frame.index, index=frame.index) < frame["ts_event"]).sum()
        )
        in_window = (frame["ts_event"] >= window_start) & (frame["ts_event"] < window_end)
        flags = frame["flags"].astype("uint64")
        usable = (
            valid
            & ((flags & dbn.F_LAST) != 0)
            & ((flags & (dbn.F_BAD_TS_RECV | dbn.F_MAYBE_BAD_BOOK | dbn.F_SNAPSHOT)) == 0)
        )
        for crop in event_counts:
            selected = in_window & frame["symbol"].str.match(
                "^" + crop + "[FGHJKMNQUVXZ][0-9]{1,2}$", na=False
            )
            event_counts[crop]["records"] += int(selected.sum())
            event_counts[crop]["valid_end_of_event_unflagged_rows"] += int(
                (selected & usable).sum()
            )
        for flag, number in [
            ("bad_ts_recv", dbn.F_BAD_TS_RECV),
            ("maybe_bad_book", dbn.F_MAYBE_BAD_BOOK),
            ("snapshot", dbn.F_SNAPSHOT),
        ]:
            counts[flag] += int(((frame["flags"].astype("uint64") & number) != 0).sum())
    return {
        "file": path.name,
        "counts": dict(counts),
        "instruments": len(instruments),
        "event_start": str(minimum),
        "event_end": str(maximum),
        "scheduled_window_start": window_start.isoformat(),
        "scheduled_window_end": window_end.isoformat(),
        "scheduled_window_counts": {crop: dict(counts) for crop, counts in event_counts.items()},
        "window_is_diagnostic_not_verified_report_availability": True,
        "execution_quality_passed": False,
        "scope": (
            "row-level diagnostics only; event-window continuity "
            "and contract eligibility not certified"
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    rows = []
    for path in sorted(args.directory.glob("*-mbp-10.dbn.zst")):
        rows.append(audit(path))
        print(path.name + " audited", flush=True)
    (args.directory / "depth-quality.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(json.dumps(rows))


if __name__ == "__main__":
    main()
