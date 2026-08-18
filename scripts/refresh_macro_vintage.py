#!/usr/bin/env python3
"""Refresh the PIT macro-vintage lake AND record when each vintage first reached us.

TWO JOBS, AND THE SECOND ONE IS WHY THIS EXISTS.

(1) REFRESH. `data/lake_macro_vintage` was built once (meta.json built_utc 2026-07-11) and nothing
    has updated it since. AlphaVintage trades a monthly signal off that lake, so without a refresh
    it would go live and quietly stop receiving new information — the exact failure that left the
    crypto sleeve holding a stale book for its entire first live period before anyone noticed.

(2) MEASURE THE ARRIVAL LAG — the part that cannot be recovered later.
    The backtest enters on "the first trading day STRICTLY AFTER the vintage date", and every
    vintage is stamped the 15th by RTDSM convention. That is CONSERVATIVE against the public
    release: BLS publishes CPI around the 10th-13th, so the backtest trades 3-9 days after the news
    was already public, and the lake's own DATA_CONTRACT says so ("Conservatism can only understate
    alpha, never manufacture it"). Verified 2026-08-07: all 304 CPI observations from 2001 are true
    first releases with a tight 42-45 day publication lag.

    So look-ahead is NOT the risk. The OPERATIONAL question is the open one: when does the Philly
    Fed workbook actually become downloadable to US? The lake stores `obs_period`, `value` and
    `vintage_date` and NOTHING about acquisition, and every raw workbook on disk carries the same
    2026-07-11 mtime, which is when we downloaded them rather than when they published. That gap is
    unmeasurable backwards and trivially measurable forwards, so this job starts measuring it.

    Each run diffs the (series, vintage_date) set against the previous one and appends any NEW
    vintage to `arrival_log.jsonl` with the UTC instant we first saw it. After a few months that
    file answers the only question that matters for the live entry rule: can we actually have the
    data by the day the backtest assumes we trade?

*** ALPHAVINTAGE MUST NOT TRADE LIVE UNTIL THAT LOG HAS REAL OBSERVATIONS. *** An entry rule whose
feasibility is assumed rather than measured is how a backtest becomes a story.

    uv run python scripts/refresh_macro_vintage.py --check    # report state, download nothing
    uv run python scripts/refresh_macro_vintage.py            # refresh + record arrivals
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
LAKE = _ROOT / "data" / "lake_macro_vintage"
TIER2 = LAKE / "tier2_vintage"
RAW_DIR = LAKE / "raw" / "rtdsm"
ARRIVAL_LOG = LAKE / "arrival_log.jsonl"
BUILDER = _ROOT / "scripts" / "probe_econtrend_data.py"

SERIES = ["PCPI", "PCPIX", "EMPLOY", "IPT", "RUC", "HSTARTS", "RCONM"]


def _observed() -> dict[str, set[str]]:
    """{series: {vintage_date ISO}} currently in the lake."""
    out: dict[str, set[str]] = {}
    for s in SERIES:
        p = TIER2 / f"{s}_vintage_long.parquet"
        if not p.exists():
            continue
        d = pd.read_parquet(p, columns=["vintage_date"])
        out[s] = {str(pd.Timestamp(v).date()) for v in d["vintage_date"].unique()}
    return out


def _report(before: dict[str, set[str]]) -> None:
    print(f"{'series':<10}{'vintages':>10}{'latest':>14}{'age (days)':>12}")
    today = datetime.now(UTC).date()
    for s in SERIES:
        v = before.get(s) or set()
        if not v:
            print(f"{s:<10}{0:>10}{'-':>14}{'-':>12}")
            continue
        latest = max(v)
        age = (today - datetime.strptime(latest, "%Y-%m-%d").date()).days
        flag = "  <-- STALE" if age > 45 else ""
        print(f"{s:<10}{len(v):>10}{latest:>14}{age:>12}{flag}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="refresh_macro_vintage")
    ap.add_argument("--check", action="store_true", help="report state only; download nothing")
    a = ap.parse_args(argv)

    print("=" * 78)
    print("PIT MACRO VINTAGE LAKE — refresh + arrival recording")
    print("=" * 78)
    meta = LAKE / "meta.json"
    if meta.exists():
        print(f"  lake built_utc: {json.loads(meta.read_text()).get('built_utc')}")
    before = _observed()
    _report(before)

    if a.check:
        n = sum(1 for _ in ARRIVAL_LOG.open()) if ARRIVAL_LOG.exists() else 0
        print(f"\n  arrival_log.jsonl: {n} recorded arrivals")
        print("  (--check: nothing downloaded)")
        return 0

    # FORCE THE FETCH. probe_econtrend_data.py:201 downloads a workbook only `if not
    # raw_path.exists()`, which is correct for a one-shot research build and completely wrong for a
    # scheduled refresh: it rebuilds parquets from CACHED xlsx, exits 0, and stamps meta.json with
    # today's date while the underlying data does not move. Measured 2026-08-07 — a "successful"
    # rebuild left every workbook at its 2026-07-11 23:22 mtime and every series 53 days stale, with
    # no warning anywhere. A job that reports healthy while serving two-month-old data to a live
    # sleeve is worse than no job. So the refresh owns the freshness policy: move the cached
    # workbooks aside, force a real download, and VERIFY it happened.
    stale_dir = RAW_DIR.parent / f"rtdsm_stale_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    cached = sorted(RAW_DIR.glob("*.xlsx")) if RAW_DIR.exists() else []
    if cached:
        stale_dir.mkdir(parents=True, exist_ok=True)
        for f in cached:
            f.rename(stale_dir / f.name)
        print(f"\n  moved {len(cached)} cached workbook(s) aside -> {stale_dir.name}")

    print("  rebuilding from the Philly Fed RTDSM workbooks ...")
    r = subprocess.run(
        [sys.executable, str(BUILDER), "build"], cwd=_ROOT, capture_output=True, text=True
    )
    fetched = sorted(RAW_DIR.glob("*.xlsx")) if RAW_DIR.exists() else []
    if r.returncode == 0 and len(fetched) < len(cached):
        # Restore rather than leave the lake short: a partial fetch that silently drops series is
        # its own failure mode.
        for f in stale_dir.glob("*.xlsx"):
            if not (RAW_DIR / f.name).exists():
                f.rename(RAW_DIR / f.name)
        print(f"  !! FETCH INCOMPLETE: {len(fetched)} of {len(cached)} workbooks downloaded; "
              "restored the cached copies. Treat this run as FAILED.")
        return 1
    if r.returncode != 0:
        # A failed refresh must be LOUD. A sleeve whose data silently stops arriving keeps
        # trading yesterday's signal and reports it as today's.
        print(f"  !! REFRESH FAILED (exit {r.returncode})")
        print("  " + "\n  ".join((r.stderr or r.stdout or "").strip().splitlines()[-8:]))
        return 1

    after = _observed()
    seen_at = datetime.now(UTC).isoformat()
    new_rows: list[dict[str, object]] = []
    for s in SERIES:
        fresh = sorted((after.get(s) or set()) - (before.get(s) or set()))
        for v in fresh:
            lag = (datetime.now(UTC).date() - datetime.strptime(v, "%Y-%m-%d").date()).days
            new_rows.append({"series": s, "vintage_date": v, "first_seen_utc": seen_at,
                             "days_after_vintage_stamp": lag})
    if new_rows:
        with ARRIVAL_LOG.open("a", encoding="utf-8") as fh:
            for row in new_rows:
                fh.write(json.dumps(row) + "\n")
        print(f"\n  RECORDED {len(new_rows)} new vintage arrival(s):")
        for row in new_rows:
            print(f"    {row['series']:<8} vintage {row['vintage_date']}  "
                  f"first seen {row['days_after_vintage_stamp']:+d}d after its stamp")
        print("\n  A POSITIVE lag means the data reached us AFTER the date the backtest assumes")
        print("  it traded. If that stays positive, the live entry rule must be pushed back to")
        print("  match, and the backtest re-derived at the later entry before anyone funds this.")
    else:
        print("\n  no new vintages this run (expected: RTDSM publishes monthly)")

    _report(after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
