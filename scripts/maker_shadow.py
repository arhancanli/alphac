#!/usr/bin/env python3
"""MAKER SHADOW VALIDATION — measure, forward and honestly, what post-only execution
would actually earn on the AlphaForge crypto carry sleeve.

WHY THIS EXISTS
---------------
The execution study (artifacts/sweep/execution_savings) found the one real book-moving
lever on the whole book: switching crypto carry from taker (the live loop walks the
order-book ladder and pays taker fees) to MAKER / post-only is worth roughly +0.04 to
+0.09 net Sharpe. But that number rests on two ASSUMED inputs — a ~49% passive fill rate
and ~5bp of adverse selection — and you cannot backtest either, because whether a resting
order fills depends on where the market goes NEXT, which no historical snapshot contains.

Booking a Sharpe gain on assumed fills would be exactly the optimistic accounting this
fund exists to refuse. So we MEASURE it forward instead: sample the real top-of-book on
the instruments the sleeve actually holds, then check against the subsequent trade tape
whether a passive quote would have filled and what it was worth. After a few weeks this
yields an honest fill rate + markout, and only then do we decide on promotion.

This is a SHADOW experiment: it places no orders, touches no production code, and cannot
affect the live loop. It only observes.

    uv run python scripts/maker_shadow.py record     # sample top-of-book (run hourly)
    uv run python scripts/maker_shadow.py evaluate   # resolve matured quotes vs the tape
    uv run python scripts/maker_shadow.py report     # honest fill rate + markout so far

CONSERVATIVE BY CONSTRUCTION
----------------------------
* FILL RULE: a resting BUY at the best bid is counted filled only if the tape later prints
  STRICTLY BELOW our bid (the book traded THROUGH our level, so queue position is very
  likely satisfied). Mirrored for sells. This understates the fill rate — the honest
  direction, since an overstated fill rate is what would manufacture a fake edge.
* MARKOUT is measured against the mid at the horizon, so adverse selection (the market
  moving against us right after we get filled) shows up as a negative number and is
  subtracted from the spread we captured.
* The maker-vs-taker comparison charges the taker leg the half-spread it would really pay
  plus the taker fee, and credits the maker leg zero taker fee — no rebate is assumed.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
SHADOW_DB = _REPO / "var" / "maker_shadow.sqlite"
CRYPTO_DB = _REPO / "var" / "trading_crypto_perp.sqlite"
EXCHANGE = "binanceusdm"
HORIZON_MS = 60 * 60 * 1000          # 1h: the sleeve's cycle cadence
TAKER_FEE_BPS = 5.0                  # Binance USDT-M VIP0 taker
MAKER_FEE_BPS = 2.0                  # VIP0 maker (positive = still a fee, no rebate assumed)


def _conn() -> sqlite3.Connection:
    SHADOW_DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(SHADOW_DB)
    c.execute("""CREATE TABLE IF NOT EXISTS quotes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER NOT NULL, instrument TEXT NOT NULL, symbol TEXT NOT NULL,
        side TEXT NOT NULL,                -- 'buy' | 'sell' (the side the sleeve holds/would add)
        best_bid REAL, best_ask REAL, mid REAL, spread_bps REAL,
        maker_px REAL,                     -- where we would rest passively
        taker_px REAL,                     -- where we would cross
        resolved INTEGER NOT NULL DEFAULT 0,
        filled INTEGER,                    -- 1 filled / 0 missed (conservative rule)
        fill_ts INTEGER, mid_at_horizon REAL,
        markout_bps REAL,                  -- signed, positive = favourable after fill
        maker_edge_bps REAL,               -- maker net advantage vs crossing, incl. markout
        UNIQUE(ts, instrument, side))""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_unresolved ON quotes(resolved, ts)")
    return c


def _client():
    import ccxt
    ex = getattr(ccxt, EXCHANGE)({"enableRateLimit": True})
    ex.load_markets()
    return ex


def _live_book() -> list[tuple[str, str]]:
    """The instruments the sleeve actually holds right now, with the side it is on.

    Shadowing exactly the live book (rather than a generic universe) is the honest
    scope: these are the names a post-only switch would really have to fill.
    """
    if not CRYPTO_DB.exists():
        return []
    con = sqlite3.connect(f"file:{CRYPTO_DB}?mode=ro", uri=True)
    try:
        last = con.execute("SELECT max(cycle_ts) FROM positions_snapshots").fetchone()[0]
        if last is None:
            return []
        rows = con.execute(
            "SELECT instrument_id, qty FROM positions_snapshots WHERE cycle_ts=? AND qty != 0",
            (last,)).fetchall()
    finally:
        con.close()
    # A long position is maintained/added with a BUY; a short with a SELL.
    return [(iid, "buy" if q > 0 else "sell") for iid, q in rows]


def _symbol_for(ex, instrument_id: str) -> str | None:
    """BINANCE:PERP:XRPUSDT -> the ccxt unified symbol, via market id lookup."""
    market_id = instrument_id.rsplit(":", 1)[-1]
    for sym, m in ex.markets.items():
        if m.get("id") == market_id and m.get("swap"):
            return sym
    return None


def cmd_record(_a) -> int:
    book = _live_book()
    if not book:
        print("no live crypto positions to shadow (sleeve flat) — nothing recorded")
        return 0
    ex, con = _client(), _conn()
    now = int(time.time() * 1000)
    n = 0
    for iid, side in book:
        sym = _symbol_for(ex, iid)
        if sym is None:
            print(f"  skip {iid}: no ccxt market")
            continue
        try:
            ob = ex.fetch_order_book(sym, limit=5)
        except Exception as e:  # noqa: BLE001 — a venue hiccup must not kill the sampler
            print(f"  skip {sym}: {str(e)[:70]}")
            continue
        if not ob.get("bids") or not ob.get("asks"):
            continue
        bid, ask = float(ob["bids"][0][0]), float(ob["asks"][0][0])
        mid = 0.5 * (bid + ask)
        # Passive: join the near side. Aggressive: cross to the far side.
        maker_px, taker_px = (bid, ask) if side == "buy" else (ask, bid)
        con.execute(
            "INSERT OR IGNORE INTO quotes(ts,instrument,symbol,side,best_bid,best_ask,mid,"
            "spread_bps,maker_px,taker_px) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (now, iid, sym, side, bid, ask, mid, (ask - bid) / mid * 1e4, maker_px, taker_px))
        n += 1
    con.commit()
    con.close()
    print(f"recorded {n} shadow quotes @ {now}")
    return 0


def cmd_evaluate(_a) -> int:
    """Resolve quotes older than the horizon against the real trade tape."""
    ex, con = _client(), _conn()
    now = int(time.time() * 1000)
    rows = con.execute(
        "SELECT id,ts,symbol,side,maker_px,taker_px,mid FROM quotes "
        "WHERE resolved=0 AND ts <= ?", (now - HORIZON_MS,)).fetchall()
    if not rows:
        print("nothing matured to evaluate")
        con.close()
        return 0
    resolved = 0
    for qid, ts, sym, side, maker_px, taker_px, mid0 in rows:
        try:
            trades = ex.fetch_trades(sym, since=ts, limit=1000)
        except Exception as e:  # noqa: BLE001
            print(f"  skip {sym}: {str(e)[:70]}")
            continue
        window = [t for t in trades if ts <= t["timestamp"] <= ts + HORIZON_MS]
        # CONSERVATIVE fill rule: the tape must trade STRICTLY THROUGH our resting level.
        if side == "buy":
            hits = [t for t in window if float(t["price"]) < maker_px]
        else:
            hits = [t for t in window if float(t["price"]) > maker_px]
        filled = 1 if hits else 0
        fill_ts = int(hits[0]["timestamp"]) if hits else None

        mid_h = None
        try:
            ob = ex.fetch_order_book(sym, limit=5)
            if ob.get("bids") and ob.get("asks"):
                mid_h = 0.5 * (float(ob["bids"][0][0]) + float(ob["asks"][0][0]))
        except Exception:  # noqa: BLE001
            pass

        markout = maker_edge = None
        if filled and mid_h:
            sgn = 1.0 if side == "buy" else -1.0
            # Favourable = market moved our way after the passive fill.
            markout = sgn * (mid_h - maker_px) / maker_px * 1e4
            # Crossing would have cost the far side plus the taker fee; resting costs the
            # near side plus the maker fee, but eats the markout (adverse selection).
            taker_cost = sgn * (taker_px - mid0) / mid0 * 1e4 + TAKER_FEE_BPS
            maker_cost = sgn * (maker_px - mid0) / mid0 * 1e4 + MAKER_FEE_BPS - markout
            maker_edge = taker_cost - maker_cost
        con.execute(
            "UPDATE quotes SET resolved=1, filled=?, fill_ts=?, mid_at_horizon=?, "
            "markout_bps=?, maker_edge_bps=? WHERE id=?",
            (filled, fill_ts, mid_h, markout, maker_edge, qid))
        resolved += 1
    con.commit()
    con.close()
    print(f"resolved {resolved} quotes")
    return 0


def cmd_report(_a) -> int:
    con = _conn()
    tot, res = con.execute("SELECT count(*), sum(resolved) FROM quotes").fetchone()
    res = res or 0
    if not res:
        print(f"{tot or 0} quotes recorded, none matured yet — let it accrue.")
        con.close()
        return 0
    n_fill, = con.execute("SELECT sum(filled) FROM quotes WHERE resolved=1").fetchone()
    n_fill = n_fill or 0
    mk, mo, edge = con.execute(
        "SELECT count(*), avg(markout_bps), avg(maker_edge_bps) FROM quotes "
        "WHERE resolved=1 AND filled=1").fetchone()
    span = con.execute("SELECT min(ts), max(ts) FROM quotes").fetchone()
    days = (span[1] - span[0]) / 86_400_000 if span[0] else 0.0
    print("=" * 66)
    print("MAKER SHADOW — honest forward measurement (no orders placed)")
    print(f"  window        : {days:.1f} days | {tot} quotes, {res} matured")
    print(f"  FILL RATE     : {n_fill}/{res} = {n_fill / res:.1%}   (conservative: tape must trade THROUGH)")
    if mk:
        print(f"  mean markout  : {mo:+.2f} bps   (negative = adverse selection)")
        print(f"  maker edge    : {edge:+.2f} bps per fill vs crossing (incl. markout, no rebate assumed)")
    print("  breakeven     : the execution study needs ~27% fill @2bp adverse selection")
    print("  NOTE: not bookable until this is stable over weeks AND beats breakeven.")
    print("=" * 66)
    con.close()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="maker_shadow")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("record").set_defaults(fn=cmd_record)
    sub.add_parser("evaluate").set_defaults(fn=cmd_evaluate)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
