"""Generate the paper-trading state JSON the Meridian web app + landing render.

THREE algorithms, presented honestly:
  1. AlphaForge - crypto funding carry (LIVE hourly broker-loop paper).
  2. AlphaMax   - US-equity 12-1 momentum (daily forward paper, realized next-open fills).
  3. ALPHAC     - the cross-asset book = AlphaForge (+) AlphaMax, equal-risk (the flagship).

Radical-transparency rules baked in: every RESEARCH curve is labelled simulation; every LIVE
curve starts at go-live (no fabricated history); metrics are the honest forward numbers (grade
C+, deflated forward Sharpe 0.7 to 1.0), never the in-sample 1.46 as if it were earned. A daily
job re-runs this to append the live marks. A back-compat top-level block (= ALPHAC) keeps the
current dashboard rendering until it migrates to the algorithms[] array.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import sqlite3
from pathlib import Path

import pyarrow.parquet as pq

from alphaforge.portfolio.book import SleeveCurve, combine_book

EQUITY_FWD_DIR = "artifacts/walkforward/equity_live_fwd"
_TOP_N = 15  # holdings shown per side (the book is ~100/side; show the largest weights)

GO_LIVE = "2026-06-21"  # the day the live paper track record begins

# The two validated, walk-forward, net-of-cost sleeves (the artifact dirs under
# artifacts/walkforward/) + their per-sleeve LIVE trading DB (None = derived, not a loop).
EQUITY_WF = "k30_dn_63"
CRYPTO_WF = "crypto_carry_wk"
CRYPTO_LIVE_DB = Path("var/trading_crypto_perp.sqlite")
EQUITY_LIVE_DB = Path("var/trading_equity.sqlite")  # populated by the daily equity forward job
# AlphaMax forward curve (realized, post-go-live) if the daily forward engine has written one.
EQUITY_FWD_CURVE = Path("artifacts/walkforward/equity_live_fwd/equity.parquet")


def _epoch_to_date(x: float) -> str:
    v = int(x)
    base = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
    d = base + (dt.timedelta(milliseconds=v) if v > 10**11 else dt.timedelta(days=v))
    return d.strftime("%Y-%m-%d")


def load_wf(name: str) -> SleeveCurve:
    """A validated walk-forward (simulation) curve."""
    t = pq.read_table(f"artifacts/walkforward/{name}/equity.parquet").to_pydict()
    return SleeveCurve(name, list(t["ts"]), list(t["equity"]))


def sample_curve(days, eq, *, target: int = 180, scale: float = 100000.0) -> list[dict]:
    """Downsample any curve (hourly crypto, daily equity, daily book) to ~`target`
    points so the JSON payload stays light and every curve renders consistently."""
    n = len(days)
    if n == 0:
        return []
    every = max(1, n // target)
    out = []
    for i in range(0, n, every):
        out.append({"date": _epoch_to_date(days[i]), "equity": round(float(eq[i]) * scale, 2)})
    if (n - 1) % every != 0:  # always include the last point
        out.append({"date": _epoch_to_date(days[-1]), "equity": round(float(eq[-1]) * scale, 2)})
    return out


def read_live_db(db: Path) -> list[dict]:
    """Realized live paper marks from a per-sleeve trading DB (equity_curve), or the honest
    go-live $100k seed until the loop has written its first cycle. No fabricated history."""
    seed = [{"date": GO_LIVE, "equity": 100000.0}]
    if not db.exists():
        return seed
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = con.execute(
            "SELECT ts, equity_quote FROM equity_curve WHERE ts IS NOT NULL ORDER BY ts ASC"
        ).fetchall()
        con.close()
    except sqlite3.Error:
        return seed
    if not rows:
        return seed
    return [{"date": _epoch_to_date(ts), "equity": round(float(eq), 2)} for ts, eq in rows]


def read_fwd_curve(path: Path) -> list[dict] | None:
    """AlphaMax's realized forward curve (post-go-live) if the daily forward engine wrote one."""
    if not path.exists():
        return None
    try:
        t = pq.read_table(path).to_pydict()
        days, eq = t["ts"], t["equity"]
        pts = [
            (_epoch_to_date(d), float(e))
            for d, e in zip(days, eq, strict=True)
            if _epoch_to_date(d) >= GO_LIVE  # forward = on/after go-live only
        ]
        if not pts:
            return None
        base = pts[0][1] or 1.0  # rebase the realized forward to the $100k go-live seed
        return [{"date": dte, "equity": round(100000.0 * v / base, 2)} for dte, v in pts]
    except Exception:
        return None


def _ticker(iid: str) -> str:
    """XUSE:CASH:MUUSD -> MU ; BINANCE:PERP:BTCUSDT -> BTC."""
    tail = iid.split(":")[-1]
    return tail.removesuffix("USDT").removesuffix("USD") if ":" in iid else iid


def read_equity_holdings() -> dict | None:
    """AlphaMax's current long/short book: the latest position snapshot from the equity
    forward walk-forward (the real names the strategy holds), top-weighted per side.
    Honest: these are the validated momentum strategy's positions on realized data."""
    legs = sorted(glob.glob(f"{EQUITY_FWD_DIR}/legs/leg_*/positions.parquet"))
    if not legs:
        return None
    try:
        t = pq.read_table(legs[-1]).to_pydict()
        rows = list(zip(t["ts"], t["instrument_id"], t["qty"], t["weight"], strict=True))
        if not rows:
            return None
        last_ts = max(r[0] for r in rows)
        hold = [(_ticker(iid), float(q), float(w)) for ts, iid, q, w in rows
                if ts == last_ts and abs(float(q)) > 1e-9]
        longs = sorted([h for h in hold if h[1] > 0], key=lambda x: -abs(x[2]))
        shorts = sorted([h for h in hold if h[1] < 0], key=lambda x: -abs(x[2]))
        gross = sum(abs(w) for _, _, w in hold)
        net = sum(w for _, _, w in hold)
        return {
            "as_of": _epoch_to_date(last_ts),
            "long_count": len(longs),
            "short_count": len(shorts),
            "gross_pct": round(gross * 100, 1),
            "net_pct": round(net * 100, 2),
            "long": [{"ticker": tk, "weight_pct": round(abs(w) * 100, 2)}
                     for tk, _, w in longs[:_TOP_N]],
            "short": [{"ticker": tk, "weight_pct": round(abs(w) * 100, 2)}
                      for tk, _, w in shorts[:_TOP_N]],
        }
    except Exception:
        return None


def read_crypto_holdings() -> dict | None:
    """AlphaForge's current crypto perp positions from the live trading DB, or flat (it has
    been deciding HOLD; an honest empty book, never invented)."""
    if not CRYPTO_LIVE_DB.exists():
        return {"as_of": None, "long_count": 0, "short_count": 0,
                "long": [], "short": [], "flat": True}
    try:
        con = sqlite3.connect(f"file:{CRYPTO_LIVE_DB}?mode=ro", uri=True)
        last = con.execute("SELECT max(cycle_ts) FROM positions_snapshots").fetchone()[0]
        rows = (con.execute(
            "SELECT instrument_id, qty FROM positions_snapshots WHERE cycle_ts=? AND qty != 0",
            (last,)).fetchall() if last is not None else [])
        con.close()
    except sqlite3.Error:
        return None
    longs = sorted([(_ticker(i), q) for i, q in rows if q > 0])
    shorts = sorted([(_ticker(i), q) for i, q in rows if q < 0])
    return {
        "as_of": _epoch_to_date(last) if last else None,
        "long_count": len(longs), "short_count": len(shorts),
        "long": [{"ticker": tk} for tk, _ in longs[:_TOP_N]],
        "short": [{"ticker": tk} for tk, _ in shorts[:_TOP_N]],
        "flat": not rows,
    }


def combined_live(crypto: list[dict], equity: list[dict]) -> list[dict]:
    """ALPHAC live = equal-risk combine of the two LIVE sleeve curves, IF both have accrued
    real marks; else the honest seed (the cross-asset record begins when both sleeves do)."""
    if len(crypto) < 2 or len(equity) < 2:
        return [{"date": GO_LIVE, "equity": 100000.0}]
    try:
        def to_sleeve(name, c):
            base = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
            ts_ms = [int((dt.datetime.strptime(p["date"], "%Y-%m-%d").replace(tzinfo=dt.UTC)
                          - base).total_seconds() * 1000) for p in c]
            eq = [p["equity"] / 100000.0 for p in c]
            return SleeveCurve(name, ts_ms, eq)
        book = combine_book([to_sleeve("crypto", crypto), to_sleeve("equity", equity)],
                            scheme="equal_risk", trading_days=365)
        return sample_curve(book.days, book.equity_curve)
    except Exception:
        return [{"date": GO_LIVE, "equity": 100000.0}]


# Per-algorithm honest descriptors + metrics (canonical numbers; in-sample always struck).
ALGOS = [
    {
        "key": "alphaforge", "name": "AlphaForge", "rank": 1,
        "asset": "Crypto funding carry",
        "desc": "Funding-rate carry on Binance USDT-M perpetuals, market-neutral.",
        "standalone_sharpe": 0.68,
        "live_kind": "Live broker-loop paper, hourly.",
        "wf": CRYPTO_WF, "live_db": CRYPTO_LIVE_DB,
    },
    {
        "key": "alphamax", "name": "AlphaMax", "rank": 2,
        "asset": "US-equity 12-1 momentum",
        "desc": "12-1 cross-sectional momentum, dollar-neutral long/short, "
                "split-adjusted, survivorship-free.",
        "standalone_sharpe": 0.91,
        "live_kind": "Daily forward paper, realized next-open fills.",
        "wf": EQUITY_WF, "live_db": EQUITY_LIVE_DB,
    },
    {
        "key": "alphac", "name": "ALPHAC", "rank": 3, "flagship": True,
        "asset": "Cross-asset book",
        "desc": "AlphaForge and AlphaMax combined equal-risk. The two sleeves are "
                "near-uncorrelated (~ -0.02); that decorrelation is the edge.",
        "standalone_sharpe": None,
        "live_kind": "Derived: the equal-risk combination of the two live sleeves.",
        "wf": None, "live_db": None,
    },
]


def main():
    crypto_wf = load_wf(CRYPTO_WF)
    equity_wf = load_wf(EQUITY_WF)
    book = combine_book([equity_wf, crypto_wf], scheme="equal_risk", trading_days=365)

    # research (simulation) curves, downsampled. Sleeve WF curves are already dollar-based
    # (100k-start), so scale=1.0; the combined book curve is normalised (~1.0), so scale=100k.
    research = {
        "alphaforge": sample_curve(crypto_wf.ts_ms, crypto_wf.equity, scale=1.0),
        "alphamax": sample_curve(equity_wf.ts_ms, equity_wf.equity, scale=1.0),
        "alphac": sample_curve(book.days, book.equity_curve, scale=100000.0),
    }
    # live (realized) curves - honest, no fabricated history
    crypto_live = read_live_db(CRYPTO_LIVE_DB)
    equity_live = read_fwd_curve(EQUITY_FWD_CURVE) or read_live_db(EQUITY_LIVE_DB)
    live = {
        "alphaforge": crypto_live,
        "alphamax": equity_live,
        "alphac": combined_live(crypto_live, equity_live),
    }
    # current holdings (the real names each algorithm is buying/holding)
    eq_hold = read_equity_holdings()
    cr_hold = read_crypto_holdings()
    holdings = {"alphaforge": cr_hold, "alphamax": eq_hold, "alphac": eq_hold}

    algorithms = []
    for a in ALGOS:
        sleeve_weight = (
            round(float(book.weights[a["wf"]].mean()), 3) if a["wf"] in book.weights else None
        )
        algorithms.append({
            "key": a["key"], "name": a["name"], "rank": a["rank"],
            "flagship": a.get("flagship", False),
            "asset": a["asset"], "desc": a["desc"],
            "standalone_sharpe": a["standalone_sharpe"],
            "book_weight": sleeve_weight,
            "live_kind": a["live_kind"],
            "live_days": max(len(live[a["key"]]) - 1, 0),
            "research_curve": research[a["key"]],
            "live_curve": live[a["key"]],
            "holdings": holdings[a["key"]],
        })

    metrics = {
        "in_sample_sharpe": round(float(book.sharpe), 2),
        "honest_forward_sharpe": "0.7 to 1.0",
        "in_sample_cagr_pct": round(float(book.cagr) * 100, 1),
        "honest_forward_return_pct": "7 to 16 (vol-targeted)",
        "max_drawdown_pct": round(float(book.maxdd) * 100, 1),
        "realistic_worst_dd_pct": "-10 to -15",
        "correlation": "the two sleeves are near-uncorrelated "
        "(equity momentum vs crypto carry ~ -0.02)",
        "gauntlet_grade": "C+",
        "gauntlet_pass": ("real but modest; fails multiple-testing deflation in-sample, "
                          "so deployment waits on the live track record"),
        "live_days": max(len(crypto_live) - 1, 0),
    }
    transparency = [
        "Research curves are simulations, not realised trading. No real capital has been deployed.",
        "The live paper track record begins " + GO_LIVE
        + " and is shown as it accrues. We publish no return until it is earned in the open.",
        "The book is two decorrelated sleeves: US equity momentum (standalone Sharpe ~0.9) "
        "and crypto funding carry (~0.7). The honest combined forward expectation after "
        "multiple-testing "
        "deflation is 0.7 to 1.0, not the higher in-sample figure (1.46).",
        "The edge is genuine (market-neutral, decorrelated, statistically real) but modest and "
        "not yet proven live.",
    ]

    state = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "go_live_date": GO_LIVE,
        "algorithms": algorithms,
        "metrics": metrics,
        "transparency": transparency,
        # the real names the algorithms are buying/holding right now (top-weighted per side)
        "holdings": {"alphamax": eq_hold, "alphaforge": cr_hold},
        # ---- back-compat top-level (= ALPHAC, the flagship book) so the current dashboard
        # keeps rendering until it migrates to algorithms[] ----
        "book": {
            "name": "ALPHAC Cross-Asset Book",
            "style": "Market-neutral, two decorrelated sleeves "
            "(US equity momentum + crypto funding carry)",
            "sleeves": [
                {"key": "alphaforge", "name": "AlphaForge", "desc": ALGOS[0]["desc"],
                 "standalone_sharpe": 0.68,
                 "weight": round(float(book.weights[CRYPTO_WF].mean()), 3)},
                {"key": "alphamax", "name": "AlphaMax", "desc": ALGOS[1]["desc"],
                 "standalone_sharpe": 0.91,
                 "weight": round(float(book.weights[EQUITY_WF].mean()), 3)},
            ],
        },
        "research_curve": research["alphac"],
        "live_curve": live["alphac"],
    }
    out = Path("data/paper/state.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(state, indent=2))
    print(f"wrote {out}  (3 algorithms; in-sample SR {book.sharpe:.2f}; "
          f"crypto live pts {len(crypto_live)}, equity live pts {len(equity_live)})")
    for app in (Path.home() / "meridian-app" / "public", Path.home() / "meridian" / "public"):
        if app.is_dir():
            (app / "paper-state.json").write_text(json.dumps(state, indent=2))
            print(f"copied to {app / 'paper-state.json'}")


if __name__ == "__main__":
    main()
