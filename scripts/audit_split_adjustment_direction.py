#!/usr/bin/env python3
"""Measure, split by split, what the shared adjusted-close engine does across every ex-date.

WHY. `alphaforge.features.library.equity_price.adjusted_close` folds a split into every pre-ex
bar by multiplying by the stored ``ratio``; its own tests encode a 2-for-1 as ``ratio = 0.5``
(old shares per new). Every lake on this machine stores the vendor's factor, new shares per old
(Apple's 2020 4-for-1 is ``4.0`` in data/lake, data/lake_sharadar and the corrected version).
Under the engine that turns a raw ex-date move that should be neutralized into one of DOUBLE
the size in log terms: Apple's adjusted close goes 1,996.92 -> 129.04 across 2020-08-31.
`eq_mom_252_21`, the only alpha of both live equity walk-forwards, reads that panel.

This audit does not fix anything. For every split in a lake it loads the instrument's daily
bars once, runs the engine as the features do (split-only), and classifies the adjusted ex-date
jump against the raw one:

  NEUTRALIZED  |adjusted jump| < 0.10                      the engine did its job
  DOUBLED      adjusted jump within 15 percent of 2 x raw  the factor was applied inverted
  UNCHANGED    adjusted jump within 15 percent of raw      the split was not applied at all
  OTHER        anything else (a tiny split, a gap, a halt)
  UNDETERMINED no bar on either side of the ex-date

Output: artifacts/audit/split_adjustment_direction.json, content-hashed, per lake.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from alphaforge.core.time import Timeframe  # noqa: E402
from alphaforge.data.store.lake import LakePaths  # noqa: E402
from alphaforge.data.store.reader import PITDataReader  # noqa: E402
from alphaforge.features.library.equity_price import adjusted_close  # noqa: E402

OUTPUT = REPO / "artifacts" / "audit" / "split_adjustment_direction.json"
DAY_MS = Timeframe.D1.ms


def _content_hash(document: dict[str, Any]) -> str:
    body = {k: v for k, v in document.items() if k != "content_hash"}
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def _splits(lake: Path) -> pd.DataFrame:
    frames = []
    for path in sorted(
        glob.glob(str(lake / "corporate_actions" / "instrument_id=*" / "year=*" / "data.parquet"))
    ):
        table = pq.ParquetFile(path).read()
        frame = table.to_pandas()
        frame = frame[frame["action_type"] == "split"]
        if not frame.empty:
            frames.append(
                frame[
                    [
                        "instrument_id",
                        "ex_date",
                        "available_at",
                        "ratio",
                        "cash_amount",
                        "action_type",
                    ]
                ]
            )
    if not frames:
        return pd.DataFrame(
            columns=[
                "instrument_id",
                "ex_date",
                "available_at",
                "ratio",
                "cash_amount",
                "action_type",
            ]
        )
    out = pd.concat(frames, ignore_index=True)
    out["ex_ms"] = (
        pd.to_datetime(out["ex_date"], utc=True) - pd.Timestamp(0, tz="UTC")
    ) // pd.Timedelta(milliseconds=1)
    out["avail_ms"] = (
        pd.to_datetime(out["available_at"], utc=True) - pd.Timestamp(0, tz="UTC")
    ) // pd.Timedelta(milliseconds=1)
    return out


def storage_convention(raw_jump: float, ratio: float) -> str:
    """Which convention the STORED ratio follows, read off the raw ex-date move alone.

    A split with vendor factor r (new shares per old) prints a raw move of about -log(r) on the
    ex-date. If the raw move is about +log(r) instead, the stored value is the reciprocal
    (old per new). Splits too small to tell (|log r| < 0.10) are UNRESOLVED.
    """
    if not math.isfinite(ratio) or ratio <= 0.0:
        return "INVALID"
    expected = -math.log(ratio)
    if abs(expected) < 0.10:
        return "UNRESOLVED_SMALL"
    if abs(raw_jump - expected) <= 0.25 * abs(expected) + 0.05:
        return "VENDOR_NEW_PER_OLD"
    if abs(raw_jump + expected) <= 0.25 * abs(expected) + 0.05:
        return "RECIPROCAL_OLD_PER_NEW"
    return "UNRESOLVED"


def classify(raw_jump: float, adjusted_jump: float) -> str:
    if abs(adjusted_jump) < 0.10:
        return "NEUTRALIZED"
    if abs(raw_jump) > 0.05 and abs(adjusted_jump - 2.0 * raw_jump) <= 0.15 * abs(2.0 * raw_jump):
        return "DOUBLED"
    if abs(raw_jump) > 0.05 and abs(adjusted_jump - raw_jump) <= 0.15 * abs(raw_jump):
        return "UNCHANGED"
    return "OTHER"


def audit_lake(lake: Path, *, limit: int | None) -> dict[str, Any]:
    t0 = time.time()
    reader = PITDataReader(LakePaths(lake))
    splits = _splits(lake)
    if limit is not None:
        splits = splits.sample(n=min(limit, len(splits)), random_state=0)
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    conventions: dict[str, int] = {}
    for iid, group in splits.groupby("instrument_id", sort=True):
        lo = int(group["ex_ms"].min()) - 60 * DAY_MS
        hi = int(group["ex_ms"].max()) + 30 * DAY_MS
        bars = reader.ohlcv([str(iid)], start=lo, end=hi, as_of=hi, tf=Timeframe.D1).to_pandas()
        if bars.empty:
            for ex in group["ex_ms"]:
                rows.append(
                    {"instrument_id": str(iid), "ex_date": int(ex), "class": "UNDETERMINED"}
                )
                counts["UNDETERMINED"] = counts.get("UNDETERMINED", 0) + 1
            continue
        bars["ts"] = (
            pd.to_datetime(bars["ts_open"], utc=True) - pd.Timestamp(0, tz="UTC")
        ) // pd.Timedelta(milliseconds=1)
        raw = bars.set_index("ts")["close"].astype("float64").to_frame(str(iid))
        actions = pd.DataFrame(
            {
                "instrument_id": group["instrument_id"].astype(str).to_list(),
                "ex_date": group["ex_ms"].astype("int64").to_list(),
                "available_at": group["avail_ms"].astype("int64").to_list(),
                "action_type": ["split"] * len(group),
                "ratio": group["ratio"].astype("float64").to_list(),
                "cash_amount": [float("nan")] * len(group),
            }
        )
        adjusted = adjusted_close(raw, actions, tf_ms=DAY_MS, include_dividends=False)[str(iid)]
        series_raw = raw[str(iid)]
        for ex, ratio in zip(group["ex_ms"], group["ratio"], strict=True):
            pre_raw = series_raw[series_raw.index < int(ex)].dropna()
            post_raw = series_raw[series_raw.index >= int(ex)].dropna()
            pre_adj = adjusted[adjusted.index < int(ex)].dropna()
            post_adj = adjusted[adjusted.index >= int(ex)].dropna()
            if pre_raw.empty or post_raw.empty or pre_adj.empty or post_adj.empty:
                label = "UNDETERMINED"
                raw_jump = adjusted_jump = None
                convention = "UNDETERMINED"
            else:
                raw_jump = math.log(float(post_raw.iloc[0]) / float(pre_raw.iloc[-1]))
                adjusted_jump = math.log(float(post_adj.iloc[0]) / float(pre_adj.iloc[-1]))
                label = classify(raw_jump, adjusted_jump)
                convention = storage_convention(raw_jump, float(ratio))
            counts[label] = counts.get(label, 0) + 1
            conventions[convention] = conventions.get(convention, 0) + 1
            rows.append(
                {
                    "instrument_id": str(iid),
                    "ex_date": dt.datetime.fromtimestamp(int(ex) / 1000, tz=dt.UTC)
                    .date()
                    .isoformat(),
                    "stored_ratio": float(ratio),
                    "raw_log_jump": raw_jump,
                    "adjusted_log_jump": adjusted_jump,
                    "class": label,
                    "storage_convention": convention,
                }
            )
    determined = sum(v for k, v in counts.items() if k != "UNDETERMINED")
    return {
        "lake": str(lake.relative_to(REPO)) if lake.is_relative_to(REPO) else str(lake),
        "splits": len(splits),
        "instruments_with_splits": int(splits["instrument_id"].nunique()),
        "counts": counts,
        "storage_conventions": conventions,
        "reciprocal_rows": [
            {k: r[k] for k in ("instrument_id", "ex_date", "stored_ratio", "raw_log_jump")}
            for r in rows
            if r.get("storage_convention") == "RECIPROCAL_OLD_PER_NEW"
        ],
        "share_of_determined": {
            k: (v / determined if determined else None)
            for k, v in counts.items()
            if k != "UNDETERMINED"
        },
        "rows": rows,
        "elapsed_seconds": round(time.time() - t0, 1),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lake", action="append", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=None, help="random sample of splits per lake")
    ap.add_argument("--output", type=Path, default=OUTPUT)
    args = ap.parse_args(argv)
    lakes = args.lake or [REPO / "data" / "lake", REPO / "data" / "lake_sharadar"]
    document: dict[str, Any] = {
        "schema": "canli.alphac-split-adjustment-direction-audit.v1",
        "author": "Arhan Canli",
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "engine": (
            "alphaforge.features.library.equity_price.adjusted_close (split-only, as the "
            "features call it)"
        ),
        "engine_test_convention": (
            "tests/unit/test_factors_equity_price.py encodes a 2-for-1 split as ratio 0.5 "
            "(old shares per new)"
        ),
        "classes": {
            "NEUTRALIZED": "|adjusted ex-date log jump| < 0.10",
            "DOUBLED": (
                "adjusted jump within 15 percent of twice the raw jump: the factor was applied "
                "inverted"
            ),
            "UNCHANGED": (
                "adjusted jump within 15 percent of the raw jump: the split was not applied"
            ),
            "OTHER": "none of the above",
            "UNDETERMINED": "no bar on one side of the ex-date",
        },
        "lakes": [audit_lake(lake, limit=args.limit) for lake in lakes],
        "claim_boundary": (
            "A measurement of what the engine produces from what the lakes store. It changes no "
            "lake, no engine and no result; it opens no return path and spends no identity."
        ),
    }
    document["content_hash"] = _content_hash(document)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for lake in document["lakes"]:
        print(
            f"{lake['lake']}: {lake['splits']} splits -> {lake['counts']} "
            f"({lake['elapsed_seconds']}s)"
        )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
