"""Audit acquired ETF session coverage and impute raw prices per vendor documentation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import exchange_calendars as xcals
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-sharadar-direct-20260912"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    acquisition = json.loads((OUT / "acquisition.json").read_text())
    assert acquisition["all_requests_complete"]
    for receipt in acquisition["responses"]:
        assert sha(OUT / (receipt["table"] + "_" + receipt["symbol"] + ".csv")) == receipt["sha256"]
    metadata_path = ROOT / "evidence/alphatrend-raw-inventory-20260912/archive_metadata.json"
    metadata = json.loads(metadata_path.read_text())["matching_ticker_metadata"]
    first_dates = {r["ticker"]: r["firstpricedate"] for r in metadata}
    cal = xcals.get_calendar("XNYS", start="2000-01-01", end="2030-12-31")
    summaries, raw_frames, action_frames = [], [], []
    for receipt in acquisition["responses"]:
        symbol = receipt["symbol"]
        frame = pd.read_parquet(OUT / (receipt["table"] + "_" + symbol + ".parquet"))
        if receipt["table"] == "actions":
            action_frames.append(frame)
            continue
        dates = pd.DatetimeIndex(pd.to_datetime(frame.date))
        start = max(pd.Timestamp("2003-01-01"), pd.Timestamp(first_dates[symbol]))
        expected = cal.sessions_in_range(start, "2026-09-11")
        missing = expected.difference(dates)
        extra = dates.difference(expected)
        columns = ["open", "high", "low", "close", "closeunadj", "closeadj", "volume"]
        numeric = frame[columns].to_numpy(dtype=float)
        if not np.isfinite(numeric).all() or not (frame[columns[:-1]] > 0).all().all():
            raise ValueError("Nonfinite or nonpositive acquired price")
        if not (frame.volume >= 0).all():
            raise ValueError("Negative volume")
        factor = frame.closeunadj / frame.close
        raw = pd.DataFrame(
            {
                "symbol": symbol,
                "session_ms": pd.to_datetime(frame.date).dt.as_unit("ms").astype("int64"),
                "open": frame.open * factor,
                "high": frame.high * factor,
                "low": frame.low * factor,
                "close": frame.closeunadj,
                "volume": frame.volume / factor,
            }
        )
        raw["ohlc_valid"] = (raw.low <= raw[["open", "close"]].min(axis=1)) & (
            raw[["open", "close"]].max(axis=1) <= raw.high
        )
        # Check arithmetic invariant without asserting vendor tick/volume accuracy.
        assert np.allclose(
            raw.close * raw.volume, frame.close * frame.volume, rtol=1e-12, atol=1e-8
        )
        raw_frames.append(raw)
        summaries.append(
            {
                "symbol": symbol,
                "rows": len(frame),
                "first": str(dates.min().date()),
                "last": str(dates.max().date()),
                "expected_sessions": len(expected),
                "missing_sessions": [str(d.date()) for d in missing],
                "unexpected_sessions": [str(d.date()) for d in extra],
                "invalid_ohlc_rows": int((~raw.ohlc_valid).sum()),
                "zero_volume_rows": int(raw.volume.eq(0).sum()),
            }
        )
    raw = pd.concat(raw_frames, ignore_index=True).sort_values(["symbol", "session_ms"])
    raw.to_parquet(OUT / "imputed_raw_ohlcv.parquet", index=False)
    actions = pd.concat(action_frames, ignore_index=True)
    actions.to_parquet(OUT / "vendor_actions.parquet", index=False)
    sip_path = ROOT / "evidence/alphatrend-history-bridge-20260912/raw_history.parquet"
    sip = pd.read_parquet(sip_path)
    overlap = raw.merge(
        sip, on=["symbol", "session_ms"], suffixes=("_sharadar", "_sip"), validate="one_to_one"
    )
    overlap["close_difference_bps"] = (overlap.close_sharadar / overlap.close_sip - 1) * 10000
    overlap.to_parquet(OUT / "sip_overlap.parquet", index=False)
    result = {
        "price_rows": len(raw),
        "action_rows": len(actions),
        "symbols": len(summaries),
        "per_symbol": summaries,
        "missing_sessions_total": sum(len(r["missing_sessions"]) for r in summaries),
        "unexpected_sessions_total": sum(len(r["unexpected_sessions"]) for r in summaries),
        "invalid_ohlc_total": sum(r["invalid_ohlc_rows"] for r in summaries),
        "zero_volume_total": sum(r["zero_volume_rows"] for r in summaries),
        "sip_overlap_rows": len(overlap),
        "max_abs_sip_close_difference_bps": float(overlap.close_difference_bps.abs().max()),
        "action_types": {str(k): int(v) for k, v in actions.action.value_counts().items()},
        "raw_price_formula": "OHL*closeunadj/close; C=closeunadj; V=volume*close/closeunadj",
        "source": "https://sharadar.com/docs/faqs",
        "historical_point_in_time_provenance_established": False,
        "runtime_ready": False,
        "new_hypotheses": 0,
        "union_hypotheses": 238,
        "bindings": {
            str(p): sha(p)
            for p in [Path(__file__), metadata_path, sip_path, OUT / "acquisition.json"]
        },
    }
    with (OUT / "audit.json").open("x") as f:
        json.dump(result, f, indent=2, sort_keys=True)
        f.write("\n")
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ["per_symbol", "bindings"]}, indent=2
        )
    )


if __name__ == "__main__":
    main()
