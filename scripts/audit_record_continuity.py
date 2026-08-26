"""Does the forward record have holes? Measure, per sleeve, every day since go-live with no mark.

WHY THIS EXISTS. The forward record is the only evidence that can defeat deflation — a
pre-registered book run forward is N=1, so its hurdle is 0.877 at five years against 2.44 for a
backtest selected from 228 hypothesis identities. Its entire value is being ONE continuous test of
ONE specification, and a gap breaks that as surely as an undeclared configuration change does.

The difference is that a configuration change is now guarded and a gap is not. Nothing measures
whether the record is continuous, so a sleeve could quietly stop marking and the published curve
would simply have fewer points — which looks like a shorter record rather than a broken one.

Reads the per-sleeve trading databases read-only. Opens no market data, registers no hypothesis,
changes nothing: 0 trials.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "artifacts" / "engineering" / "record_continuity.json"
STATE = REPO / "data" / "paper" / "state.json"

# The per-sleeve trading databases, as paper_trading_state.py reads them.
SLEEVES: dict[str, dict[str, Any]] = {
    "alphaforge": {
        "db": "var/trading_crypto_perp.sqlite",
        "trades_24_7": True,
        "mark_date_convention": "UTC_CALENDAR_DATE",
    },
    "alphamax": {
        "db": "var/trading_equity.sqlite",
        "trades_24_7": False,
        "mark_date_convention": "ALPACA_1D_CLOSE_D_STAMPED_D_PLUS_1_00_UTC",
    },
    "managed_futures": {
        "db": "var/trading_managed_futures.sqlite",
        "trades_24_7": False,
        "mark_date_convention": "ALPACA_1D_CLOSE_D_STAMPED_D_PLUS_1_00_UTC",
    },
    "alphavintage": {
        "db": "var/trading_alphavintage.sqlite",
        "trades_24_7": False,
        "mark_date_convention": "ALPACA_1D_CLOSE_D_STAMPED_D_PLUS_1_00_UTC",
    },
}

# A sleeve that misses more than this share of days since go-live is not producing a continuous
# record. Declared here rather than discovered from the data: a threshold fitted to today's gap
# rate would pass whatever the gap rate happens to be, which is not a threshold.
MAX_GAP_RATE = 0.20
DAY_MS = 86_400_000
XNYS = XNYSCalendar()
NEW_YORK = ZoneInfo("America/New_York")


def _epoch_to_date(ts: int | float) -> str:
    seconds = float(ts) / 1000.0 if float(ts) > 1e11 else float(ts)
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC).date().isoformat()


def _date_to_utc_midnight_ms(value: dt.date) -> int:
    return int(dt.datetime.combine(value, dt.time(), tzinfo=dt.UTC).timestamp() * 1000)


def mark_session_date(ts: int | float, *, trades_24_7: bool) -> str | None:
    """Map a stored mark timestamp to the economic session date it represents.

    Crypto marks use their UTC calendar date. Alpaca's 1D portfolio history stamps the close
    for XNYS session D at ``(D + 1) 00:00 UTC``; exact-midnight rows therefore map to the
    preceding XNYS session. The exporter also appends one current account snapshot at an
    arbitrary timestamp. That row counts only when its New York date is itself an XNYS session,
    so a weekend refresh cannot manufacture a trading-day mark.
    """
    raw = int(ts)
    ms = raw if raw > 100_000_000_000 else raw * 1000
    if trades_24_7:
        return _epoch_to_date(ms)
    if ms % DAY_MS == 0:
        session_open = XNYS.floor_bar(ms - 1, Timeframe.D1)
        return _epoch_to_date(session_open)
    local_date = dt.datetime.fromtimestamp(ms / 1000, tz=dt.UTC).astimezone(NEW_YORK).date()
    session_open = _date_to_utc_midnight_ms(local_date)
    return local_date.isoformat() if XNYS.is_session(session_open) else None


def expected_days(start: dt.date, end: dt.date, *, trades_24_7: bool) -> list[str]:
    """Expected mark dates over the inclusive range, on the sleeve's actual calendar."""
    if trades_24_7:
        return [
            (start + dt.timedelta(days=i)).isoformat()
            for i in range((end - start).days + 1)
        ]
    opens = XNYS.expected_bar_opens(
        _date_to_utc_midnight_ms(start),
        _date_to_utc_midnight_ms(end + dt.timedelta(days=1)),
        Timeframe.D1,
    )
    return [_epoch_to_date(value) for value in opens]


def marked_days(db: Path, go_live: str, *, trades_24_7: bool) -> set[str]:
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
    return {
        day
        for (ts,) in rows
        if (day := mark_session_date(ts, trades_24_7=trades_24_7)) is not None
        and day >= go_live
    }


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
        marks = marked_days(REPO / rel, go_live, trades_24_7=spec["trades_24_7"])
        missing = [d for d in calendar_days if d not in marks]
        # The equity expectation is the real XNYS session set, not weekday arithmetic. That
        # distinction is load-bearing on exchange holidays. Crypto remains a UTC 24/7 calendar.
        expected = expected_days(start, today, trades_24_7=spec["trades_24_7"])
        expected_set = set(expected)
        real = [d for d in expected if d not in marks]
        legitimate = [d for d in missing if d not in expected_set]
        expected_marks = set(expected) & marks
        sleeves[key] = {
            "database": rel,
            "database_exists": (REPO / rel).exists(),
            "trades_24_7": spec["trades_24_7"],
            "expected_calendar": "UTC_24_7" if spec["trades_24_7"] else "XNYS",
            "mark_date_convention": spec["mark_date_convention"],
            "days_since_go_live": len(calendar_days),
            "days_expected": len(expected),
            "days_marked": len(expected_marks),
            "calendar_days_marked": len(marks),
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
        "author": "Arhan Canli",
        "claim_boundary": (
            "Reads the per-sleeve trading databases read-only. Opens no market data, registers no "
            "hypothesis identity and changes nothing. Corrects session-date classification only; "
            "it changes no mark, equity, return, order, fill or configuration. 0 trials."
        ),
        "correction": {
            "status": "CORRECTED",
            "documentation": "docs/design/CORRECTION_ALPACA_SESSION_DATE_CONTINUITY.md",
            "withdrawn_finding": (
                "The v1 UTC-calendar audit called 2026-08-10 a systemic gap. The three Alpaca "
                "rows stamped 2026-08-11T00:00:00Z are the finalized 2026-08-10 XNYS closes."
            ),
            "raw_marks_rewritten": False,
        },
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
            "Dates that are expected and missing on EVERY sleeve's own calendar are systemic — "
            "the tick did not run or did not mark — rather than a fault in any one sleeve."
        ),
        "how_a_gap_is_classified": (
            "Crypto marks and expectations use UTC calendar dates. Alpaca 1D midnight-UTC marks "
            "map to the preceding XNYS session; equity expectations come from XNYS sessions, so "
            "weekends and exchange holidays are legitimate absences."
        ),
        "what_this_does_not_measure": (
            "Whether a mark is CORRECT — only whether one exists. A sleeve marking the same "
            "equity every day would show a perfect continuity record and a frozen curve. That is "
            "the publish gate's job (check_published_state), not this one's."
        ),
    }
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    result["content_hash"] = "sha256:" + hashlib.sha256(canonical).hexdigest()

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
