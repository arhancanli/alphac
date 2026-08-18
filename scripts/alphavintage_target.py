#!/usr/bin/env python3
"""ALPHAVINTAGE — write the live target book as a walk-forward positions artifact.

WHY THIS IS AN ARTIFACT WRITER AND NOT A BROKER RUNNER
------------------------------------------------------
AlphaVintage is the only validated sleeve that could not trade, because `live_cycle.py` reads
its target book from `artifacts/walkforward/<wf>/legs/leg_*/positions.parquet` and AlphaVintage
— born as a probe, not a walk-forward run — never produced one. The obvious fix is a dedicated
execution runner. That would be the wrong fix: it would fork a SECOND order-submission path
that does not inherit the price collar, the participation cap, the flip-split client-order-ids,
the stale-order sweep or the kill switch, and every one of those guards would have to be
re-implemented and re-tested. Bugs would live in the copy.

So this script writes the ARTIFACT instead. `live_cycle.py` is then unchanged except for one
routing entry, and AlphaVintage inherits every existing safety guard for free.

THE SPEC IS IMPORTED, NEVER RETYPED
-----------------------------------
`surprise()` and `px()` come from scripts/probe_cpi_surprise_size.py — the file that validated
this sleeve. If that spec ever changes, this file changes with it or fails loudly; it cannot
silently diverge into "the live version" that differs from "the tested version". This is the
same discipline probe_macro_vintage_family.py applies, and for the same reason.

THE RULE, quoted from the pre-registered spec:
    SIGNAL  : SI = mean of the standardized AR(3) surprises of PCPI (headline) and PCPIX (core).
    WEIGHTS : w = -clip(SI, -1, +1) on the dollar-neutral spread (IWM - SPY).
              w > 0 = long IWM / short SPY. Gross per leg = |w| x NAV.
    TIMING  : enter at the CLOSE of the first trading day STRICTLY AFTER the vintage date V,
              hold until the next vintage date. The announcement-day move is deliberately
              forfeited — it is a real but far more crowded trade.

TWO GUARDS THIS ADDS, both of which fail CLOSED
-----------------------------------------------
1. STALENESS. The vintage lake is refreshed by a launchd job (com.accapital.macrovintage,
   08:20 daily). If that job dies, the newest vintage silently stops advancing and this script
   would happily keep republishing a months-old target as though it were current. So if the
   newest vintage is older than STALE_DAYS, this REFUSES TO WRITE and exits non-zero. A stale
   target that stops updating is worse than no target, because it looks alive.
2. PRE-ENTRY. Between V and the first trading day after it we are NOT yet in the new position;
   the spec forfeits that window. During it this republishes the PREVIOUS vintage's weight
   rather than jumping the gun on the new one.

    uv run python scripts/alphavintage_target.py            # write the artifact
    uv run python scripts/alphavintage_target.py --dry-run  # print, write nothing
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

# THE SPEC, IMPORTED. Not a copy — the actual functions the validation ran on.
from scripts.probe_cpi_surprise_size import px, surprise  # noqa: E402

OUT_DIR = _ROOT / "artifacts/walkforward/alphavintage_live/legs/leg_01"
IWM_ID = "XUSE:CASH:IWMUSD"
SPY_ID = "XUSE:CASH:SPYUSD"

# A CPI vintage lands monthly on the 15th. 45 days = one full missed release plus a fortnight of
# slack for holidays and a late ALFRED post. Beyond that the feed is broken, not merely slow.
STALE_DAYS = 45

# ---------------------------------------------------------------- THE LEVERAGE DEVIATION, DECLARED
# The pre-registered spec sizes gross per leg at |w| x NAV, so at the clip (|w| = 1) it runs
# 2.0x GROSS. That is outside the design envelope of every sleeve now live — live_cycle.py's own
# comment records the legitimate profiles as "MF ~1.0x gross, equity ~0.55x, crypto <=1.0x" — and
# it exceeds `_GROSS_HARD_CAP = 1.5`, which does NOT merely skip the sleeve: it ENGAGES THE GLOBAL
# KILL SWITCH and halts every other sleeve until a human disengages it. Publishing the spec's raw
# weights would therefore take the entire book down the first time SI hit the clip. It is at the
# clip today (SI = -2.36).
#
# It is also unrunnable on its own terms: the account holds $1.0M, so 2.0x gross is $2.0M against a
# Reg T OVERNIGHT limit of exactly $2.0M — zero cushion on a position held for a month.
#
# So live runs at 1.0x gross, i.e. every weight scaled by LIVE_GROSS_TARGET / SPEC_GROSS = 0.5.
# WHAT THIS DOES AND DOES NOT CHANGE, stated precisely because "we scaled it" invites suspicion:
#   * SHARPE IS UNCHANGED. Scaling a return series by a constant scales mean and sd equally, so
#     the validated Sharpe applies to the live sleeve exactly. No re-validation is owed.
#   * EXPECTED DOLLAR RETURN IS HALVED, as is vol and drawdown. This is a risk choice, not an
#     edge claim, and it is the reason no trial is spent: nothing about the hypothesis changed.
#   * The sleeve's EFFECTIVE WEIGHT in the combined book is halved. Any book arithmetic that
#     assumes AlphaVintage at spec notional must apply the same 0.5 or it will overstate.
SPEC_GROSS = 2.0
LIVE_GROSS_TARGET = 1.0


def active_vintage(SI: pd.Series, trading_days: pd.DatetimeIndex, today: pd.Timestamp):
    """The vintage whose weight we should be HOLDING today, honouring the anti-lookahead rule.

    Returns (V, entry_date). The spec enters at the close of the first trading day strictly
    after V, so a vintage stamped but not yet entered must NOT be published — during that gap
    the previous vintage's position is still the live one.
    """
    for V in reversed(list(SI.index)):
        if today < V:
            continue  # a future-stamped vintage cannot inform today's book
        after = trading_days[trading_days > V]
        if len(after) == 0:
            continue  # stamped, but no trading day has passed yet — not entered
        entry = after[0]
        if today >= entry:
            return V, entry
    return None, None


def gross_hard_cap() -> float:
    """Read `_GROSS_HARD_CAP` out of live_cycle.py's SOURCE rather than importing it.

    Textual, so this has no import side effects, and it raises if the constant is renamed or
    deleted. The point is that the cap and the sleeve that must respect it cannot silently drift
    apart: if someone retunes the rail, this script either adapts or fails loudly on the next run.
    """
    src = (_ROOT / "scripts" / "live_cycle.py").read_text()
    m = re.search(r"^_GROSS_HARD_CAP\s*=\s*([0-9.]+)", src, re.M)
    if not m:
        raise SystemExit(
            "cannot find _GROSS_HARD_CAP in scripts/live_cycle.py — the runaway brake this sleeve "
            "is sized against has moved or been removed; refusing to guess a leverage limit"
        )
    return float(m.group(1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the target, write nothing")
    args = ap.parse_args()

    print("=" * 92)
    print("ALPHAVINTAGE — live target book (CPI surprise -> IWM/SPY size spread)")
    print("=" * 92)

    SI = ((surprise("PCPI") + surprise("PCPIX")) / 2.0).dropna()
    IWM, SPY = px("IWM"), px("SPY")
    trading_days = IWM.index.intersection(SPY.index)
    today = pd.Timestamp.now("UTC").tz_localize(None).normalize()

    newest = SI.index.max()
    age = (today - newest).days
    print(f"  vintages      : {len(SI)}  ({SI.index.min().date()} .. {newest.date()})")
    print(f"  newest vintage: {newest.date()}  ({age}d old, stale gate {STALE_DAYS}d)")

    # GUARD 1 — fail CLOSED on a dead feed rather than republish a stale target as current.
    if age > STALE_DAYS:
        print(f"\n!!! REFUSING TO WRITE: newest vintage is {age}d old (> {STALE_DAYS}d).")
        print("!!! The macro-vintage refresh (com.accapital.macrovintage, 08:20) has likely died.")
        print("!!! A stale target that keeps publishing looks alive and is worse than none.")
        return 1

    V, entry = active_vintage(SI, trading_days, today)
    if V is None:
        print("\n!!! REFUSING TO WRITE: no vintage has been entered yet under the timing rule.")
        return 1

    si = float(SI[V])
    w_spec = -float(np.clip(si, -1.0, 1.0))
    scale = LIVE_GROSS_TARGET / SPEC_GROSS
    w = w_spec * scale
    gross = 2.0 * abs(w)
    mark_iwm, mark_spy = float(IWM.iloc[-1]), float(SPY.iloc[-1])

    print(f"  active vintage: {V.date()}   entered {entry.date()} (close)")
    print(f"  SI            : {si:+.4f}   ->   w_spec = -clip(SI) = {w_spec:+.4f}"
          f"  (gross {2 * abs(w_spec):.2f}x)")
    print(f"  live scale    : x{scale:.2f}   -> w_live {w:+.4f}   (gross {gross:.2f}x NAV)")
    print(f"  target        : {IWM_ID} {w:+.4f}   |   {SPY_ID} {-w:+.4f}")
    print(f"  marks         : IWM {mark_iwm:.2f}  SPY {mark_spy:.2f}  (as of {IWM.index[-1].date()})")

    # GUARD 3 — never hand live_cycle a book that would trip its runaway brake. That brake does not
    # skip this sleeve; it engages the GLOBAL kill switch and stops every sleeve. Refuse here, where
    # the blast radius is one script exiting non-zero.
    cap = gross_hard_cap()
    if gross > cap:
        print(f"\n!!! REFUSING TO WRITE: gross {gross:.2f}x exceeds live_cycle _GROSS_HARD_CAP {cap:.2f}x.")
        print("!!! Writing it would engage the GLOBAL kill switch and halt every sleeve, not just this one.")
        return 1
    print(f"  runaway brake : gross {gross:.2f}x vs cap {cap:.2f}x — OK ({cap - gross:.2f}x headroom)")
    if abs(w) < 1e-9:
        print("  NOTE: w rounds to zero — the target book is FLAT. live_cycle will hold no position.")

    ts_ms = int(pd.Timestamp(today).value // 1_000_000)
    # `qty` is deliberately NULL, not 0.0: this artifact carries TARGET WEIGHTS, and share counts
    # are only knowable against live NAV, which live_cycle resolves at submit time. A 0.0 here
    # would read as "flat" to any future consumer; a null makes misuse loud instead of silent.
    table = pa.table({
        "ts": pa.array([ts_ms, ts_ms], type=pa.int64()),
        "instrument_id": pa.array([IWM_ID, SPY_ID], type=pa.string()),
        "qty": pa.array([None, None], type=pa.float64()),
        "mark": pa.array([mark_iwm, mark_spy], type=pa.float64()),
        "weight": pa.array([w, -w], type=pa.float64()),
        "unreal_pnl": pa.array([None, None], type=pa.float64()),
    })

    if args.dry_run:
        print("\n  --dry-run: nothing written.")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, OUT_DIR / "positions.parquet")
    print(f"\n  written: {OUT_DIR / 'positions.parquet'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
