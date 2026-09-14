"""As-of pair coverage at fixed clocks; no relative prices or return selection."""

import hashlib
import json
from collections import Counter
from pathlib import Path

import databento as db
import databento_dbn as dbn
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "evidence/share-class-quotes-sdk-fix"
PAIRS = [("GOOG", "GOOGL"), ("BRK.A", "BRK.B")]


def latest_state(frame, at):
    """Use latest received row, even when invalid; never search backward for a good quote."""
    if not frame.index.is_monotonic_increasing:
        raise ValueError("unordered receive timestamps")
    pos = frame.index.searchsorted(at, side="right") - 1
    if pos < 0:
        return "missing", None
    row, recv = frame.iloc[pos], frame.index[pos]
    if pd.isna(row.ts_event) or row.ts_event > recv:
        return "timestamp_order", recv
    if at - min(row.ts_event, recv) > pd.Timedelta(seconds=1):
        return "stale", recv
    flags = int(row["flags"])
    if not flags & dbn.F_LAST or flags & (
        dbn.F_BAD_TS_RECV | dbn.F_MAYBE_BAD_BOOK | dbn.F_SNAPSHOT
    ):
        return "flagged_or_incomplete", recv
    if row.action not in ["A", "C", "M"]:
        return "non_book_update", recv
    bid, ask = row.bid_px_00, row.ask_px_00
    if not np.isfinite(bid) or not np.isfinite(ask) or bid <= 0 or ask <= bid:
        return "invalid_prices", recv
    if row.bid_sz_00 <= 0 or row.ask_sz_00 <= 0:
        return "empty_side", recv
    return "valid", recv


def main():
    receipt = json.loads((DIRECTORY / "receipt.json").read_text())
    if receipt["status"] != "COMPLETE":
        raise ValueError("sample acquisition incomplete")
    results = []
    grid = pd.date_range("2025-08-12T14:01:00Z", periods=60, freq="s")
    for request in receipt["requests"]:
        path = DIRECTORY / request["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != request["sha256"]:
            raise ValueError("input hash mismatch")
        frame = db.DBNStore.from_file(path).to_df()
        states = {}
        for symbol in request["parameters"]["symbols"]:
            rows = frame[frame.symbol == symbol]
            if rows.instrument_id.nunique() > 1:
                raise ValueError("ambiguous instrument ID")
            states[symbol] = [latest_state(rows, at) for at in grid]
        pairs = []
        for left, right in PAIRS:
            counts = Counter()
            observations = []
            for at, a, b in zip(grid, states[left], states[right], strict=True):
                reason = "both_valid"
                skew = None
                if a[0] != "valid" or b[0] != "valid":
                    reason = f"{left}:{a[0]}|{right}:{b[0]}"
                else:
                    skew = abs((a[1] - b[1]).value)
                    if skew > 100_000_000:
                        reason = "quote_skew_exceeds_100ms"
                counts[reason] += 1
                observations.append(
                    {"as_of": at.isoformat(), "status": reason, "receive_skew_ns": skew}
                )
            pairs.append(
                {"legs": [left, right], "counts": dict(counts), "observations": observations}
            )
        results.append(
            {
                "dataset": request["parameters"]["dataset"],
                "records": len(frame),
                "records_by_symbol": frame.groupby("symbol").size().to_dict(),
                "pairs": pairs,
            }
        )
    output = {
        "grid_points": 60,
        "max_quote_age_ms": 1000,
        "max_pair_receive_skew_ms": 100,
        "scope": "Feed-local quote coverage only; neither feed is certified SIP NBBO",
        "execution_eligible": False,
        "return_trials": 0,
        "results": results,
    }
    (DIRECTORY / "pair-coverage.json").write_text(json.dumps(output, indent=2) + "\n")
    for r in results:
        print(r["dataset"], r["records"], [(x["legs"], x["counts"]) for x in r["pairs"]])


if __name__ == "__main__":
    main()
