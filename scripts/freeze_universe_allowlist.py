#!/usr/bin/env python3
"""FREEZE the AlphaMax eligibility allowlist at the pre-break cohort. 2026-08-04.

THE DEFECT (measured, not inferred)
-----------------------------------
On 2026-06-22 the equity lake's cross-section stepped from 3,343 names/session to 11,863
overnight. The Polygon flat-file entitlement had lapsed (GetObject 403) and the ingest moved to
a whole-market feed. The 25-year historical lake, however, was built by scripts/sharadar_load.py
under this category filter:

    _COMMON = ("Domestic Common Stock", "Domestic Common Stock Primary Class", "ADR Common Stock")

Canadian ordinaries (RY, TD, BNS, CNQ, SHOP) and SECONDARY share classes (GOOG, where GOOGL is
the primary) match none of those. So those names have no history at all before 2026-06-22 —
GOOGL runs 2004..2026 while GOOG has 30 sessions. That one tuple explains the whole asymmetry.

Consequence: `universe.size=2000` silently stopped meaning what it meant during validation. The
sleeve that was validated over 25 years and the sleeve now running are drawn from different
cross-sections, and the published forward curve splices the two mid-window.

WHY WE CONSTRAIN THE LIVE UNIVERSE RATHER THAN EXPAND THE BACKTEST
------------------------------------------------------------------
The obvious repair — backfill the whole market to 1997 — is UNBUILDABLE on this entitlement, and
that was verified rather than assumed: grouped-daily returns OK for 2022-06-15 and 2026-07-28 but
NOT_AUTHORIZED for 2019-06-03, 2010-06-15, 2003-09-10 and 1997-01-02. Roughly five years is all
this key can reach, which cannot reconstruct a 25-year validation.

So the honest move is the reverse: make the live sleeve trade the cohort it was actually
validated on, and admit the new cohort only when it has earned its own history.

THE FREEZE DISCIPLINE (the part that makes this legitimate)
-----------------------------------------------------------
The allowlist is itself a point-in-time artifact, and it would be trivially corrupt to choose the
freeze date after seeing which cohort backtests better. So:

  * The freeze date is 2026-06-19 — the last session BEFORE the break. It is fixed by the defect,
    not chosen by us, and it was written down before any performance delta was computed.
  * Eligibility = at least MIN_SESSIONS sessions of lake history AS OF that date. 253 is the
    12-1 momentum warmup (eq_mom_252_21 is NaN until 253 bars exist), so it is the signal's own
    requirement rather than a tuned number.
  * The output is hashed and committed. It is NEVER re-derived against a later lake — doing so
    would silently re-admit the new cohort and reintroduce exactly the look-ahead being removed.
  * SUNSET, pre-registered NOW: on 2027-06-22 the post-break cohort clears 253 sessions. At that
    point the identical walk-forward is re-run on the expanded cohort and the delta is published
    WHETHER IT IS POSITIVE OR NEGATIVE. No parameter is re-tuned to compensate.

Expected Sharpe contribution: 0.00. This adds no alpha. It removes a breadth loss we are
currently taking for free, and it makes the sleeve we run the sleeve we published.

    uv run python scripts/freeze_universe_allowlist.py
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

LAKE = "data/lake/ohlcv_1d"
OUT = Path("data/research/universe_allowlist_20260619.json")
FREEZE_DATE = "2026-06-19"      # last session BEFORE the 2026-06-22 cohort break
MIN_SESSIONS = 253              # eq_mom_252_21 warmup: NaN until 253 bars exist
SUNSET_DATE = "2027-06-22"      # post-break cohort clears 253 sessions; re-measure and publish


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    freeze_ms = int(pd.Timestamp(FREEZE_DATE, tz="UTC").timestamp() * 1000)

    ids = [d for d in os.listdir(LAKE) if d.startswith("instrument_id=XUSE")]
    print(f"scanning {len(ids):,} equity instruments as of {FREEZE_DATE} ...", flush=True)

    eligible, short, empty = [], 0, 0
    for d in ids:
        fs = glob.glob(glob.escape(os.path.join(LAKE, d)) + "/*/*.parquet")
        if not fs:
            empty += 1
            continue
        n = 0
        for f in fs:
            try:
                ts = pd.read_parquet(f, columns=["ts_open"])["ts_open"]
            except Exception:  # noqa: BLE001 — a malformed shard must not skew the freeze
                continue
            # ts_open may be int64 ms or tz-aware datetime64 depending on shard vintage;
            # normalise to epoch ms so the freeze comparison is exact either way.
            v = pd.to_datetime(ts, unit="ms", utc=True) if pd.api.types.is_integer_dtype(ts) \
                else pd.to_datetime(ts, utc=True)
            n += int((v <= pd.Timestamp(FREEZE_DATE, tz="UTC")).sum())
        if n >= MIN_SESSIONS:
            eligible.append(d.split("instrument_id=")[1])
        else:
            short += 1

    eligible.sort()
    payload = {
        "schema": "alphaforge.universe_allowlist/1",
        "freeze_date": FREEZE_DATE,
        "min_sessions": MIN_SESSIONS,
        "sunset_date": SUNSET_DATE,
        "rationale": (
            "Cohort break 2026-06-22: the equity lake stepped 3,343 -> 11,863 names/session when "
            "the ingest moved to a whole-market feed after the flat-file entitlement lapsed. The "
            "25-year lake was built under a Sharadar category filter excluding Canadian ordinaries "
            "and secondary share classes, so those names have no pre-break history. This allowlist "
            "restricts live selection to the cohort AlphaMax was actually validated on. It is "
            "frozen: never re-derive it against a later lake."
        ),
        "n_eligible": len(eligible),
        "instrument_ids": eligible,
    }
    body = json.dumps(payload, indent=1, sort_keys=True)
    digest = hashlib.sha256(body.encode()).hexdigest()
    payload["sha256"] = digest
    OUT.write_text(json.dumps(payload, indent=1, sort_keys=True))

    print(f"\n  eligible (>= {MIN_SESSIONS} sessions by {FREEZE_DATE}): {len(eligible):,}")
    print(f"  excluded, insufficient pre-break history:              {short:,}")
    print(f"  excluded, no bars at all:                              {empty:,}")
    print(f"\n  sha256: {digest}")
    print(f"  written: {OUT}")
    print(f"\n  SUNSET {SUNSET_DATE}: re-run the identical walk-forward on the expanded cohort")
    print("  and publish the delta whether positive or negative. Do not re-tune to compensate.")
    print(f"\n  frozen at {datetime.now(UTC).isoformat(timespec='seconds')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
