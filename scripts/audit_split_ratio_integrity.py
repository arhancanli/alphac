#!/usr/bin/env python3
"""AUDIT — how many stored split ratios disagree with the price move they should explain.

WHY. The AlphaLedger pinned re-run -- the first execution of PREREG_SLEEVE4_INVESTMENT.md's
declared 8,017-id cohort, and the evidence the sleeve's admission rests on -- ran for 2h18m and
died with `ValueError: equity must be finite and > 0, got -370885.66`. The account went bankrupt
from a $100k start.

The first line of that run's log explains it:

    split record(s) for XUSE:CASH:VEONUSD at ex=1187740800000 SKIPPED by sanity guard:
    stored ratio 0.2 disagrees with the actual price move 102.47 -> 21
    (|log err| 3.194 > 0.30); position and orders remain unconverted

The guard (backtest/engine.py, `_SPLIT_SANITY_MAX_ABS_LOG = 0.30`) is RIGHT to refuse a ratio it
cannot verify: applying a wrong one silently rewrites a position. But the fallback -- leave the
position unconverted -- means the engine then observes the raw price series across the split and
books a fabricated move of the whole split factor. On a short, a 75x fabricated move is an
unbounded loss. That is the mechanism that took equity negative.

WHAT THIS MEASURES. For every split with a verifiable price boundary, compare the stored ratio
against the move it should explain: a correct record satisfies `(post_open / pre_close) * ratio
== 1`. Classify each failure as RECIPROCAL (the inverse ratio would verify -- a convention error)
or UNEXPLAINED (neither direction fits, typically a record whose price did not move at all).

Read-only. No hypothesis, no backtest, no ledger write.

    uv run python scripts/audit_split_ratio_integrity.py
"""
# ruff: noqa: E501
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = _ROOT / "artifacts" / "analysis" / "split_ratio_integrity"
LEDGER = _ROOT / "var" / "experiments.jsonl"
#: Must match backtest/engine.py::_SPLIT_SANITY_MAX_ABS_LOG or this audit measures a different guard.
GUARD_TOLERANCE = 0.30
LAKES = ("data/lake_sharadar", "data/lake")


def audit(lake: str) -> dict | None:
    con = duckdb.connect()
    q = f"""
    WITH sp AS (
      SELECT instrument_id AS iid, ex_date, ratio
      FROM read_parquet('{_ROOT}/{lake}/corporate_actions/**/*.parquet')
      WHERE action_type='split' AND ratio IS NOT NULL AND ratio > 0
    ),
    px AS (SELECT instrument_id AS iid, ts_open, open, close
           FROM read_parquet('{_ROOT}/{lake}/ohlcv_1d/**/*.parquet'))
    SELECT sp.iid, sp.ex_date, sp.ratio,
      (SELECT close FROM px WHERE px.iid=sp.iid AND px.ts_open <  sp.ex_date ORDER BY px.ts_open DESC LIMIT 1) AS pre_close,
      (SELECT open  FROM px WHERE px.iid=sp.iid AND px.ts_open >= sp.ex_date ORDER BY px.ts_open ASC  LIMIT 1) AS post_open
    FROM sp
    """
    try:
        df = con.execute(q).df()
    except Exception as exc:
        print(f"  {lake}: UNAVAILABLE ({type(exc).__name__}: {str(exc)[:90]})")
        return None

    df = df[(df.pre_close > 0) & (df.post_open > 0)].dropna(subset=["pre_close", "post_open"])
    if df.empty:
        print(f"  {lake}: no split has a verifiable price boundary")
        return None

    move = df.post_open / df.pre_close
    df["err_stored"] = np.abs(np.log(move * df.ratio))
    df["err_inverted"] = np.abs(np.log(move / df.ratio))
    df["price_moved"] = np.abs(np.log(move)) > 0.05

    bad = df.err_stored > GUARD_TOLERANCE
    reciprocal = bad & (df.err_inverted <= GUARD_TOLERANCE)
    unexplained = bad & ~reciprocal
    flat = unexplained & ~df.price_moved

    n = len(df)
    out = {
        "lake": lake,
        "guard_tolerance_log": GUARD_TOLERANCE,
        "splits_with_verifiable_boundary": int(n),
        "consistent": int((~bad).sum()),
        "skipped_by_guard": int(bad.sum()),
        "skipped_fraction": float(bad.sum() / n),
        "of_skipped_reciprocal_would_verify": int(reciprocal.sum()),
        "of_skipped_unexplained": int(unexplained.sum()),
        "of_unexplained_price_did_not_move": int(flat.sum()),
        "worst": df[bad].nlargest(10, "err_stored")[
            ["iid", "ratio", "pre_close", "post_open", "err_stored", "err_inverted"]
        ].to_dict("records"),
    }
    print(f"\n  {lake}")
    print(f"    splits with a verifiable price boundary : {n}")
    print(f"    stored ratio CONSISTENT (guard passes)  : {out['consistent']} ({out['consistent']/n:.1%})")
    print(f"    stored ratio INCONSISTENT (SKIPPED)     : {out['skipped_by_guard']} ({out['skipped_fraction']:.1%})")
    print(f"      of those, RECIPROCAL would verify     : {out['of_skipped_reciprocal_would_verify']}  <- convention error, recoverable")
    print(f"      of those, UNEXPLAINED                 : {out['of_skipped_unexplained']}")
    print(f"        of which the price did NOT move     : {out['of_unexplained_price_did_not_move']}  <- spurious record, should be dropped")
    return out


def main() -> int:
    before = sum(1 for _ in LEDGER.open()) if LEDGER.exists() else 0
    print("=" * 96)
    print("  SPLIT RATIO INTEGRITY — do stored ratios explain the price moves they claim?")
    print("=" * 96)
    results = [r for r in (audit(lk) for lk in LAKES) if r]
    if not results:
        raise SystemExit("ABORT: no lake produced a verifiable split; refusing to report a clean bill")

    print("\n  CONSEQUENCE. A skipped split leaves the position UNCONVERTED, so the engine books the")
    print("  raw price move across the split as a real return. On a short, that is an unbounded")
    print("  loss. This is what drove the AlphaLedger pinned re-run to equity -$370,885 after 2h18m.")
    print("  Neither applying an unverified ratio nor silently skipping it is safe: the third option,")
    print("  refusing to trade an instrument whose corporate-action record cannot be verified, is the")
    print("  only one that cannot fabricate a return.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "result.json").write_text(json.dumps({
        "lakes": results,
        "claim_boundary": "Read-only data-quality measurement. No hypothesis registered, no backtest run, 0 trials.",
    }, indent=2, sort_keys=True, default=float) + "\n")

    after = sum(1 for _ in LEDGER.open()) if LEDGER.exists() else 0
    if before != after:
        raise SystemExit(f"ABORT: ledger moved {before} -> {after}; the zero-trial claim is void.")
    print(f"\n  ledger unmoved ({after}); 0 hypotheses consumed")
    print(f"  written: {OUT_DIR / 'result.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
