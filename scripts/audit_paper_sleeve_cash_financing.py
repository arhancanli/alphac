#!/usr/bin/env python3
"""Measure the Alpaca paper sleeves' daily cash, margin debit and idle-cash yield (read-only).

WHY. config/cost_realism_contract.json leaves `financing_margin_interest` and
`cash_yield_on_idle_capital` NOT_CHARGED for want of a rate source. Before wiring one, this
measures whether either matters on the record as it stands.

HOW. For every calendar day from the first fill or mark to the last mark: positions from the filled
orders, long and short market value at the last lake close on or before the day, and
cash = equity - long + short, where equity is the latest broker mark (`equity_curve.equity_quote`).
It reads the same databases and lakes as scripts/derive_cost_charged_live_curves.py, through that
script's own loaders. The rate is the point-in-time federal funds rate (DFF) published on or before
each day.

WHAT IT REPORTS, per sleeve: margin-debit days and the largest debit; mean long, short, net and cash
shares of equity; what idle cash would have earned at that rate; and the drag the standard
excess-return Sharpe charges, rate times net exposure, because
(P&L + rate x cash) - rate x equity = P&L - rate x (long - short).

It writes nothing unless --out is given, charges nothing, and changes no curve.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Final

import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parents[1]
DERIVE_SCRIPT: Final[Path] = REPO / "scripts" / "derive_cost_charged_live_curves.py"
RATE_SERIES: Final[Path] = REPO / "data" / "lake_macro_vintage" / "tier1_daily" / "DFF.parquet"
DAYS_PER_YEAR: Final[float] = 365.0


def _load_derive() -> Any:
    spec = importlib.util.spec_from_file_location("derive_cost_charged_live_curves", DERIVE_SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {DERIVE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _rate_lookup() -> pd.DataFrame:
    rates = pd.read_parquet(RATE_SERIES, columns=["obs_date", "value", "publication_date"])
    rates["obs_date"] = pd.to_datetime(rates["obs_date"]).dt.strftime("%Y-%m-%d")
    rates["publication_date"] = pd.to_datetime(rates["publication_date"]).dt.strftime("%Y-%m-%d")
    return rates.sort_values(["publication_date", "obs_date"])


def _rate_known_on(rates: pd.DataFrame, date: str) -> float | None:
    """The latest observation published on or before `date`, in percent per year."""
    known = rates.loc[rates["publication_date"] <= date]
    if known.empty:
        return None
    return float(known.sort_values("obs_date")["value"].iloc[-1])


def _equity_by_date(derive: Any, db: Path) -> dict[str, float]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT ts, equity_quote FROM equity_curve WHERE ts IS NOT NULL ORDER BY ts"
    ).fetchall()
    con.close()
    return {derive._date(int(ts)): float(value) for ts, value in rows if value is not None}


def measure_sleeve(derive: Any, rates: pd.DataFrame, profile: str) -> dict[str, Any]:
    db = REPO / "var" / f"trading_{profile}.sqlite"
    if not db.exists():
        return {"database": str(db.relative_to(REPO)), "calendar_days": 0}
    fills = derive.read_fills(db)
    marks = _equity_by_date(derive, db)
    if not fills or not marks:
        return {"database": str(db.relative_to(REPO)), "calendar_days": 0}
    bars = {symbol: derive.load_bars(symbol) for symbol in {fill["symbol"] for fill in fills}}
    fills_by_date: dict[str, list[dict[str, Any]]] = {}
    for fill in fills:
        fills_by_date.setdefault(fill["date"], []).append(fill)
    position: dict[str, float] = {}
    unmarked: set[str] = set()
    rows: list[dict[str, Any]] = []
    cursor = dt.date.fromisoformat(min(fills[0]["date"], min(marks)))
    end = dt.date.fromisoformat(max(marks))
    equity: float | None = None
    while cursor <= end:
        date = cursor.isoformat()
        for fill in fills_by_date.get(date, []):
            signed = fill["qty"] if fill["side"] == "buy" else -fill["qty"]
            position[fill["symbol"]] = position.get(fill["symbol"], 0.0) + signed
        equity = marks.get(date, equity)
        if equity is not None:
            long_value = short_value = 0.0
            for symbol, quantity in position.items():
                if abs(quantity) < 1e-9:
                    continue
                symbol_bars = bars.get(symbol)
                close = (
                    derive.last_close_on_or_before(symbol_bars, date)
                    if symbol_bars is not None
                    else None
                )
                if close is None:
                    unmarked.add(symbol)
                    continue
                if quantity > 0:
                    long_value += quantity * close
                else:
                    short_value += -quantity * close
            rows.append(
                {
                    "date": date,
                    "equity": equity,
                    "long": long_value,
                    "short": short_value,
                    "cash": equity - long_value + short_value,
                    "rate_pct": _rate_known_on(rates, date),
                }
            )
        cursor += dt.timedelta(days=1)
    frame = pd.DataFrame(rows)
    daily_rate = frame["rate_pct"].fillna(0.0) / 100.0 / DAYS_PER_YEAR
    idle_cash_yield = float((frame["cash"].clip(lower=0.0) * daily_rate).sum())
    net_share = (frame["long"] - frame["short"]) / frame["equity"]
    mean_rate = float(frame["rate_pct"].mean())
    return {
        "database": str(db.relative_to(REPO)),
        "calendar_days": len(frame),
        "first_date": frame["date"].iloc[0],
        "last_date": frame["date"].iloc[-1],
        "fills": len(fills),
        "symbols_without_marks": sorted(unmarked),
        "equity_start": round(float(frame["equity"].iloc[0]), 2),
        "equity_end": round(float(frame["equity"].iloc[-1]), 2),
        "mean_long_over_equity": round(float((frame["long"] / frame["equity"]).mean()), 4),
        "mean_short_over_equity": round(float((frame["short"] / frame["equity"]).mean()), 4),
        "mean_net_exposure_over_equity": round(float(net_share.mean()), 4),
        "mean_cash_over_equity": round(float((frame["cash"] / frame["equity"]).mean()), 4),
        "min_cash_over_equity": round(float((frame["cash"] / frame["equity"]).min()), 4),
        "margin_debit_calendar_days": int((frame["cash"] < 0.0).sum()),
        "largest_margin_debit_usd": round(float(max(0.0, -frame["cash"].min())), 2),
        "mean_rate_pct": round(mean_rate, 3),
        "idle_cash_yield_usd_if_credited": round(idle_cash_yield, 2),
        "idle_cash_yield_over_start_equity": round(
            idle_cash_yield / float(frame["equity"].iloc[0]), 5
        ),
        "excess_return_drag_per_year_on_net_exposure": round(
            float(net_share.mean()) * mean_rate / 100.0, 5
        ),
    }


def build() -> dict[str, Any]:
    derive = _load_derive()
    rates = _rate_lookup()
    return {
        "schema": "canli.alphac-paper-sleeve-cash-financing-audit.v1",
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "rate_series": str(RATE_SERIES.relative_to(REPO)),
        "claim_boundary": (
            "Reconstructed cash from filled orders, lake closes and broker equity marks. It "
            "measures whether margin financing or idle-cash yield would change the paper record; "
            "it charges nothing and is not a statement of what any broker pays."
        ),
        "sleeves": {
            key: measure_sleeve(derive, rates, profile)
            for key, profile in derive.SLEEVES.items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="also write the JSON here")
    args = parser.parse_args(argv)
    payload = build()
    text = json.dumps(payload, indent=1, sort_keys=True)
    if args.out is not None:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
