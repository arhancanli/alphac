"""Generate the paper-trading state JSON the Meridian web app + landing render.

FOUR algorithms, presented FLAGSHIP-FIRST (this list order IS the published order: the
algorithms[] array is emitted in it and the public pages render it top to bottom):
  1. ALPHAC     - THE FLAGSHIP and the product: the cross-asset book = the three sleeves below at
                  fixed 40/40/20 weights + a DISCLOSED +20% strategic net-long overlay. It is what
                  the published forward Sharpe actually describes, so it leads.
  2. AlphaMax   - US-equity 12-1 momentum (LIVE broker-executed on its own Alpaca account as of
                  2026-06-27, trading the ~170/176 Alpaca-tradable subset; live record is days old).
  3. AlphaTrend - managed-futures trend on a 17-market ETF basket (LIVE broker-executed on Alpaca
                  paper as of 2026-06-27 — the first sleeve taken genuinely live; DSR 0.83, but the
                  live record is only days old so 0.33/0.83 stays a backtest figure for now).
  4. AlphaForge - crypto funding carry (LIVE hourly broker-loop paper). It USED to lead this list,
                  purely as an artifact of build order — which oversold the smallest-capacity sleeve
                  we own (~$10M measured cliff, glassbox/capacity.json) and buried the book the
                  record is about. Ordering is presentation only; no number, weight or metric moved.

Radical-transparency rules baked in: every RESEARCH curve is labelled simulation; every LIVE
curve starts at go-live (no fabricated history); metrics are the honest forward numbers (grade
C+, deflated forward Sharpe 0.3 to 0.9), never an in-sample headline (currently 1.85 tilted /
1.46 neutral core) as if it were earned. A daily job re-runs this to append the live marks. A
back-compat top-level block (= ALPHAC) keeps the current dashboard rendering until it migrates
to the algorithms[] array.
"""
# ruff: noqa: E501  (this file is intentionally full of long, exact honest-disclosure prose strings)
from __future__ import annotations

import datetime as dt
import glob
import json
import sqlite3
from pathlib import Path

import pyarrow.parquet as pq

from alphaforge.portfolio.book import SleeveCurve, combine_book
from alphaforge.portfolio.market_factor import market_factor_by_date, market_factor_by_epochday

EQUITY_FWD_DIR = "artifacts/walkforward/equity_live_fwd"
_TOP_N = 15  # holdings shown per side (the book is ~100/side; show the largest weights)

# ---- v2 re-baseline (2026-06-29) -------------------------------------------------------------
# On 2026-06-29 the flagship gained a DISCLOSED +20% strategic net-long overlay (STRATEGIC_TILT_PCT)
# and all four tracks were restarted clean. v1 (2026-06-21..06-29) ran market-neutral and FLAT
# ($100k -> $100k, $0 realized) and is SUPERSEDED, NOT deleted: it stays in the signed transparency
# chain (seq 0..4, Bitcoin-anchored). We re-baseline in the open; we never silently rewrite "live since".
V1_GO_LIVE = "2026-06-21"
V1_ENDED = "2026-06-29"
GO_LIVE = "2026-06-29"  # the day the live paper track record begins (v2: tilted + restarted)

# The flagship ALPHAC carries a DISCLOSED strategic net-long BETA overlay on top of the two
# market-neutral alpha sleeves. It is commoditized beta (you could buy 0.5 BTC + 0.5 SPY yourself),
# it DILUTES risk-adjusted return and ADDS crash tail-risk — it is NOT alpha. It is held as a
# SEPARATE labelled line, never laundered into the neutral sleeves (which stay measurably neutral).
# Purpose: let the book participate in a chunk of bull-market upside for near-term/family capital;
# the pure-neutral configuration remains the institutional franchise.
STRATEGIC_TILT_PCT = 0.20
TILT_MIX = {"BTC": 0.5, "SPY": 0.5}

# The REALIZED record can never contain a future date. The walk-forward / forward engines are run
# with --end=TOMORROW so the test leg reaches today, but the data vendor (or the engine's bar
# labelling) can emit a bar dated for the NEXT session, which is in the future and has NOT happened.
# Publishing or anchoring such a mark fabricates a return the record has not earned (and seals a
# value into the signed transparency chain that the real day will later contradict). Every live
# curve is clamped to <= today (UTC) before it is published. Research/simulation curves are exempt
# (they are explicitly labelled simulations and may legitimately extend a forward-filled bar).
TODAY = dt.datetime.now(dt.UTC).date().isoformat()


def clamp_live(curve: list[dict] | None) -> list[dict]:
    """Drop any mark dated after today (UTC) from a REALIZED live curve — no future returns."""
    return [p for p in (curve or []) if p["date"] <= TODAY]

# The two validated, walk-forward, net-of-cost sleeves (the artifact dirs under
# artifacts/walkforward/) + their per-sleeve LIVE trading DB (None = derived, not a loop).
EQUITY_WF = "k30_dn_63"
CRYPTO_WF = "crypto_carry_wk"
CRYPTO_LIVE_DB = Path("var/trading_crypto_perp.sqlite")
EQUITY_LIVE_DB = Path("var/trading_equity.sqlite")  # AlphaMax REALIZED broker equity (live_cycle.py --profile equity)
# AlphaMax went GENUINELY broker-executed on its own Alpaca paper account (2026-06-27). Its record
# is RE-BASELINED to the v2 restart date (2026-06-29) — the pre-restart days were flat at baseline.
EQ_GO_LIVE = "2026-06-29"
# AlphaMax forward curve (realized, post-go-live) if the daily forward engine has written one.
EQUITY_FWD_CURVE = Path("artifacts/walkforward/equity_live_fwd/equity.parquet")

# Managed-futures trend (built 2026-06-27). As of the v2 restart (2026-06-29) it is FOLDED INTO the
# flagship ALPHAC book at a deliberate modest 20% sleeve weight (see BOOK_WEIGHTS): it is the ONLY
# sleeve to clear deflation (DSR 0.83) and is ~0-correlated to the other two, so a small allocation
# keeps the book Sharpe flat AND lowers drawdown (crisis-robust trend). Equal-risk would over-weight
# it (low vol -> 60% of the book, which tanks the Sharpe), so the book uses FIXED weights.
MF_WF = "managed_futures"
MF_GO_LIVE = "2026-06-29"  # re-baselined to the v2 restart date (was live 2026-06-27, flat pre-restart)
MF_FWD_CURVE = Path("artifacts/walkforward/mf_live_fwd/equity.parquet")
# AlphaTrend is GENUINELY broker-executed as of go-live: live_cycle.py submits its 17-ETF book to
# Alpaca paper daily and records the realized marked-to-market account equity here. This realized
# curve — NOT the simulation — is what the public record shows from go-live forward.
MF_LIVE_DB = Path("var/trading_managed_futures.sqlite")

# The flagship ALPHAC is now a THREE-sleeve book at deliberate FIXED weights: the two proven sleeves
# keep ~equal weight, the new deflation-cleared trend sleeve enters as a modest 20% satellite. Fixed
# (not equal-risk) because equal-risk over-weights AlphaTrend's low vol and dilutes the book.
BOOK_WEIGHTS = {EQUITY_WF: 0.40, CRYPTO_WF: 0.40, MF_WF: 0.20}


def _epoch_to_date(x: float) -> str:
    v = int(x)
    base = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
    d = base + (dt.timedelta(milliseconds=v) if v > 10**11 else dt.timedelta(days=v))
    return d.strftime("%Y-%m-%d")


def live_days_elapsed(curve: list[dict], go_live: str = GO_LIVE) -> int:
    """Calendar DAYS this sleeve has been live = the curve's latest date minus THIS sleeve's own
    go-live (NOT point count: the crypto loop writes many hourly marks per day, so len-1 would
    badly overcount; per-sleeve go_live so a newer sleeve like AlphaTrend counts from its own
    start, never inflated to the book's earlier go-live)."""
    if not curve:
        return 0
    gl = dt.date.fromisoformat(go_live)
    last = dt.date.fromisoformat(curve[-1]["date"])
    return max((last - gl).days, 0)


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


def read_live_db(db: Path, go_live: str = GO_LIVE) -> list[dict]:
    """Realized live paper marks from a per-sleeve trading DB (equity_curve), or the honest
    go-live $100k seed until the loop has written its first cycle. No fabricated history.
    ``go_live`` lets a newer sleeve (e.g. AlphaTrend) seed from its OWN start, never backdated."""
    seed = [{"date": go_live, "equity": 100000.0}]
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
    # Floor at go-live: a broker account that existed (idle, flat) before this sleeve went live must
    # not contribute pre-go-live marks to the sleeve's record. Crypto's marks are all >= GO_LIVE, so
    # this is a no-op there; for AlphaTrend it drops the days the account sat at $100k before launch.
    pts = [(d, float(eq)) for ts, eq in rows if (d := _epoch_to_date(ts)) >= go_live]
    if not pts:
        return seed
    # Normalize to a common $100k display base at go-live so sleeves on different-sized accounts
    # (AlphaTrend $100k, AlphaMax $1M) are directly comparable: it is the % path that matters, not the
    # raw balance. Already-$100k sleeves (crypto, AlphaTrend) are unchanged (base ~= 100k).
    base = pts[0][1] or 100000.0
    return [{"date": d, "equity": round(100000.0 * eq / base, 2)} for d, eq in pts]


def read_fwd_curve(path: Path, go_live: str = GO_LIVE) -> list[dict] | None:
    """A sleeve's realized forward curve (post-go-live) if its daily forward engine wrote one.
    ``go_live`` lets a newer sleeve (e.g. managed-futures) use its OWN start, never backdated."""
    if not path.exists():
        return None
    try:
        t = pq.read_table(path).to_pydict()
        days, eq = t["ts"], t["equity"]
        pts = [
            (_epoch_to_date(d), float(e))
            for d, e in zip(days, eq, strict=True)
            if _epoch_to_date(d) >= go_live  # forward = on/after go-live only
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


def read_equity_holdings(fwd_dir: str = EQUITY_FWD_DIR) -> dict | None:
    """A walk-forward sleeve's current long/short book: the latest position snapshot from its
    forward legs (the real names the strategy holds), top-weighted per side. Honest: these are
    the validated strategy's positions on realized data. Reused for AlphaMax (equities) and
    AlphaTrend (the managed-futures ETF basket) — same leg/positions.parquet layout."""
    legs = sorted(glob.glob(f"{fwd_dir}/legs/leg_*/positions.parquet"))
    if not legs:
        return None
    try:
        t = pq.read_table(legs[-1]).to_pydict()
        rows = list(zip(t["ts"], t["instrument_id"], t["qty"], t["weight"], strict=True))
        if not rows:
            return None
        # "What the book holds right now" must never be a future-dated TARGET book: with
        # next-open fills, a Friday-close decision is stamped at Monday's open, so over the
        # weekend the latest snapshot sits ahead of the clock. Clamp to snapshots at or
        # before now; only if none exist (fresh-leg edge case) fall back to what's there.
        now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
        past = [r for r in rows if r[0] <= now_ms]
        rows = past if past else rows
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


def _daily_returns(curve: list[dict]) -> dict[str, float]:
    """Map date -> that sleeve's realized daily return. Dedup to the last mark per
    calendar day (the crypto loop writes many hourly marks), then diff. A sleeve's
    first mark has return 0 (it is the baseline, not a gain)."""
    byday: dict[str, float] = {}
    for p in curve:
        byday[p["date"]] = float(p["equity"])  # last write per day wins
    days = sorted(byday)
    rets: dict[str, float] = {}
    prev: str | None = None
    for d in days:
        rets[d] = (byday[d] / byday[prev] - 1.0) if (prev and byday[prev]) else 0.0
        prev = d
    return rets


def combined_live(
    sleeves: list[tuple[list[dict], float]],
    market: dict[str, float] | None = None, tilt: float = 0.0,
) -> list[dict]:
    """ALPHAC live = the REALIZED live sleeve curves combined at their committed (research)
    weights, PLUS a disclosed ``tilt`` net-long market overlay (``market`` = date -> the
    0.5 BTC + 0.5 SPY factor return), compounded daily from the $100k seed. ``sleeves`` is
    [(live_curve, weight), ...] (weights normalized). Honest: real per-sleeve returns,
    pre-committed dollar weights, the overlay is a SEPARATE labelled beta line (commoditized,
    dilutes Sharpe, adds crash tail), no fabricated history. A sleeve with no mark on a day
    contributes nothing that day, so the flagship accrues from go-live even when the sleeves
    came online on different days."""
    rets = [(_daily_returns(c), float(w or 0.0)) for c, w in sleeves]
    if all(len(c) < 2 for c, _ in sleeves):
        return [{"date": GO_LIVE, "equity": 100000.0}]
    s = sum(w for _, w in rets) or 1.0
    rets = [(r, w / s) for r, w in rets]
    mkt = market or {}
    dates = sorted({GO_LIVE}.union(*[set(r) for r, _ in rets]))
    out: list[dict] = []
    val = 100000.0
    for i, d in enumerate(dates):
        if i:
            step = sum(w * r.get(d, 0.0) for r, w in rets) + tilt * mkt.get(d, 0.0)
            val *= 1.0 + step
        out.append({"date": d, "equity": round(val, 2)})
    return out


# Per-algorithm honest descriptors + metrics (canonical numbers; in-sample always struck).
#
# ORDER = PRESENTATION ORDER, and it is deliberate. The flagship ALPHAC is FIRST: it is the
# product, it is the book the published forward Sharpe describes, and every metric block on the
# public pages is its. The three sleeves that COMPOSE it follow, largest-capacity first. Until
# 2026-08-01 this list led with AlphaForge purely because it was built first — a build-order
# artifact that put our smallest-capacity sleeve (~$10M measured capacity cliff), knocked out by
# venue unreachability in two multi-day outages between 2026-07-18 and 2026-07-29 (var/
# trading_crypto_perp.sqlite cycles), at the top of the page and the flagship at the bottom.
# Re-ordering is
# PRESENTATION ONLY: no number, weight, cadence or metric changed with it. ``rank`` is renumbered
# to match so anything that sorts by rank and anything that renders the array agree.
ALGOS = [
    {
        "key": "alphac", "name": "ALPHAC", "rank": 1, "flagship": True,
        "asset": "Cross-asset book (3 decorrelated sleeves + disclosed strategic long)",
        "desc": "AlphaForge + AlphaMax + AlphaTrend combined at fixed 40/40/20 weights — three "
                "near-uncorrelated sleeves (carry / equity momentum / managed-futures trend); that "
                "decorrelation is the edge, and AlphaTrend (the only deflation-cleared sleeve, DSR "
                "0.83, ~0 equity corr) holds the Sharpe flat while LOWERING drawdown. PLUS a "
                "DISCLOSED +20% strategic net-long overlay (0.5 BTC + 0.5 SPY) held as a SEPARATE "
                "labelled line — commoditized beta that adds bull-market participation but DILUTES "
                "risk-adjusted return and adds crash tail-risk; never blended into the neutral sleeves.",
        "standalone_sharpe": None,
        "live_kind": "Derived: fixed 40/40/20 combination of the 3 live sleeves + the disclosed +20% beta overlay.",
        "wf": None, "live_db": None,
    },
    {
        "key": "alphamax", "name": "AlphaMax", "rank": 2,
        "asset": "US-equity 12-1 momentum",
        "desc": "12-1 cross-sectional momentum, dollar-neutral long/short, "
                "split-adjusted, survivorship-free.",
        "standalone_sharpe": 0.91,
        "live_kind": "LIVE broker-executed — its long/short book (the ~170 of 176 Alpaca-tradable "
                     "names) is submitted to a dedicated Alpaca paper account daily, fills at the US open.",
        "caveat": "Genuinely broker-executed as of " + EQ_GO_LIVE + " on its own Alpaca account, but the "
                  "live record is only days old. 0.91 is the TOP of a 0.07-1.17 construction band; the "
                  "deep-history forward is ~0.08 with DSR 0.34 (does NOT clear the deflation gate). The "
                  "honest central estimate is ~0.5-0.6, not 0.91 — the live book will settle it. A few "
                  "unshortable / non-fractionable small-caps are skipped, so the live book is a close "
                  "tradable proxy of the research strategy, not an exact replica.",
        "wf": EQUITY_WF, "live_db": EQUITY_LIVE_DB,
    },
    {
        "key": "managed_futures", "name": "AlphaTrend", "rank": 3,
        "asset": "Managed-futures trend",
        "desc": "Time-series momentum across a 17-market basket (equity-index, rates, "
                "commodities, FX via liquid ETFs), long/short on each market's own trend, "
                "inverse-vol weighted. The first new sleeve to clear deflation: net Sharpe "
                "0.33 but DSR 0.83 (statistically real after multiple-testing), positive "
                "skew, two-decade stable, near-uncorrelated to equities (corr ~+0.08).",
        "standalone_sharpe": 0.33,
        "live_kind": "LIVE broker-executed — its 17-ETF book is submitted to Alpaca paper daily "
                     "(fills at the US open). Genuine fills, not a simulation.",
        "caveat": "The soundest sleeve by design (DSR 0.83, survives 2008/2020/2022, ~0 equity "
                  "corr) and genuinely broker-executed on Alpaca paper. As of the v2 restart "
                  "(" + MF_GO_LIVE + ") it is FOLDED INTO the flagship ALPHAC book at a modest 20% "
                  "weight — a small allocation keeps the book Sharpe flat and lowers drawdown. But "
                  "the live record is only days old: the 0.33 / DSR 0.83 is the 2003-2026 BACKTEST, "
                  "not yet confirmed by the live book.",
        "wf": MF_WF, "live_db": str(MF_LIVE_DB),
    },
    {
        "key": "alphaforge", "name": "AlphaForge", "rank": 4,
        "asset": "Crypto funding carry",
        "desc": "Funding-rate carry on Binance USDT-M perpetuals, market-neutral.",
        "standalone_sharpe": 0.68,
        "live_kind": "Live broker-loop (hourly, paper). Trading since 2026-07-05, when a "
                     "signal-wiring bug was found and fixed (see the dated correction).",
        "caveat": "0.68 is the FULL-HISTORY figure and hides the tail: -1.63 Sharpe / -19.6% "
                  "drawdown in 2022 (FTX). Carry compresses with size/crowding. CORRECTION "
                  "(2026-07-05): from go-live to 07-05 this sleeve was flat and we published "
                  "'funding carry compressed, holding cash' — that explanation was WRONG. The "
                  "real cause was a signal-wiring bug: the live blend included equity-fundamental "
                  "alphas that are undefined on crypto, which invalidated every signal; the "
                  "validated carry-only configuration was not what was deployed. Found in an "
                  "internal audit and fixed the same day — the loop now runs the exact blessed "
                  "walk-forward configuration (carry_fund_21, weekly rebalance). No money was "
                  "misreported (the sleeve genuinely held cash at $100k); the published "
                  "explanation was wrong, and we correct it here rather than rewrite it.",
        "wf": CRYPTO_WF, "live_db": CRYPTO_LIVE_DB,
    },
]

# Key -> descriptor. The back-compat ``book.sleeves`` block below is addressed BY KEY, never by
# list position: presentation order must be free to change without silently re-labelling a sleeve.
ALGO_BY_KEY = {a["key"]: a for a in ALGOS}


def transparency_entries() -> list[str]:
    """The public, append-only disclosure list emitted as state["transparency"].

    Module level (not a local of main()) on purpose: this list IS the published record, so a
    regression test must be able to assert against the exact object main() emits, not a copy.
    Append-only in spirit — corrections are ADDED, never swapped in over an old claim.
    """
    return [
        "Research curves are simulations. No real capital has been deployed.",
        "2026-06-29 RE-BASELINE (v1 -> v2): on this date the flagship ALPHAC (a) folded AlphaTrend "
        "(managed-futures trend) into the book as a 3rd decorrelated sleeve at a modest 20% weight "
        "(fixed 40/40/20), and (b) gained a DISCLOSED +20% strategic net-long overlay (0.5 BTC + 0.5 "
        "SPY); all four tracks were restarted clean. v1 (2026-06-21..06-29) ran market-neutral and "
        "FLAT ($100k -> $100k, $0 realized — "
        "crypto held cash, equity/MF were days-old at baseline) and is SUPERSEDED, not deleted: it "
        "stays in the signed transparency chain (seq 0..4, Bitcoin-anchored). We re-baseline in the "
        "open and never silently rewrite 'live since'. The change is sealed into the chain itself.",
        "About the +20% tilt — said plainly: it is COMMODITIZED BETA (you could buy 0.5 BTC + 0.5 "
        "SPY yourself for ~free), so it DILUTES risk-adjusted return (~-0.2 Sharpe vs the neutral "
        "core) and ADDS crash tail-risk (a crypto-50%/equity-20% crash costs the overlay ~-7% on "
        "top of the neutral book). It is NOT alpha and is held as a SEPARATE labelled line — the two "
        "sleeves (AlphaForge, AlphaMax) remain genuinely market-neutral. It exists to add bull-market "
        "participation for near-term capital; the pure-neutral core stays the institutional franchise.",
        "What is actually live: TWO sleeves are now genuinely broker-executed on their own Alpaca "
        "paper accounts. AlphaTrend (managed-futures) submits its 17-ETF book daily; AlphaMax (equity "
        "momentum) submits its ~170-of-176 tradable long/short book daily; both fill at the US open. "
        "Crypto carry runs a real hourly broker loop but has been FLAT since go-live (the funding edge "
        "is compressed — it is honestly holding cash). Every live record here is only days old, so the "
        "headline Sharpes (0.33/0.83 for AlphaTrend, 0.91 for AlphaMax) stay BACKTEST figures until the "
        "live books confirm them. We will not call a simulation a realized record, nor a days-old live "
        "record a track record.",
        "Honest worst-case risk: the live-overlap curve starts 2023-07 and contains no 2022 bear "
        "or 2020 crash, so its -4.7% drawdown is a coverage artifact, NOT a risk estimate. The "
        "crisis-inclusive worst drawdown is -15% to -18%, and sleeve correlations rise to +0.6 to "
        "+0.9 in risk-off. We publish the worse number as the headline.",
        "Honest forward expectation is 0.3 to 0.9, NOT 0.7 to 1.0 — with a real chance of ~0 in "
        "year one. Crypto carry's standalone 0.68 hides a -19.6% 2022 drawdown; equity momentum's "
        "0.91 is the top of a 0.07-1.17 band whose deep-history forward is ~0.08 (DSR 0.17 at the "
        "current N=102 trial ledger — it was 0.34 when first published at N=27; deflation tightens "
        "as experiments accumulate, and it fails the 0.95 gate either way). The honest central "
        "estimates are lower than the headline figures.",
        "DISCLOSURE 2026-07-11 — the equity sleeve's deflated confidence has decayed with our own "
        "research, and we say so: DSR 0.34 was computed at N=27 logged trials; the ledger now "
        "stands at N=102 and the same equity curve deflates to DSR 0.17. Nothing about the sleeve "
        "changed — running more experiments mechanically lowers every number's deflated confidence, "
        "including our own live record's. Also from the same campaign: six documented momentum "
        "improvements (Barroso-Santa-Clara / Daniel-Moskowitz vol-scaling x3, residual momentum, "
        "12-7 intermediate, sector-neutral) were built and tested against the live AlphaMax "
        "construction — ALL null or worse. Vol-scaling is redundant with the book-level vol target "
        "already running (incremental alpha t between -1.64 and +0.81 across 5 configs); residual "
        "momentum screens weaker than plain 12-1 (t 2.11 vs 2.49 monthly); 12-7 and sector-neutral "
        "screen weaker than what we run (t 0.92 / 1.28 vs 1.73). The frozen 12-1 construction "
        "stays. One pre-registered follow-up (52-week-high, screen t 2.01) is in its deep-history "
        "walk-forward now; its result will be published either way.",
        "GATE AUDIT 2026-07-12 — we audited our own deploy gate for whether it flatters us. The "
        "deflated-Sharpe formula already corrects for fat tails and skew, but it assumed returns "
        "are serially independent; trend and momentum are not. We added the standard "
        "serial-correlation correction (Lo-2002 HAC) and re-graded every sleeve. Result: nothing "
        "crosses the 0.95 gate, and if anything the old formula was slightly too HARSH on the "
        "trend/momentum sleeves — AlphaTrend's deflated Sharpe nudges UP (~0.80 to ~0.83) because "
        "its daily returns are mildly mean-reverting, so its average is known a little better than "
        "the naive formula assumed. We are not being flattered by an assumption; the safe direction "
        "to be wrong is the one we were wrong in. No change to the live gate was warranted, so none "
        "was made. (This audit becomes load-bearing only for a future slow/smoothed signal graded "
        "near the gate, where the correction would pull a Sharpe DOWN; we will run it before "
        "deploying any such candidate.)",
        "DISCLOSURE 2026-08-01 — the evidence base we publish for the equity sleeve is stale in "
        "two separate ways, and both are ours to say. FIRST, the figures on the record (net Sharpe "
        "0.907, DSR 0.341) describe the frozen k30_dn_63 walk-forward artifact. Re-run on today's "
        "data lake, that same construction measures net Sharpe 0.818, and deflated against the "
        "trial ledger as it now stands (N=111; those figures were computed at N=27) its DSR is "
        "about 0.15. Nothing about the construction changed — the lake grew, the ledger grew, and "
        "the number came down. SECOND, and the part that matters more: that construction is NOT "
        "what the live sleeve trades. The live tick runs the equity profile's default construction "
        "— a different rebalance cadence, K per side, universe and leg grid (seven parameters "
        "differ) — which is the recipe drift we disclosed on 2026-07-19 and have not closed. So our "
        "published evidence blesses one thing and our account trades another. We then ran the "
        "head-to-head we owed: both constructions re-measured from scratch on ONE matched window "
        "(the same 2022-07..2026-06 span, the same 12-leg grid, the same committed cost model). "
        "The evidenced construction scores 0.818 and the live one 0.982, and a paired bootstrap on "
        "the daily returns puts P(the evidenced construction is the better one) at about 0.37-0.39 "
        "across seeds, with a 95% interval on the Sharpe difference of roughly -1.3 to +0.9. That "
        "interval straddles zero by a mile: on the evidence we have the two are statistically "
        "INDISTINGUISHABLE. The honest statement is therefore that the drift was never shown to be "
        "a downgrade — and it was never shown to be an upgrade either. We are NOT claiming the "
        "live construction is better, and one matched window does not settle it. Separately, from "
        "the same audit: the in-sample Sharpe this state emits for the flagship now reads 1.85 — "
        "that is the book carrying the disclosed +20% net-long overlay through a bull window — "
        "while the market-neutral core, emitted alongside it, reads 1.46. At the time of writing "
        "the public pages still carry 1.46 as their struck in-sample headline, so the figure moved "
        "1.46 -> 1.85 and the pages have not caught up. Both are in-sample and neither is earned; "
        "the honest forward band is unchanged at 0.3 to 0.9. We publish the drift, the lower "
        "re-measurement and the null head-to-head together, because reporting only the ones that "
        "flatter us is how an evidence base rots.",
        "PRESENTATION 2026-08-01 — we changed the order the four algorithms are listed in, and we "
        "note it so a verifier diffing the signed chain sees a documented reason rather than an "
        "unexplained reshuffle. The flagship ALPHAC now leads; the three sleeves that compose it "
        "follow (AlphaMax, AlphaTrend, AlphaForge). Previously AlphaForge led, purely because it "
        "was built first — which put our smallest-capacity sleeve (~$10M measured capacity cliff, "
        "and the one knocked out by venue unreachability in two multi-day outages between "
        "2026-07-18 and 2026-07-29 — see the open incident below) at the top of the page and the "
        "book our published forward record actually describes at the bottom. No number, weight, cadence "
        "or metric changed with the reorder; the book's composition weights (40/40/20) and every "
        "curve are byte-identical to before it.",
        "OPEN INCIDENT 2026-07-20 — the crypto sleeve is HALTED on venue unreachability, and we "
        "are saying so while it is still unresolved rather than after. Since 2026-07-18 13:00 UTC "
        "the hourly carry loop has completed ZERO cycles: Binance is unreachable from our network. "
        "This is venue-specific, not a general outage and not a DNS fault — DNS resolves normally, "
        "the general internet and our other venues are fine (Bybit responds, the equity broker "
        "responds), and the failure persists when we bypass DNS entirely and connect by IP with "
        "SNI, which points to network-level filtering or an edge geo-restriction rather than a "
        "transient blip. Consequences, stated plainly: the sleeve's positions are FROZEN as of the "
        "last successful cycle and are not being managed, and its published curve stops at "
        "2026-07-18 — we do NOT roll forward a mark we did not observe, so the book you see is "
        "stale by design, not live. We are determining whether this is transient or a persistent "
        "regional restriction. If it proves persistent it is a STRUCTURAL problem for a sleeve "
        "built on a single venue, and we will say that too — venue access is exactly the kind of "
        "risk that quietly kills a strategy, and it belongs on the record while it is inconvenient, "
        "not once it is tidy.",
        "CORRECTION 2026-07-19 — a reverse split was mismarked and it cost us real money and a "
        "week of half-size trading; here is everything. During the equity sleeve's July drawdown "
        "(itself genuine: a momentum junk-rally squeeze, every construction of the factor lost on "
        "the same days, and the signal verified alive — longs 97th momentum percentile, shorts "
        "6th), an audit found the nightly simulation had marked a 1-for-20 reverse split (ALIT) at "
        "raw prices: it fabricated a -4.95% simulation day that never happened, leaked about "
        "-1.45% of real loss into the live account via an oversized short, and falsely tripped the "
        "-10% drawdown brake — so the live book traded at roughly HALF its intended size for over "
        "a week on a phantom loss. The corrected curve's true worst day is -2.49% and its maximum "
        "drawdown -7.1%; the brake should never have fired and releases on the corrected numbers "
        "at the next session. Two more defects found and fixed in the same audit: crypto "
        "perpetuals had leaked into the equity book's record through Jun 11 (~+$323 of crypto PnL "
        "inside the published equity record — the same unscoped-universe class as the 2026-07-05 "
        "crypto bug, now guarded at two layers), and the live recipe had drifted from the exact "
        "configuration our published evidence blesses (disclosed here; the strategy itself is "
        "unchanged). Fixes: split-aware marking with a sanity guard against bogus records, "
        "universe scoped to equities, an asset-class guard in the order path, and regression "
        "tests pinning the RUNNING path — because this is the third time a data defect dressed up "
        "as performance, and the lesson is permanent: it is never the strategy, always the "
        "plumbing, and a fix is not done until a test pins the path that runs.",
        "CORRECTION 2026-07-05 — the crypto sleeve was signal-dead, not 'carry compressed'. From "
        "go-live (06-23) to 07-05 AlphaForge held cash and we published that funding carry was "
        "compressed. An internal audit found the true cause: a wiring bug blended equity-fundamental "
        "alphas (undefined on crypto) into the live signal, invalidating it every cycle — the "
        "validated carry-only configuration was never what ran live. Fixed same day (the loop now "
        "runs the exact blessed walk-forward config: carry_fund_21, weekly rebalance, with per-cycle "
        "signal-health logging so a dead signal can never masquerade as a quiet hold again). The "
        "$100k cash equity curve was genuine; the published EXPLANATION was wrong. Per our "
        "append-only posture this correction is added to the record, not swapped into it.",
        "We red-team our own record. On 2026-06-27 our publishing pipeline emitted a future-dated "
        "(2026-06-29) paper mark that briefly reached the public sites and was anchored into seq 0 "
        "of the signed transparency chain. We caught it the same day, added a fail-closed guard, "
        "and appended the corrected seq 1 — the append-only chain shows BOTH, because we don't get "
        "to delete our mistakes. That is the trust system working, not failing.",
        "AlphaTrend (managed-futures trend) was added " + MF_GO_LIVE + " as the fourth algorithm and "
        "is the FIRST sleeve we took genuinely live: its 17-ETF book transacts on Alpaca paper, not "
        "in a simulator. Net Sharpe is a modest 0.33, but it is the first new sleeve to CLEAR "
        "multiple-testing deflation (DSR 0.83) — statistically real, not a backtest fluke — with "
        "positive skew and near-zero equity correlation. As of the v2 restart (" + MF_GO_LIVE + ") it "
        "is FOLDED INTO the flagship ALPHAC book at a modest 20% weight (fixed 40/40/20) — its "
        "decorrelation holds the book Sharpe flat while lowering drawdown. The screen suggested 0.73; "
        "the honest engine says 0.33, which is what real managed-futures delivers. We published both.",
    ]


def main():
    crypto_wf = load_wf(CRYPTO_WF)
    equity_wf = load_wf(EQUITY_WF)
    mf_wf = load_wf(MF_WF)  # AlphaTrend (managed-futures) — now the 3rd sleeve in the flagship book
    # the disclosed +20% net-long overlay's market factor (0.5 BTC + 0.5 SPY), epoch-day keyed for
    # the research book and date-string keyed for the live curve — ONE definition, never divergent.
    mkt_epochday = market_factor_by_epochday()
    mkt_by_date = market_factor_by_date()
    # THREE-sleeve flagship at FIXED weights (40/40/20) — AlphaForge + AlphaMax + AlphaTrend — plus
    # the disclosed +20% strategic-long overlay. Fixed (not equal-risk) so AlphaTrend's low vol does
    # not over-weight it (which would tank the Sharpe to ~1.04); at 20% it holds Sharpe and cuts DD.
    sleeves = [equity_wf, crypto_wf, mf_wf]
    book = combine_book(sleeves, scheme="fixed", fixed_weights=BOOK_WEIGHTS, trading_days=365,
                        strategic_tilt_pct=STRATEGIC_TILT_PCT, strategic_tilt_market=mkt_epochday)
    # the NEUTRAL core (pre-overlay) for honest side-by-side disclosure of what the tilt costs/adds
    book_neutral = combine_book(sleeves, scheme="fixed", fixed_weights=BOOK_WEIGHTS, trading_days=365)

    # research (simulation) curves, downsampled. Sleeve WF curves are already dollar-based
    # (100k-start), so scale=1.0; the combined book curve is normalised (~1.0), so scale=100k.
    research = {
        "alphaforge": sample_curve(crypto_wf.ts_ms, crypto_wf.equity, scale=1.0),
        "alphamax": sample_curve(equity_wf.ts_ms, equity_wf.equity, scale=1.0),
        "managed_futures": sample_curve(mf_wf.ts_ms, mf_wf.equity, scale=1.0),
        "alphac": sample_curve(book.days, book.equity_curve, scale=100000.0),
    }
    # live (realized) curves - honest, no fabricated history
    crypto_live = read_live_db(CRYPTO_LIVE_DB)
    equity_live = read_live_db(EQUITY_LIVE_DB, go_live=EQ_GO_LIVE)  # realized broker fills, $100k-rebased
    # AlphaTrend: the REALIZED Alpaca-paper account equity (genuine broker fills), seeded from its
    # own go-live. live_cycle.py writes a mark each daily run; the curve accrues real marks as the
    # ETF book fills and marks to market. No simulation, no backdating.
    mf_live = read_live_db(MF_LIVE_DB, go_live=MF_GO_LIVE)
    # committed fixed dollar weights from the research book (NOT re-estimated live)
    w_cr = float(book.weights[CRYPTO_WF].mean()) if CRYPTO_WF in book.weights else 0.4
    w_eq = float(book.weights[EQUITY_WF].mean()) if EQUITY_WF in book.weights else 0.4
    w_mf = float(book.weights[MF_WF].mean()) if MF_WF in book.weights else 0.2
    # Clamp every REALIZED sleeve curve to <= today BEFORE combining, so a future-dated vendor/
    # engine bar can neither be published nor leak into the combined book or the transparency chain.
    crypto_live = clamp_live(crypto_live)
    equity_live = clamp_live(equity_live)
    mf_live = clamp_live(mf_live) or [{"date": MF_GO_LIVE, "equity": 100000.0}]
    live = {
        "alphaforge": crypto_live,
        "alphamax": equity_live,
        "managed_futures": mf_live,
        "alphac": clamp_live(combined_live(
            [(crypto_live, w_cr), (equity_live, w_eq), (mf_live, w_mf)],
            mkt_by_date, STRATEGIC_TILT_PCT,
        )),
    }
    # current holdings (the real names each algorithm is buying/holding)
    eq_hold = read_equity_holdings()
    cr_hold = read_crypto_holdings()
    # AlphaTrend's current ETF book: prefer the daily-regenerated live forward (the book
    # live_cycle actually submits to Alpaca — same preference order as live_cycle._WF),
    # falling back to the blessed research artifact only if the tick has never run.
    mf_hold = (read_equity_holdings("artifacts/walkforward/mf_live_fwd")
               or read_equity_holdings(f"artifacts/walkforward/{MF_WF}"))
    holdings = {
        "alphaforge": cr_hold, "alphamax": eq_hold,
        "managed_futures": mf_hold, "alphac": eq_hold,
    }

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
            "sharpe_caveat": a.get("caveat"),
            "book_weight": sleeve_weight,
            "live_kind": a["live_kind"],
            "go_live": (algo_go_live := MF_GO_LIVE if a["key"] == "managed_futures"
                        else EQ_GO_LIVE if a["key"] == "alphamax" else GO_LIVE),
            "live_days": live_days_elapsed(live[a["key"]], algo_go_live),
            "research_curve": research[a["key"]],
            "live_curve": live[a["key"]],
            "holdings": holdings[a["key"]],
        })

    metrics = {
        "in_sample_sharpe": round(float(book.sharpe), 2),
        # ALPHAC now carries a disclosed +20% net-long overlay. The in-window Sharpe is the TILTED
        # book's, and it is INFLATED by a favourable bull window — the overlay is commoditized beta,
        # which DILUTES honest-forward Sharpe (~-0.2 vs the neutral core) rather than improving it.
        "neutral_core_in_sample_sharpe": round(float(book_neutral.sharpe), 2),
        # Widened + lowered after the 2026-06-27 red-team AND the 2026-06-29 tilt: the neutral 0.7-1.0
        # is optimistic for the LIVE book (crypto carry flat, equity deep-history forward ~0.08/DSR
        # 0.34); the +20% beta does not lift forward Sharpe and adds crash tail. Honest band is wider.
        "honest_forward_sharpe": "0.3 to 0.9 (the +20% beta does NOT improve this — it adds bull "
                                 "upside + crash risk, not risk-adjusted quality; real chance of ~0 yr1)",
        "in_sample_cagr_pct": round(float(book.cagr) * 100, 1),
        "honest_forward_return_pct": "0 to 14 (vol-targeted; lower bound is real)",
        # The measured book curve starts 2023-07 and contains NO 2020-Covid / 2022 bear, so this
        # computed number is a LIVE-OVERLAP artifact, not a risk estimate. The honest crisis-
        # inclusive worst-case lives in realistic_worst_dd_pct (the headline the UI shows).
        "max_drawdown_pct": round(float(book.maxdd) * 100, 1),
        "max_drawdown_note": "live-overlap window only (2023-07+); EXCLUDES 2022 & Covid — NOT a risk estimate",
        # neutral core -15 to -18, PLUS the +20% overlay's ~-7% hit in a crypto-50%/equity-20% crash.
        "realistic_worst_dd_pct": "-22 to -28 (incl. the +20% strategic-long overlay's crash tail)",
        "correlation": "Calm: ~-0.02. BUT in risk-off the sleeve correlations SPIKE to +0.6 to +0.9 "
        "(equity-momentum~trend, trend~carry), and crypto carry is itself short-crisis-vol — the "
        "diversification benefit shrinks exactly in the left tail. We size on the stressed matrix.",
        "gauntlet_grade": "C+",
        "gauntlet_pass": ("real but modest; fails multiple-testing deflation in-sample, so "
                          "deployment waits on a live record where both sleeves actually transact "
                          "through a risk-off episode"),
        "live_days": live_days_elapsed(crypto_live),
    }

    state = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "go_live_date": GO_LIVE,
        "rebaseline": {
            "v1": {"go_live": V1_GO_LIVE, "ended": V1_ENDED,
                   "result": "flat, $0 realized ($100k -> $100k); crypto carry held cash, "
                             "equity/MF days-old at baseline",
                   "config": "market-neutral, net beta ~0, no strategic tilt"},
            "v2": {"go_live": GO_LIVE,
                   "config": "3-sleeve market-neutral core (AlphaForge + AlphaMax + AlphaTrend, "
                             "fixed 40/40/20) + DISCLOSED +20% strategic net-long overlay "
                             "(0.5 BTC + 0.5 SPY), held as a separate labelled line"},
            "disclosure": "v1 (2026-06-21..06-29) ran flat at the $100k baseline and is SUPERSEDED, "
                          "NOT deleted: it remains in the signed transparency chain (seq 0..4, "
                          "Bitcoin-anchored). v2 restarts the forward record on 2026-06-29 under a "
                          "disclosed net-long tilt. We re-baseline in the open; we never silently "
                          "rewrite 'live since'.",
        },
        "algorithms": algorithms,
        "metrics": metrics,
        "transparency": transparency_entries(),
        # the real names the algorithms are buying/holding right now (top-weighted per side)
        "holdings": {"alphamax": eq_hold, "alphaforge": cr_hold},
        # ---- back-compat top-level (= ALPHAC, the flagship book) so the current dashboard
        # keeps rendering until it migrates to algorithms[] ----
        "book": {
            "name": "ALPHAC Cross-Asset Book",
            "style": "Market-neutral core (equity momentum + crypto funding carry + managed-futures "
            "trend, three decorrelated sleeves at fixed 40/40/20) PLUS a disclosed +20% strategic "
            "net-long overlay",
            "strategic_tilt": {
                "pct": STRATEGIC_TILT_PCT,
                "mix": TILT_MIX,
                "kind": "disclosed net-long market beta (commoditized), separate labelled line, "
                        "NOT blended into the neutral sleeves",
                "honest_note": "beta dilutes risk-adjusted return and adds crash tail-risk; it buys "
                               "bull-market participation, not quality. The pure-neutral core is the "
                               "institutional franchise; the tilt is for near-term/family capital.",
            },
            # COMPOSITION order (what the book is made of), not presentation rank — left exactly
            # as it was so the signed transparency chain's book_sleeves payload does not churn.
            "sleeves": [
                {"key": "alphaforge", "name": "AlphaForge", "desc": ALGO_BY_KEY["alphaforge"]["desc"],
                 "standalone_sharpe": 0.68,
                 "weight": round(float(book.weights[CRYPTO_WF].mean()), 3)},
                {"key": "alphamax", "name": "AlphaMax", "desc": ALGO_BY_KEY["alphamax"]["desc"],
                 "standalone_sharpe": 0.91,
                 "weight": round(float(book.weights[EQUITY_WF].mean()), 3)},
                {"key": "managed_futures", "name": "AlphaTrend", "desc": ALGO_BY_KEY["managed_futures"]["desc"],
                 "standalone_sharpe": 0.33,
                 "weight": round(float(book.weights[MF_WF].mean()), 3)},
            ],
        },
        "research_curve": research["alphac"],
        "live_curve": live["alphac"],
    }
    out = Path("data/paper/state.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(state, indent=2))
    print(f"wrote {out}  ({len(algorithms)} algorithms; in-sample SR {book.sharpe:.2f}; "
          f"crypto live pts {len(crypto_live)}, equity live pts {len(equity_live)})")
    for app in (Path.home() / "meridian-app" / "public", Path.home() / "meridian" / "public"):
        if app.is_dir():
            (app / "paper-state.json").write_text(json.dumps(state, indent=2))
            print(f"copied to {app / 'paper-state.json'}")


if __name__ == "__main__":
    main()
