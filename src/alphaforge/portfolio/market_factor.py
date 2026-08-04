"""Strategic-tilt market factor — the DISCLOSED beta overlay's market return (0.5 BTC + 0.5 SPY).

ONE definition, imported by BOTH the research book (the ``combine_book`` caller) and the live
ALPHAC curve (``combined_live`` in scripts/paper_trading_state.py), so the two published paths can
never silently diverge. The overlay is intentionally a SEPARATE, labelled beta line — it is NEVER
blended into the neutral alpha sleeves (they must stay measurably market-neutral). This module only
SOURCES the market-factor return; the sizing (+20% net long) and the additive overlay live in the
book/curve code.

Daily close-to-close simple returns from the lakes. BTC trades 24/7; SPY is closed on weekends/
holidays and contributes 0 that day (a flat position) — exactly the book's own calendar convention.
"""
from __future__ import annotations

import datetime as dt
import glob
from collections.abc import Sequence
from itertools import pairwise

import pyarrow.parquet as pq

from alphaforge.portfolio.book import DAY_MS

# (name, weight, lake glob) — the two asset classes the neutral book actually spans.
DEFAULT_MIX: tuple[tuple[str, float, str], ...] = (
    ("BTC", 0.5, "data/lake/ohlcv_1d/instrument_id=BINANCE:PERP:BTCUSDT/**/*.parquet"),
    ("SPY", 0.5, "data/lake_mf/ohlcv_1d/instrument_id=XUSE:CASH:SPYUSD/**/*.parquet"),
)
_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)


def _epochday_close_returns(glob_pat: str) -> dict[int, float]:
    """Daily close-to-close simple returns keyed by epoch-day (UTC) from a lake series."""
    files = sorted(glob.glob(glob_pat, recursive=True))
    if not files:
        raise FileNotFoundError(glob_pat)
    rows: list[tuple[int, float]] = []
    for f in files:
        d = pq.ParquetFile(f).read().to_pydict()
        for ts, close in zip(d["ts_open"], d["close"], strict=True):
            ms = int(ts.timestamp() * 1000) if hasattr(ts, "timestamp") else int(ts)
            rows.append((ms // DAY_MS, float(close)))
    by_day: dict[int, float] = {}
    for day, close in sorted(rows):  # ascending -> last close per epoch-day wins
        by_day[day] = close
    days = sorted(by_day)
    rets: dict[int, float] = {}
    for prev, day in pairwise(days):
        rets[day] = by_day[day] / by_day[prev] - 1.0 if by_day[prev] else 0.0
    return rets


def market_factor_by_epochday(
    mix: Sequence[tuple[str, float, str]] = DEFAULT_MIX,
) -> dict[int, float]:
    """The weighted market-factor daily return keyed by epoch-day, over the union of leg days.

    On a day a leg is missing (SPY weekend) that leg contributes 0 — so the factor on a
    SPY-closed day is just ``btc_weight * btc_ret``, the prototype's exact convention.
    """
    legs = {name: _epochday_close_returns(pat) for name, _, pat in mix}
    all_days: set[int] = set().union(*[set(r) for r in legs.values()])
    return {
        d: sum(w * legs[name].get(d, 0.0) for name, w, _ in mix)
        for d in all_days
    }


def market_factor_by_date(mix: Sequence[tuple[str, float, str]] = DEFAULT_MIX) -> dict[str, float]:
    """Same factor, keyed by ``YYYY-MM-DD`` (UTC) — for the live (date-string) ALPHAC path."""
    return {
        (_EPOCH + dt.timedelta(days=int(d))).strftime("%Y-%m-%d"): v
        for d, v in market_factor_by_epochday(mix).items()
    }


def latest_factor_date(mix: Sequence[tuple[str, float, str]] = DEFAULT_MIX) -> str | None:
    """The most recent date the market factor can be computed for (data-freshness guard)."""
    by_date = market_factor_by_date(mix)
    return max(by_date) if by_date else None


__all__ = [
    "DEFAULT_MIX",
    "_epochday_close_returns",
    "latest_factor_date",
    "market_factor_by_date",
    "market_factor_by_epochday",
]
