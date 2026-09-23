#!/usr/bin/env python3
"""Judge every stored split against the raw bars and write each lake's correction file.

WHY. The direction audit (scripts/audit_split_adjustment_direction.py) measures what the
adjusted-close kernel does across each ex-date; it fixes nothing. This builder turns its evidence
into decisions: reciprocal rows are inverted, a split whose raw move sits a few sessions away is
moved there, a split with no raw move anywhere near its ex-date is voided, and everything else is
left as stored and listed. The decisions go to ``<lake>/_corrections/corporate_actions.json``,
which :class:`alphaforge.data.store.reader.PITDataReader` applies to every read.

It reads the STORED rows straight from the parquet leaves, never through the reader, so an
existing correction file cannot feed back into the next one. Dry run by default; ``--write``
replaces each lake's file and the summary at artifacts/audit/split_corrections.json.

    uv run python scripts/build_split_corrections.py [--lake data/lake ...] [--write]
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

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from alphaforge.core.time import Timeframe  # noqa: E402
from alphaforge.data.store import corrections as corr  # noqa: E402
from alphaforge.data.store.lake import LakePaths  # noqa: E402
from alphaforge.data.store.reader import PITDataReader  # noqa: E402
from alphaforge.features.library.equity_price import adjusted_close  # noqa: E402

DEFAULT_LAKES = ("data/lake", "data/lake_sharadar")
SUMMARY = REPO / "artifacts" / "audit" / "split_corrections.json"
DAY_MS = Timeframe.D1.ms
#: A correction is kept only if, through the engine's own kernel, it shrinks the total absolute
#: adjusted log movement within VERIFY_SESSIONS of the split by more than MIN_IMPROVEMENT. Total
#: movement, not the largest move: a wrong fix that splits one fake jump into two half-size jumps
#: halves the largest move and changes nothing about the damage.
VERIFY_SESSIONS = 8
MIN_IMPROVEMENT = 0.05


def _window_movement(
    closes: pd.Series, iid: str, rows: list[tuple[int, float]], around: tuple[int, ...]
) -> float:
    """Sum of |adjusted log moves| within VERIFY_SESSIONS days of any date in ``around``."""
    raw = closes.to_frame(iid)
    actions = pd.DataFrame(
        {
            "instrument_id": [iid] * len(rows),
            "ex_date": [e for e, _ in rows],
            # Knowable well before the ex-date: this measures the adjustment, not PIT timing.
            "available_at": [e - 60 * DAY_MS for e, _ in rows],
            "action_type": ["split"] * len(rows),
            "ratio": [r for _, r in rows],
            "cash_amount": [float("nan")] * len(rows),
        }
    )
    adjusted = adjusted_close(raw, actions, tf_ms=DAY_MS, include_dividends=False)[iid].dropna()
    moves = np.log(adjusted.astype("float64")).diff().abs()
    near = np.zeros(len(moves), dtype=bool)
    for ts in around:
        near |= (moves.index >= ts - VERIFY_SESSIONS * DAY_MS) & (
            moves.index <= ts + VERIFY_SESSIONS * DAY_MS
        )
    window = moves[near].dropna()
    return float(window.sum()) if len(window) else float("nan")


def _median(values: list[float]) -> float:
    return float(np.median(values)) if values else float("nan")


def verify_instrument(
    closes: pd.Series,
    iid: str,
    stored: list[tuple[int, float]],
    proposed: list[corr.SplitCorrection],
) -> list[tuple[corr.SplitCorrection, float, float, bool]]:
    """Each proposed correction applied ALONE to the stored rows: (fix, before, after, kept)."""
    out = []
    for fix in proposed:
        after_rows = []
        for e, r in stored:
            if e == fix.stored_ex_ms and math.isclose(r, fix.stored_ratio, rel_tol=1e-9):
                if fix.action != "void":
                    after_rows.append((fix.ex_ms, fix.ratio))
            else:
                after_rows.append((e, r))
        around = (fix.stored_ex_ms, fix.ex_ms)
        before = _window_movement(closes, iid, stored, around)
        after = _window_movement(closes, iid, after_rows, around)
        kept = math.isfinite(before) and math.isfinite(after) and after < before - MIN_IMPROVEMENT
        out.append((fix, before, after, kept))
    return out


def _stored_splits(lake: Path) -> pd.DataFrame:
    frames = []
    pattern = str(lake / "corporate_actions" / "instrument_id=*" / "year=*" / "data.parquet")
    for path in sorted(glob.glob(pattern)):
        frame = pq.ParquetFile(path).read().to_pandas()
        frame = frame[frame["action_type"] == "split"]
        if not frame.empty:
            frames.append(frame[["instrument_id", "ex_date", "ratio"]])
    if not frames:
        return pd.DataFrame(columns=["instrument_id", "ex_ms", "ratio"])
    out = pd.concat(frames, ignore_index=True)
    out["ex_ms"] = (
        pd.to_datetime(out["ex_date"], utc=True) - pd.Timestamp(0, tz="UTC")
    ) // pd.Timedelta(milliseconds=1)
    return out[["instrument_id", "ex_ms", "ratio"]]


def _iso(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.UTC).date().isoformat()


def judge_lake(lake: Path) -> dict[str, Any]:
    t0 = time.time()
    # A fresh reader over the lake is only used for BARS, which corrections never touch.
    reader = PITDataReader(LakePaths(lake))
    splits = _stored_splits(lake)
    verdicts: list[dict[str, Any]] = []
    fixes: list[corr.SplitCorrection] = []
    rejected: list[corr.SplitCorrection] = []
    rejected_detail: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    for iid, group in splits.groupby("instrument_id", sort=True):
        lo = int(group["ex_ms"].min()) - 30 * DAY_MS
        hi = int(group["ex_ms"].max()) + 30 * DAY_MS
        bars = reader.ohlcv([str(iid)], start=lo, end=hi, as_of=hi, tf=Timeframe.D1).to_pandas()
        if bars.empty:
            closes = pd.Series(dtype="float64")
        else:
            ts = (
                pd.to_datetime(bars["ts_open"], utc=True) - pd.Timestamp(0, tz="UTC")
            ) // pd.Timedelta(milliseconds=1)
            closes = pd.Series(bars["close"].astype("float64").to_numpy(), index=ts.to_numpy())
        stored = [(int(e), float(r)) for e, r in zip(group["ex_ms"], group["ratio"], strict=True)]
        proposed = []
        for i, (ex_ms, ratio) in enumerate(stored):
            others = stored[:i] + stored[i + 1 :]
            v = corr.classify_split(closes, ex_ms, ratio, other_splits=others)
            verdicts.append(
                {
                    "instrument_id": str(iid),
                    "stored_ex_ms": int(ex_ms),
                    "stored_ratio": float(ratio),
                    **v,
                }
            )
            if v["action"] is not None:
                proposed.append(
                    corr.SplitCorrection(
                        instrument_id=str(iid),
                        stored_ex_ms=int(ex_ms),
                        stored_ratio=float(ratio),
                        action=v["action"],
                        ratio=float(v["ratio"]),
                        ex_ms=int(v["ex_ms"]),
                        verdict=v["verdict"],
                    )
                )
        for fix, before, after, kept in verify_instrument(closes, str(iid), stored, proposed):
            (fixes if kept else rejected).append(fix)
            checks.append({"kept": kept, "before": before, "after": after})
            if not kept:
                rejected_detail.append(
                    {
                        "instrument_id": fix.instrument_id,
                        "stored_ex_date": _iso(fix.stored_ex_ms),
                        "stored_ratio": fix.stored_ratio,
                        "proposed": fix.action,
                        "verdict": fix.verdict,
                        "window_movement_before": before,
                        "window_movement_after": after,
                    }
                )
    counts: dict[str, int] = {}
    for v in verdicts:
        counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1
    return {
        "lake": str(lake.relative_to(REPO)) if lake.is_relative_to(REPO) else str(lake),
        "splits": len(verdicts),
        "verdict_counts": dict(sorted(counts.items())),
        "corrections": tuple(fixes),
        "verification": {
            "rule": (
                f"kept only if the total absolute adjusted log movement within {VERIFY_SESSIONS} "
                f"sessions shrinks by more than {MIN_IMPROVEMENT} through the engine's kernel"
            ),
            "proposed": len(checks),
            "kept": sum(c["kept"] for c in checks),
            "rejected": rejected_detail,
            "kept_median_window_movement_before": _median(
                [c["before"] for c in checks if c["kept"]]
            ),
            "kept_median_window_movement_after": _median([c["after"] for c in checks if c["kept"]]),
        },
        "unresolved": [
            {
                "instrument_id": v["instrument_id"],
                "ex_date": _iso(v["stored_ex_ms"]),
                "stored_ratio": v["stored_ratio"],
                "ex_date_move": v.get("ex_date_move"),
                "largest_move_in_window": v.get("largest_move_in_window"),
            }
            for v in verdicts
            if v["verdict"] == "UNRESOLVED"
        ],
        "elapsed_seconds": round(time.time() - t0, 1),
    }


def _content_hash(document: dict[str, Any]) -> str:
    body = {k: v for k, v in document.items() if k != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lake", action="append", help="lake root (repeatable)")
    parser.add_argument("--write", action="store_true", help="write the files (default: dry run)")
    args = parser.parse_args()
    lakes = [REPO / p for p in (args.lake or DEFAULT_LAKES)]
    reports = []
    for lake in lakes:
        report = judge_lake(lake)
        fixes = report.pop("corrections")
        evidence = {
            "builder": "scripts/build_split_corrections.py",
            "rule": {
                "min_log_ratio": corr.MIN_LOG_RATIO,
                "tolerance": f"{corr.REL_TOL} x |log r| + {corr.ABS_TOL}",
                "window_sessions": corr.WINDOW,
                "phantom_max_move": corr.PHANTOM_MAX_MOVE,
            },
            "splits_judged": report["splits"],
            "verdict_counts": report["verdict_counts"],
        }
        report["correction_count"] = len(fixes)
        report["actions"] = [
            {
                "instrument_id": f.instrument_id,
                "stored_ex_date": _iso(f.stored_ex_ms),
                "stored_ratio": f.stored_ratio,
                "action": f.action,
                "ratio": f.ratio,
                "ex_date": _iso(f.ex_ms),
                "verdict": f.verdict,
            }
            for f in fixes
        ]
        if args.write:
            path = corr.write_split_corrections(lake, fixes, evidence=evidence)
            _, sha = corr.load_split_corrections(lake)
            report["correction_file"] = {"path": str(path.relative_to(REPO)), "content_hash": sha}
        ver = report["verification"]
        print(
            f"{report['lake']}: {report['splits']} splits, {ver['proposed']} proposed, "
            f"{len(fixes)} kept, {len(ver['rejected'])} rejected by the kernel check; "
            f"median window movement of kept rows {ver['kept_median_window_movement_before']:.3f}"
            f" -> {ver['kept_median_window_movement_after']:.3f}; {report['verdict_counts']} "
            f"({report['elapsed_seconds']}s)"
        )
        reports.append(report)
    if args.write:
        document: dict[str, Any] = {
            "schema": "canli.split-corrections-summary.v1",
            "generated_at": dt.datetime.now(dt.UTC).isoformat(),
            "lakes": reports,
            "claim_boundary": (
                "Decisions about stored split rows judged against the raw daily bars of the same "
                "lake. A correction changes what the reader serves; the stored rows are untouched. "
                "UNRESOLVED rows are served as stored and listed here for review."
            ),
        }
        document["content_hash"] = _content_hash(document)
        SUMMARY.parent.mkdir(parents=True, exist_ok=True)
        SUMMARY.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n")
        print(f"wrote {SUMMARY.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
