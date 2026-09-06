#!/usr/bin/env python3
"""AUDIT — how much of a walk-forward run's PnL is a split that was never applied to the position.

WHY THIS EXISTS. scripts/audit_split_ratio_integrity.py measured that 5.6-6.2% of stored split
ratios cannot explain the price move they claim, and that the engine's sanity guard responds by
leaving the position UNCONVERTED -- after which the engine books the raw price move across the
split as a real return. It left one question explicitly open:

    "AlphaLedger's published 21y Sharpe 0.83 / NW t +3.19 came from the 6,880-id run, which drew
     on the same contaminated corporate actions. Whether that run simply avoided holding the
     affected names is unknown and is now a question that has to be answered before the sleeve is
     admitted, not after."

This answers it. It does not avoid them.

WHY IT DOES NOT JOIN THE CORPORATE-ACTION TABLE, which is the whole design point. The obvious
approach -- join flagged splits to positions on the ex-date -- requires aligning a corporate
action's ex_date with a position snapshot's bar. Two defensible alignments of that join disagreed
by two orders of magnitude ($90,936 vs $807) on the same data, because `ex_date` arrives as
`datetime64[us, Asia/Dubai]` and the bar a split lands on is off-by-one depending on whether you
read ts_open as the bar's start or its boundary. A number I cannot reconcile is a number I cannot
publish.

The signature needs no join at all. When a split is applied, the position's `qty` changes. When
the guard skips it, `qty` is IDENTICAL across the bar where `mark` moves by the split factor. So:
same leg, same instrument, consecutive bars, qty unchanged, mark moved >= 2x. That is read
entirely from the run's own artifact, and it is what actually reached the equity curve.

The measured quantity is the one-bar change in `unreal_pnl`. The walk-forward Sharpe is computed
on a mark-to-market equity curve, so these swings ARE in the returns that produced it, whether or
not the position was later closed at a corrected price.

Read-only. No hypothesis registered, no backtest run, ledger asserted unmoved.

    uv run python scripts/audit_unapplied_splits_in_run.py [--run prereg_investment]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb

_ROOT = Path(__file__).resolve().parent.parent
LEDGER = _ROOT / "var" / "experiments.jsonl"
OUT_DIR = _ROOT / "artifacts" / "analysis" / "unapplied_splits_in_run"

#: A one-bar mark move at or beyond this multiple, with qty unchanged, is the signature.
#: 2x is the reporting floor; the tiers below exist because a genuine 2x overnight move is
#: possible (a biotech readout, a squeeze) while a 10x is not.
TIERS = (
    (2.0, "all (a genuine 2x one-bar move is possible, so this tier is an upper bound)"),
    (5.0, "a genuine one-bar move of this size is implausible"),
    (10.0, "unambiguous — no real price does this overnight"),
)
#: Consecutive-bar guard: a gap longer than this is not one bar, it is a re-entry.
MAX_GAP_DAYS = 5


def measure(run: str) -> dict:
    legs = _ROOT / "artifacts" / "walkforward" / run / "legs"
    if not legs.is_dir():
        raise SystemExit(f"ABORT: {legs} does not exist — refusing to report a clean bill")
    con = duckdb.connect()
    df = con.execute(f"""
    WITH p AS (
      SELECT regexp_extract(filename,'leg_[0-9]+') AS leg, instrument_id AS iid, ts, qty, mark,
             unreal_pnl
      FROM read_parquet('{legs}/*/positions.parquet', filename=true)
      WHERE qty IS NOT NULL AND qty <> 0 AND mark > 0),
    s AS (
      SELECT *, lag(ts) OVER w AS pts, lag(qty) OVER w AS pqty, lag(mark) OVER w AS pmark,
             lag(unreal_pnl) OVER w AS pupnl
      FROM p WINDOW w AS (PARTITION BY leg, iid ORDER BY ts))
    SELECT leg, iid, ts, qty, pmark, mark, mark/pmark AS move, unreal_pnl - pupnl AS d_upnl
    FROM s
    WHERE pqty IS NOT NULL AND qty = pqty AND (ts - pts) <= {MAX_GAP_DAYS}*86400000
      AND (mark/pmark >= {TIERS[0][0]} OR mark/pmark <= {1 / TIERS[0][0]})
    """).df()

    total_legs = con.execute(
        f"SELECT count(DISTINCT regexp_extract(filename,'leg_[0-9]+')) "
        f"FROM read_parquet('{legs}/*/positions.parquet', filename=true)"
    ).fetchone()[0]
    if not total_legs:
        raise SystemExit("ABORT: the run has no position snapshots; this audit cannot conclude")

    wf = json.loads((_ROOT / "artifacts" / "walkforward" / run / "walkforward.json").read_text())
    summary = wf["summary"]
    profit = summary["final_equity"] - summary["initial_equity"]

    tiers = []
    for lo, note in TIERS:
        sub = df[(df["move"] >= lo) | (df["move"] <= 1 / lo)]
        tiers.append(
            {
                "min_move_multiple": lo,
                "note": note,
                "events": len(sub),
                "instruments": int(sub.iid.nunique()),
                "legs_affected": int(sub.leg.nunique()),
                "legs_total": int(total_legs),
                "gross_fabricated_pnl": float(sub.d_upnl.abs().sum()),
                "net_fabricated_pnl": float(sub.d_upnl.sum()),
                "gross_as_fraction_of_run_profit": float(sub.d_upnl.abs().sum() / profit),
                "net_as_fraction_of_run_profit": float(sub.d_upnl.sum() / profit),
            }
        )

    # DISCRIMINATION. The detector keys on `qty unchanged`, so it is only meaningful if the
    # opposite case -- a split correctly APPLIED -- is distinguishable at all. Among every large
    # one-bar mark move in the run, count how many had qty adjusted in a way consistent with a
    # split (qty and mark move inversely, so qty/pqty * mark/pmark == 1 within the engine's own
    # 0.30 log tolerance). If that number is zero, the finding is not "some splits were missed",
    # it is "no large split was ever applied to a held position in this run".
    disc = (
        con.execute(f"""
    WITH p AS (
      SELECT regexp_extract(filename,'leg_[0-9]+') AS leg, instrument_id AS iid, ts, qty, mark
      FROM read_parquet('{legs}/*/positions.parquet', filename=true)
      WHERE qty IS NOT NULL AND qty <> 0 AND mark > 0),
    s AS (SELECT *, lag(ts) OVER w AS pts, lag(qty) OVER w AS pqty, lag(mark) OVER w AS pmark
          FROM p WINDOW w AS (PARTITION BY leg, iid ORDER BY ts))
    SELECT count(*) AS large_moves,
      sum(CASE WHEN qty = pqty THEN 1 ELSE 0 END) AS qty_unchanged,
      sum(CASE WHEN qty <> pqty THEN 1 ELSE 0 END) AS qty_changed,
      sum(CASE WHEN qty <> pqty AND abs(ln((qty/pqty)*(mark/pmark))) < 0.30 THEN 1 ELSE 0 END)
        AS qty_changed_consistent_with_split
    FROM s WHERE pqty IS NOT NULL AND (ts - pts) <= {MAX_GAP_DAYS}*86400000
      AND (mark/pmark >= {TIERS[0][0]} OR mark/pmark <= {1 / TIERS[0][0]})
    """)
        .df()
        .iloc[0]
        .to_dict()
    )
    if not disc["large_moves"]:
        raise SystemExit(
            "ABORT: no large one-bar mark move found at all; this audit cannot conclude"
        )

    worst = df.reindex(df.d_upnl.abs().sort_values(ascending=False).index).head(15)
    return {
        "run": run,
        "run_summary": {
            "initial_equity": summary["initial_equity"],
            "final_equity": summary["final_equity"],
            "profit": profit,
            "cagr": summary["cagr"],
            "sharpe": summary["sharpe"],
        },
        "detection": "qty IDENTICAL across consecutive bars while mark moved >= the tier multiple",
        "measured_quantity": "one-bar change in unreal_pnl, which is what the mark-to-market "
        "equity curve (and therefore the reported Sharpe) actually carried",
        "max_gap_days": MAX_GAP_DAYS,
        "tiers": tiers,
        "discrimination": {k: int(v) for k, v in disc.items()},
        "worst_events": worst[["leg", "iid", "qty", "pmark", "mark", "move", "d_upnl"]].to_dict(
            "records"
        ),
        "claim_boundary": "Read-only measurement over an existing run artifact. It shows that "
        "fabricated moves reached the equity curve; it does NOT re-derive what "
        "the Sharpe would be without them. Only a corrected re-run can do that.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="prereg_investment")
    args = ap.parse_args()
    before = sum(1 for _ in LEDGER.open()) if LEDGER.exists() else 0

    out = measure(args.run)
    print("=" * 96)
    print("  UNAPPLIED SPLITS — how much of this run's PnL is a split the position never took")
    print("=" * 96)
    r = out["run_summary"]
    print(
        f"\n  run {out['run']}: ${r['initial_equity']:,.0f} -> ${r['final_equity']:,.0f} "
        f"(profit ${r['profit']:,.0f}, CAGR {r['cagr']:.2%}, Sharpe {r['sharpe']:.4f})"
    )
    for t in out["tiers"]:
        print(f"\n  >= {t['min_move_multiple']:g}x  — {t['note']}")
        print(
            f"    events {t['events']:>4} | instruments {t['instruments']:>4} | "
            f"legs {t['legs_affected']:>3} of {t['legs_total']}"
        )
        print(
            f"    gross fabricated ${t['gross_fabricated_pnl']:>12,.0f}  "
            f"= {t['gross_as_fraction_of_run_profit']:>6.0%} of the run's entire profit"
        )
        print(
            f"    net   fabricated ${t['net_fabricated_pnl']:>12,.0f}  "
            f"= {t['net_as_fraction_of_run_profit']:>6.0%}"
        )
    d = out["discrimination"]
    print(f"\n  DISCRIMINATION — of {d['large_moves']} large one-bar mark moves in this run:")
    print(f"    qty UNCHANGED (split not applied)          : {d['qty_unchanged']}")
    print(f"    qty changed at all                         : {d['qty_changed']}")
    print(
        f"    qty changed CONSISTENTLY with a split      : {d['qty_changed_consistent_with_split']}"
    )
    if not d["qty_changed_consistent_with_split"]:
        print("    -> not one large split was applied to a held position in this run.")
    print("\n  worst events:")
    for e in out["worst_events"][:10]:
        print(
            f"    {e['iid']:20} {e['leg']:7} qty={e['qty']:>10,.0f} "
            f"{e['pmark']:>9.3f}->{e['mark']:<9.3f} x{e['move']:>7.2f}  "
            f"d_upnl=${e['d_upnl']:>12,.0f}"
        )
    print(f"\n  {out['claim_boundary']}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "result.json").write_text(
        json.dumps(out, indent=2, sort_keys=True, default=float) + "\n"
    )
    after = sum(1 for _ in LEDGER.open()) if LEDGER.exists() else 0
    if before != after:
        raise SystemExit(f"ABORT: ledger moved {before} -> {after}; the zero-trial claim is void.")
    print(f"\n  ledger unmoved ({after}); 0 hypotheses consumed")
    print(f"  written: {OUT_DIR / 'result.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
