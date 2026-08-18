"""The +893% phantom: a published return manufactured by two accounts in one curve.

WHAT HAPPENED, 2026-08-11. canlicapital.com served this as the flagship's live record:

    2026-08-07 : 100,000.00
    2026-08-08 : 400,207.73     <- a 300% gain in one day

The book is market-neutral and runs gross <= 1.0x. It cannot do that, and it did not. At the v3
account cutover, `live_cycle` wrote broker history with INSERT OR REPLACE, so rows from the
SUPERSEDED v2 account survived at any timestamp the new account's history did not happen to cover:

    AlphaTrend  08-06 00:00  $1,000,000.00   (v3 account)
    AlphaTrend  08-07 05:32  $  100,681.45   (v2 account, $100k)
    AlphaTrend  08-08 00:00  $1,000,000.00   (v3 again)

Rebasing on the first mark turned the v2 row into 10,068, and the step to the next day published as
+893%. At one third weight that is +297% on the book — the 400,207 above.

TWO DEFECTS, both pinned here:
  1. several marks per DAY meant two points shared a date, and the "return" between them was not a
     return at all;
  2. nothing rejected a step that is arithmetically impossible for the strategy.

The durable fix is in live_cycle (replace the curve rather than merge into it, so it can only ever
hold one account's history). These tests pin the READER, because the reader is what published the
number and must be safe even against a database that is already contaminated.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import paper_trading_state as m  # noqa: E402

_DAY = 86_400_000
#: 2026-08-07T00:00Z — the v3 go-live used throughout these tests. Verified against
#: paper_trading_state._epoch_to_date rather than assumed; an off-by-one-day constant here would
#: make every assertion below test the wrong day while still looking plausible.
_T0 = 1_786_060_800_000


def _db(tmp_path: Path, marks: list[tuple[int, float]]) -> Path:
    p = tmp_path / "trading_x.sqlite"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE equity_curve (ts INTEGER PRIMARY KEY, equity_quote REAL)")
    con.executemany("INSERT INTO equity_curve VALUES (?,?)", marks)
    con.commit()
    con.close()
    return p


def _rets(curve: list[dict]) -> list[float]:
    return [
        curve[i]["equity"] / curve[i - 1]["equity"] - 1.0
        for i in range(1, len(curve))
        if curve[i - 1]["equity"]
    ]


def test_the_exact_phantom_cannot_be_published(tmp_path: Path) -> None:
    """THE TEST THIS FILE EXISTS FOR — the real AlphaTrend marks that produced 400,207."""
    db = _db(tmp_path, [
        (_T0 - _DAY, 1_000_000.00),      # v3
        (_T0, 1_000_000.00),             # v3
        (_T0 + 19_920_000, 100_681.45),  # v2 leftover, SAME DAY as the v3 mark above
        (_T0 + _DAY, 1_000_000.00),      # v3
        (_T0 + 2 * _DAY, 1_000_086.82),  # v3
    ])
    curve = m.read_live_db(db, go_live="2026-08-07")
    dates = [p["date"] for p in curve]
    assert len(dates) == len(set(dates)), f"one point per day required, got {dates}"
    worst = max((abs(r) for r in _rets(curve)), default=0.0)
    assert worst < 0.5, (
        f"published a {worst:+.1%} daily move — this is the +893% phantom, which reached "
        f"canlicapital.com as a 300% one-day gain. curve={curve}"
    )


def test_superseded_account_marks_are_dropped_not_spliced(tmp_path: Path) -> None:
    """The surviving segment must be the CURRENT account — the sleeve trades that one today."""
    db = _db(tmp_path, [
        (_T0, 100_000.0),                # old $100k account
        (_T0 + _DAY, 100_500.0),         # old
        (_T0 + 2 * _DAY, 1_000_000.0),   # NEW $1M account
        (_T0 + 3 * _DAY, 1_004_000.0),   # new
    ])
    curve = m.read_live_db(db, go_live="2026-08-07")
    assert len(curve) == 2, f"expected only the current account's 2 marks, got {curve}"
    assert curve[0]["equity"] == pytest.approx(100_000.0)   # rebased to the $100k display base
    assert curve[-1]["equity"] == pytest.approx(100_400.0)  # +0.4%, the real move


def test_a_real_move_is_never_mistaken_for_an_account_switch(tmp_path: Path) -> None:
    """The guard must not eat genuine performance.

    A sleeve's daily sd here is 0.7%-1.3%, so the 50% threshold is ~40 standard deviations away.
    A guard that trimmed real drawdowns would be worse than the bug it replaced, because it would
    flatter the record — silently and in our favour.
    """
    db = _db(tmp_path, [
        (_T0, 1_000_000.0),
        (_T0 + _DAY, 900_000.0),   # -10%: a very bad day, but a REAL one
        (_T0 + 2 * _DAY, 940_000.0),
    ])
    curve = m.read_live_db(db, go_live="2026-08-07")
    assert len(curve) == 3, "a -10% day is performance, not an account change"
    assert curve[1]["equity"] == pytest.approx(90_000.0)


def test_many_marks_per_day_collapse_to_the_close(tmp_path: Path) -> None:
    """equity_curve holds several marks a day (daily cycle + hourly refresh). Keep the last."""
    db = _db(tmp_path, [
        (_T0, 1_000_000.0),
        (_T0 + 3_600_000, 1_002_000.0),
        (_T0 + 7_200_000, 1_003_000.0),   # the day's close
        (_T0 + _DAY, 1_005_000.0),
    ])
    curve = m.read_live_db(db, go_live="2026-08-07")
    assert [p["date"] for p in curve] == ["2026-08-07", "2026-08-08"]
    assert curve[0]["equity"] == pytest.approx(100_000.0)
    # 1,003,000 -> 1,005,000 is +0.199%, NOT 1,000,000 -> 1,005,000 (+0.5%).
    # Tolerance is one cent because the reader publishes rounded currency; asserting tighter than
    # the function's own precision tests the rounding, not the behaviour.
    assert curve[1]["equity"] == pytest.approx(100_000.0 * 1_005_000 / 1_003_000, abs=0.01)


def test_pre_go_live_marks_are_excluded(tmp_path: Path) -> None:
    """An account that sat idle before the sleeve launched must not contribute to its record."""
    db = _db(tmp_path, [
        (_T0 - 5 * _DAY, 1_000_000.0),
        (_T0, 1_000_000.0),
        (_T0 + _DAY, 1_001_000.0),
    ])
    curve = m.read_live_db(db, go_live="2026-08-07")
    assert [p["date"] for p in curve] == ["2026-08-07", "2026-08-08"]


def test_an_empty_or_missing_db_seeds_honestly(tmp_path: Path) -> None:
    """No marks means the $100k seed at go-live — never a fabricated path."""
    assert m.read_live_db(tmp_path / "nope.sqlite", go_live="2026-08-07") == [
        {"date": "2026-08-07", "equity": 100000.0}
    ]
    assert m.read_live_db(_db(tmp_path, []), go_live="2026-08-07") == [
        {"date": "2026-08-07", "equity": 100000.0}
    ]
