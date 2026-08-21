"""Does the forward record have holes? Measure, per sleeve, every day since go-live with no mark.

WHY THIS EXISTS. The forward record is the only evidence that can defeat deflation — a
pre-registered book run forward is N=1, so its hurdle is 0.877 at five years against 2.44 for a
backtest selected from 162 hypothesis identities. Its entire value is being ONE continuous test of
ONE specification, and a gap breaks that as surely as an undeclared configuration change does.

The difference is that a configuration change is now guarded and a gap is not. Nothing measures
whether the record is continuous, so a sleeve could quietly stop marking and the published curve
would simply have fewer points — which looks like a shorter record rather than a broken one.

Reads the per-sleeve trading databases read-only. Opens no market data, registers no hypothesis,
changes nothing: 0 trials.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "artifacts" / "engineering" / "record_continuity.json"
STATE = REPO / "data" / "paper" / "state.json"

# The per-sleeve trading databases, as paper_trading_state.py reads them.
SLEEVES: dict[str, dict[str, Any]] = {
    "alphaforge": {"db": "var/trading_crypto_perp.sqlite", "trades_24_7": True},
    "alphamax": {"db": "var/trading_equity.sqlite", "trades_24_7": False},
    "managed_futures": {"db": "var/trading_managed_futures.sqlite", "trades_24_7": False},
    "alphavintage": {"db": "var/trading_alphavintage.sqlite", "trades_24_7": False},
}

# A sleeve that misses more than this share of days since go-live is not producing a continuous
# record. Declared here rather than discovered from the data: a threshold fitted to today's gap
# rate would pass whatever the gap rate happens to be, which is not a threshold.
MAX_GAP_RATE = 0.20


def _epoch_to_date(ts: int | float) -> str:
    seconds = float(ts) / 1000.0 if float(ts) > 1e11 else float(ts)
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC).date().isoformat()


def marked_days(db: Path, go_live: str) -> set[str]:
    if not db.exists():
        return set()
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = con.execute(
            "SELECT ts FROM equity_curve WHERE ts IS NOT NULL ORDER BY ts ASC"
        ).fetchall()
        con.close()
    except sqlite3.Error:
        return set()
    return {d for (ts,) in rows if (d := _epoch_to_date(ts)) >= go_live}


def main() -> int:
    if not STATE.exists():
        print("no published state; refusing to audit a record that has not been written")
        return 1
    state = json.loads(STATE.read_text())
    go_live = state["go_live_date"]
    today = dt.datetime.now(tz=dt.UTC).date()
    start = dt.date.fromisoformat(go_live)
    # Calendar days, not trading days: the crypto sleeve trades 24/7 and the equity sleeves do
    # not, so a weekend is a legitimate absence for some sleeves and a real gap for others. Both
    # counts are reported and the CALENDAR one is never used as the verdict on its own.
    calendar_days = [
        (start + dt.timedelta(days=i)).isoformat() for i in range((today - start).days + 1)
    ]

    sleeves: dict[str, Any] = {}
    for key, spec in SLEEVES.items():
        rel = spec["db"]
        marks = marked_days(REPO / rel, go_live)
        missing = [d for d in calendar_days if d not in marks]
        # A weekend absence is legitimate for a sleeve that does not trade weekends, and a REAL
        # gap for one that trades around the clock. Classified per sleeve rather than counted the
        # same way for all four.
        if spec["trades_24_7"]:
            real = list(missing)
            legitimate: list[str] = []
        else:
            real = [d for d in missing if dt.date.fromisoformat(d).weekday() < 5]
            legitimate = [d for d in missing if dt.date.fromisoformat(d).weekday() >= 5]
        expected = [
            d
            for d in calendar_days
            if spec["trades_24_7"] or dt.date.fromisoformat(d).weekday() < 5
        ]
        sleeves[key] = {
            "database": rel,
            "database_exists": (REPO / rel).exists(),
            "trades_24_7": spec["trades_24_7"],
            "days_since_go_live": len(calendar_days),
            "days_expected": len(expected),
            "days_marked": len(marks),
            "real_gaps": len(real),
            "real_gap_days": real,
            "legitimate_absences": len(legitimate),
            "legitimate_absence_days": legitimate,
            "gap_rate": len(real) / len(expected) if expected else 0.0,
            "longest_consecutive_gap": _longest_run(expected, marks),
        }

    worst = max(sleeves.values(), key=lambda s: s["gap_rate"]) if sleeves else None
    # Days missing on EVERY sleeve are systemic — the tick did not run — rather than a problem
    # with any one sleeve, and that is the more useful thing to say.
    systemic = sorted(set.intersection(*(set(s["real_gap_days"]) for s in sleeves.values())))
    result = {
        "schema": "canli.alphac-record-continuity.v1",
        "claim_boundary": (
            "Reads the per-sleeve trading databases read-only. Opens no market data, registers no "
            "hypothesis identity and changes nothing. 0 trials."
        ),
        "go_live_date": go_live,
        "as_of": today.isoformat(),
        "days_since_go_live": len(calendar_days),
        "max_gap_rate_threshold": MAX_GAP_RATE,
        "threshold_basis": (
            "Declared, not fitted. A threshold derived from today's gap rate would pass whatever "
            "the gap rate happens to be, which is not a threshold."
        ),
        "sleeves": sleeves,
        "worst_gap_rate": worst["gap_rate"] if worst else None,
        "passes": all(s["gap_rate"] <= MAX_GAP_RATE for s in sleeves.values()),
        "systemic_gap_days": systemic,
        "systemic_note": (
            "Days missing on EVERY sleeve are systemic — the tick did not run or did not mark — "
            "rather than a fault in any one sleeve."
        ),
        "how_a_gap_is_classified": (
            "A weekend absence is LEGITIMATE for a sleeve that does not trade weekends and a REAL "
            "gap for one that trades around the clock. Classified per sleeve, because counting "
            "them the same way makes a closed market and a broken loop look identical."
        ),
        "what_this_does_not_measure": (
            "Whether a mark is CORRECT — only whether one exists. A sleeve marking the same "
            "equity every day would show a perfect continuity record and a frozen curve. That is "
            "the publish gate's job (check_published_state), not this one's."
        ),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(f"  {len(calendar_days)} days since go-live ({go_live})")
    print(
        f"  {'sleeve':18} {'24/7':>5} {'expect':>7} {'marked':>7} "
        f"{'REAL gaps':>10} {'rate':>7} {'longest':>8}"
    )
    for key, s_ in sleeves.items():
        print(
            f"  {key:18} {s_['trades_24_7']!s:>5} {s_['days_expected']:>7} "
            f"{s_['days_marked']:>7} {s_['real_gaps']:>10} {s_['gap_rate']:>6.1%} "
            f"{s_['longest_consecutive_gap']:>8}"
        )
    if systemic:
        print(f"\n  SYSTEMIC — missing on every sleeve: {', '.join(systemic)}")
        for day in systemic:
            print(f"    {day} is a {dt.date.fromisoformat(day).strftime('%A')}")
    print(f"\n  passes (gap rate <= {MAX_GAP_RATE:.0%}): {result['passes']}")
    return 0


def _longest_run(days: list[str], marks: set[str]) -> int:
    longest = run = 0
    for day in days:
        run = 0 if day in marks else run + 1
        longest = max(longest, run)
    return longest


if __name__ == "__main__":
    raise SystemExit(main())
