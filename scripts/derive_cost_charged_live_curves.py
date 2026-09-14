#!/usr/bin/env python3
"""Charge the equity paper-live record the frictions a funded book would pay, beside the broker NAV.

WHY. The published NAV of the three Alpaca paper sleeves (AlphaMax, AlphaTrend, AlphaVintage) is
the broker's account equity verbatim: no commission, no spread, no impact, no borrow, no
financing. Research charges roughly 6 bp a side plus 50 bp a year on shorts. The owner's Sharpe
target is net, so the forward record must be net of what a funded book would pay, and the
correction must keep the original beside it (docs/design/COST_REALISM_AUDIT_2026-09-14.md).

WHAT IS CHARGED, from the same TransactionCostModel research uses, per filled order:
  commission   notional x equity commission (CostsCfg.equity_commission_bps)
  spread       notional x half spread (CostsCfg.equity_half_spread_bps)
  impact       notional x square-root impact(notional, ADV, sigma), ADV the 30-session median
               quote volume and sigma the EWMA (halflife 240 sessions) daily volatility, both
               as of the session BEFORE the fill, from the daily-bar lake; a fill above the
               model's 5 percent participation tripwire is charged AT the tripwire and flagged
               understated, never skipped
  borrow       short notional x equity borrow rate / 365 per calendar day, short notional
               reconstructed from the cumulative signed filled quantity per symbol marked at the
               last lake close on or before the day (the broker persists no daily positions)
NOT charged, and said so in config/cost_realism_contract.json: latency (the 2 bp research add-on
is an intra-second arrival quantity; live equity submit-to-fill is hours, a different thing),
financing on margin debit, cash yield on idle cash, FX. Each is a contract row with a reason.

A fill whose symbol has no lake bars is charged commission and spread and listed UNPRICED for
impact; the count is published. Nothing here reads a return or spends an identity.

Reads var/trading_equity.sqlite, var/trading_managed_futures.sqlite and var/trading_alphavintage.sqlite
(read-only) and the daily-bar lakes; writes artifacts/engineering/cost_charged_live_curves.json,
read by scripts/paper_trading_state.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from alphaforge.config.settings import load_settings  # noqa: E402
from alphaforge.core.instruments import Instrument  # noqa: E402
from alphaforge.core.types import AssetClass, Liquidity, MarketType  # noqa: E402
from alphaforge.costs.model import MAX_ADV_PARTICIPATION, TransactionCostModel  # noqa: E402

SCHEMA: Final[str] = "canli.alphac-cost-charged-live-curves.v1"
CONTRACT: Final[Path] = REPO / "config" / "cost_realism_contract.json"
OUTPUT: Final[Path] = REPO / "artifacts" / "engineering" / "cost_charged_live_curves.json"
#: Daily-bar lakes, in order of precedence on a date both hold. The equity lake carries every
#: traded stock and ETF but only from 2026 for the ETFs; the managed-futures lake carries the
#: ETFs from 2024, which the 30-session ADV and the volatility estimate need at the go-live.
LAKES: Final[tuple[Path, ...]] = (
    REPO / "data" / "lake" / "ohlcv_1d",
    REPO / "data" / "lake_mf" / "ohlcv_1d",
)
#: published sleeve key -> live_cycle profile (the trading database name)
SLEEVES: Final[dict[str, str]] = {
    "alphamax": "equity",
    "managed_futures": "managed_futures",
    "alphavintage": "alphavintage",
}
ADV_SESSIONS: Final[int] = 30
SIGMA_HALFLIFE_SESSIONS: Final[int] = 240
SIGMA_MIN_SESSIONS: Final[int] = 30
ADV_MIN_SESSIONS: Final[int] = 10
DAYS_PER_YEAR: Final[float] = 365.0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _date(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000.0, tz=dt.UTC).strftime("%Y-%m-%d")


def equity_instrument(symbol: str) -> Instrument:
    """A minimal cash-equity instrument: the cost model routes on market type and id only."""
    return Instrument(
        instrument_id=f"XUSE:CASH:{symbol}USD",
        asset_class=AssetClass.EQUITY,
        market_type=MarketType.CASH,
        base=symbol,
        quote="USD",
        tick_size=0.01,
        lot_size=1.0,
        min_qty=1.0,
        min_notional=1.0,
        contract_multiplier=1.0,
        can_short=True,
        maker_fee_bps=0.0,
        taker_fee_bps=0.0,
        funding_interval_hours=None,
        listed_ts=0,
        delisted_ts=None,
    )


def load_bars(symbol: str) -> pd.DataFrame | None:
    """Daily bars for one symbol from the lake: date index, close and quote volume."""
    files = [
        f
        for lake in LAKES
        for f in sorted((lake / f"instrument_id=XUSE:CASH:{symbol}USD").glob("year=*/data.parquet"))
    ]
    if not files:
        return None
    frame = pd.concat(
        [pd.read_parquet(f, columns=["ts_open", "close", "quote_volume"]) for f in files]
    )
    frame["date"] = pd.to_datetime(frame["ts_open"], utc=True).dt.strftime("%Y-%m-%d")
    frame = frame.drop_duplicates("date").set_index("date").sort_index()
    frame["log_return"] = np.log(frame["close"]).diff()
    return frame[["close", "quote_volume", "log_return"]]


def as_of_stats(bars: pd.DataFrame, date: str) -> tuple[float | None, float | None]:
    """(adv_quote, sigma_daily) using only sessions strictly before `date`."""
    prior = bars.loc[bars.index < date]
    if len(prior) < ADV_MIN_SESSIONS:
        return None, None
    adv = float(prior["quote_volume"].tail(ADV_SESSIONS).median())
    returns = prior["log_return"].dropna()
    if len(returns) < SIGMA_MIN_SESSIONS:
        return adv, None
    sigma = float(returns.ewm(halflife=SIGMA_HALFLIFE_SESSIONS).std().iloc[-1])
    return (adv if adv > 0 else None), (sigma if sigma > 0 else None)


def last_close_on_or_before(bars: pd.DataFrame, date: str) -> float | None:
    prior = bars.loc[bars.index <= date]
    return float(prior["close"].iloc[-1]) if len(prior) else None


def read_fills(db: Path) -> list[dict[str, Any]]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT ts, instrument_id, side, filled_qty, fill_price, notional FROM fills "
        "WHERE status = 'filled' AND filled_qty > 0 AND fill_price > 0 ORDER BY ts, client_order_id"
    ).fetchall()
    con.close()
    return [
        {
            "ts": int(ts),
            "date": _date(int(ts)),
            "symbol": str(symbol),
            "side": str(side).lower(),
            "qty": float(qty),
            "price": float(price),
            "notional": float(notional) if notional else float(qty) * float(price),
        }
        for ts, symbol, side, qty, price, notional in rows
    ]


def read_mark_dates(db: Path) -> list[str]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute("SELECT ts FROM equity_curve WHERE ts IS NOT NULL ORDER BY ts").fetchall()
    con.close()
    return sorted({_date(int(ts)) for (ts,) in rows})


def charge_sleeve(key: str, profile: str) -> dict[str, Any]:
    settings = load_settings(profile)
    model = TransactionCostModel.from_settings(settings)
    cfg = settings.costs
    db = REPO / "var" / f"trading_{profile}.sqlite"
    fills = read_fills(db) if db.exists() else []
    bars: dict[str, pd.DataFrame | None] = {}
    by_date: dict[str, dict[str, float]] = {}
    unpriced: list[dict[str, Any]] = []
    floored = 0
    priced = 0

    def bucket(date: str) -> dict[str, float]:
        return by_date.setdefault(
            date, {"commission": 0.0, "spread": 0.0, "impact": 0.0, "borrow": 0.0}
        )

    for fill in fills:
        symbol = fill["symbol"]
        if symbol not in bars:
            bars[symbol] = load_bars(symbol)
        inst = equity_instrument(symbol)
        notional = fill["notional"]
        day = bucket(fill["date"])
        day["commission"] += notional * model.fee_frac(inst, Liquidity.TAKER)
        day["spread"] += notional * model.half_spread_frac(inst)
        symbol_bars = bars[symbol]
        adv, sigma = (
            as_of_stats(symbol_bars, fill["date"]) if symbol_bars is not None else (None, None)
        )
        if adv is None or sigma is None:
            unpriced.append(
                {
                    **fill,
                    "reason": "no_lake_bars" if symbol_bars is None else "insufficient_history",
                }
            )
            continue
        participation = notional / adv
        charged_notional = notional
        if participation > MAX_ADV_PARTICIPATION:
            charged_notional = MAX_ADV_PARTICIPATION * adv
            floored += 1
        day["impact"] += notional * model.impact_frac(charged_notional, adv, sigma)
        priced += 1

    # Borrow on reconstructed short notional, every calendar day from the first fill to the
    # last mark, at the last lake close on or before the day.
    position: dict[str, float] = {}
    fills_by_date: dict[str, list[dict[str, Any]]] = {}
    for fill in fills:
        fills_by_date.setdefault(fill["date"], []).append(fill)
    mark_dates = read_mark_dates(db) if db.exists() else []
    borrow_frac_day = model.borrow_frac_per_day()
    short_days = 0
    unmarked_short_symbols: set[str] = set()
    if fills:
        start = dt.date.fromisoformat(fills[0]["date"])
        end = dt.date.fromisoformat(max([fills[-1]["date"], *mark_dates]))
        day_cursor = start
        while day_cursor <= end:
            date = day_cursor.isoformat()
            for fill in fills_by_date.get(date, []):
                signed = fill["qty"] if fill["side"] == "buy" else -fill["qty"]
                position[fill["symbol"]] = position.get(fill["symbol"], 0.0) + signed
            short_notional = 0.0
            for symbol, qty in position.items():
                if qty >= -1e-9:
                    continue
                symbol_bars = bars.get(symbol)
                mark = (
                    last_close_on_or_before(symbol_bars, date) if symbol_bars is not None else None
                )
                if mark is None:
                    unmarked_short_symbols.add(symbol)
                    continue
                short_notional += -qty * mark
            if short_notional > 0:
                bucket(date)["borrow"] += short_notional * borrow_frac_day
                short_days += 1
            day_cursor += dt.timedelta(days=1)

    cumulative = 0.0
    series: dict[str, dict[str, float]] = {}
    for date in sorted(by_date):
        row = by_date[date]
        total = sum(row.values())
        cumulative += total
        series[date] = {
            **{k: round(v, 6) for k, v in row.items()},
            "total": round(total, 6),
            "cumulative": round(cumulative, 6),
        }
    totals = {
        k: round(sum(v[k] for v in by_date.values()), 2)
        for k in ("commission", "spread", "impact", "borrow")
    }
    totals["total"] = round(sum(totals.values()), 2)
    return {
        "profile": profile,
        "database": str(db.relative_to(REPO)),
        "database_sha256": _sha256(db) if db.exists() else None,
        "model": {
            "equity_commission_bps": cfg.equity_commission_bps,
            "equity_half_spread_bps": cfg.equity_half_spread_bps,
            "impact_coef": cfg.impact_coef,
            "equity_borrow_bps_annual": cfg.equity_borrow_bps_annual,
            "participation_tripwire": MAX_ADV_PARTICIPATION,
            "adv_sessions_median": ADV_SESSIONS,
            "sigma_ewm_halflife_sessions": SIGMA_HALFLIFE_SESSIONS,
            "latency_addon_bps_not_charged": cfg.latency_addon_bps,
        },
        "fills_total": len(fills),
        "fills_priced_for_impact": priced,
        "fills_unpriced_for_impact": len(unpriced),
        "fills_impact_floored_at_tripwire": floored,
        "unpriced_fills": unpriced[:50],
        "short_calendar_days_charged": short_days,
        "short_symbols_without_marks": sorted(unmarked_short_symbols),
        "traded_notional": round(sum(f["notional"] for f in fills), 2),
        "totals_usd": totals,
        "charges_by_date": series,
        "first_fill_date": fills[0]["date"] if fills else None,
        "last_fill_date": fills[-1]["date"] if fills else None,
    }


def build() -> dict[str, Any]:
    sleeves = {key: charge_sleeve(key, profile) for key, profile in SLEEVES.items()}
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "author": "Arhan Canli",
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "contract": {
            "path": str(CONTRACT.relative_to(REPO)),
            "sha256": _sha256(CONTRACT) if CONTRACT.exists() else None,
        },
        "claim_boundary": (
            "Model-charged frictions on the Alpaca paper record, derived from every filled order "
            "and the reconstructed daily short book, at research's own cost parameters. The "
            "broker NAV is kept as the original; the cost-charged curve is the broker NAV less "
            "these cumulative charges. Latency, financing, cash yield and FX are not charged and "
            "the contract says so. A charged curve is not a real-money result."
        ),
        "sleeves": sleeves,
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    payload = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for key, sleeve in payload["sleeves"].items():
        t = sleeve["totals_usd"]
        print(
            f"{key}: {sleeve['fills_total']} fills, ${sleeve['traded_notional']:,.0f} traded; charged "
            f"${t['total']:,.2f} (commission {t['commission']:,.2f}, spread {t['spread']:,.2f}, "
            f"impact {t['impact']:,.2f}, borrow {t['borrow']:,.2f}); impact unpriced "
            f"{sleeve['fills_unpriced_for_impact']}, floored {sleeve['fills_impact_floored_at_tripwire']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
