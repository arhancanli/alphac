"""Generate the paper-trading state JSON the Meridian web app + landing render.

FOUR algorithms, presented FLAGSHIP-FIRST (this list order IS the published order: the
algorithms[] array is emitted in it and the public pages render it top to bottom):
  1. ALPHAC     - THE FLAGSHIP and the product: the cross-asset book = the three sleeves below at
                  equal weights + a DISCLOSED strategic net-long overlay (see STRATEGIC_TILT_PCT). It is what
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
import math
import sqlite3
from pathlib import Path

import pyarrow.parquet as pq

from alphaforge.portfolio.book import SleeveCurve, combine_book
from alphaforge.portfolio.market_factor import market_factor_by_date, market_factor_by_epochday
from alphaforge.validation.publish_gate import check_published_state

EQUITY_FWD_DIR = "artifacts/walkforward/equity_live_fwd"
_TOP_N = 15  # holdings shown per side (the book is ~100/side; show the largest weights)

# ---- v2 re-baseline (2026-06-29) -------------------------------------------------------------
# On 2026-06-29 the flagship gained a DISCLOSED +20% strategic net-long overlay (STRATEGIC_TILT_PCT)
# and all four tracks were restarted clean. v1 (2026-06-21..06-29) ran market-neutral and FLAT
# ($100k -> $100k, $0 realized) and is SUPERSEDED, NOT deleted: it stays in the signed transparency
# chain (seq 0..4, Bitcoin-anchored). We re-baseline in the open; we never silently rewrite "live since".
V1_GO_LIVE = "2026-06-21"
V1_ENDED = "2026-06-29"
V2_GO_LIVE = "2026-06-29"
V2_ENDED = "2026-08-07"

# v3 RE-BASELINE, 2026-08-07 — every sleeve moved to its own fresh $1,000,000 Alpaca paper account.
#
# WHY. The sleeves ran on mismatched seeds (AlphaMax $932k, AlphaTrend $100k), which broke two
# things at once. The published 40/40/20 book weights described a dollar split that was really
# ~9:1, and $100k is simply too small for a wide dollar-neutral book: whole-share truncation on
# shorts (Alpaca forbids fractional shorts, longs fill fractionally) cost AlphaMax 8.79% of its
# short notional and pushed it +2.40% NET LONG — eroding the neutrality the sleeve is built on.
# At $1M that falls to 0.37%/+0.10%, while market impact stays at 0.08% of median ADV, two orders
# of magnitude below where it starts to matter.
#
# WHAT WAS PRESERVED. Nothing was destroyed. The v2 accounts (AlphaMax PA397834GG9R, AlphaTrend
# PA3IQC5B7BC2) still EXIST at the broker with their positions and full portfolio history, and the
# whole record — both brokers' own history, every fill, the local DBs and the published state — is
# frozen read-only under artifacts/archive/ with a manifest digest.
#
# WHY THE DATE MATTERS MECHANICALLY. read_live_db floors at go_live, so moving these dates is what
# stops v2's last mark and v3's first mark being read as one day's return: AlphaMax would have
# printed +7.26% and AlphaTrend +894.01% out of nothing. Re-baselining in the open is the same
# thing we did at v1->v2; silently splicing the curves is what we refuse to do.
V3_GO_LIVE = "2026-08-07"
GO_LIVE = V3_GO_LIVE  # the day the CURRENT live paper track record begins

# The flagship ALPHAC carries a DISCLOSED strategic net-long BETA overlay on top of the two
# market-neutral alpha sleeves. It is commoditized beta (you could buy 0.5 BTC + 0.5 SPY yourself),
# it DILUTES risk-adjusted return and ADDS crash tail-risk — it is NOT alpha. It is held as a
# SEPARATE labelled line, never laundered into the neutral sleeves (which stay measurably neutral).
# Purpose: let the book participate in a chunk of bull-market upside for near-term/family capital;
# the pure-neutral configuration remains the institutional franchise.
#
# ---- 2026-08-12: CUT FROM 20% TO 10%, on measurement rather than taste ----------------------
# The overlay was never claimed to be alpha, but until now nobody had measured what it actually
# does to the book. Measured on the 4-sleeve research book (1,061-day common window) and then
# stressed by replaying the market factor's worst equal-length stretch under an UNCHANGED neutral
# core, so only the overlay varies:
#
#     tilt     measured window     crash stress     worst day (measured)
#     0%       SR 1.396            SR 1.396         -0.90%
#     5%       SR 1.667            SR 1.308         -0.89%
#     10%      SR 1.784            SR 1.192         -1.26%   <- chosen
#     12.5%    SR 1.799  (peak)    SR 1.128         -1.45%
#     20%      SR 1.760            SR 0.929         -2.02%   <- previous
#     30%      SR 1.651            SR 0.686         -2.79%
#
# THE SHAPE IS WHAT DECIDES IT, not any single cell. Measured-window Sharpe is FLAT from 5% to
# 15% (1.667 -> 1.799, a 0.13 spread) while the crash-stress Sharpe falls MONOTONICALLY with size
# (1.308 -> 1.062) and the worst day grows steadily. When one axis is flat and the other is
# monotone, you take the lower number: you buy the same upside for strictly less tail. Going
# 20% -> 10% therefore costs essentially nothing in the measured window (1.760 -> 1.784, actually
# a touch HIGHER) while recovering +0.26 of stress Sharpe and cutting the worst day from -2.02%
# to -1.26%.
#
# *** WE DELIBERATELY DO NOT PICK THE PEAK. *** 12.5% maximises the measured window, and choosing
# it would be selecting the argmax of a curve fitted to ONE window — the exact selection trap this
# book's deflation discipline exists to prevent, and the same error that makes a hand-picked
# lookback look like an edge. 10% is a round number below the peak chosen on the trade-off, not
# on the maximum. A prior version of this comment claimed 10% halved the upside (SR 1.578); that
# number was a linear interpolation, never measured, and it was wrong — the upside is essentially
# unchanged. It is corrected here rather than quietly deleted.
#
# WHY NOT ZERO. Equity beta has positive long-run drift and this capital is explicitly stated to
# want participation; removing it entirely would trade real expected return for a cleaner-looking
# ratio. 10% keeps the participation and removes the domination.
#
# TWO HONEST CAVEATS ON THE STRESS. (1) The market factor is 0.5 BTC + 0.5 SPY and a missing leg
# contributes 0, but BTC data begins 2020-01-01 — so the crash-era stress ran at effectively HALF
# weight (SPY only). A real crash where both legs fall together costs MORE than -0.47 shows.
# (2) The measured window rose +121.6% with a worst drawdown of -28.2%, against -54.4% available
# in the factor's own history: the upside is measured in a bull market, the downside is not.
# Both caveats push the same way, which is why the cut is a cut and not a raise.
STRATEGIC_TILT_PCT = 0.10
TILT_MIX = {"BTC": 0.5, "SPY": 0.5}
#: The tilt as PUBLISHED PROSE — derived, never typed. Eight published strings once said
#: "40/40/20" after the weights moved, and the ALPHAC blurb said "3 sleeves" while listing four.
#: Hand-typed prose about a constant is a second source of truth; this closes the class for the
#: tilt the same way WEIGHTS_PROSE closed it for the sleeve weights.
TILT_PROSE = f"+{STRATEGIC_TILT_PCT:.0%}"

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
EQ_GO_LIVE = V3_GO_LIVE  # v3: fresh $1M account PA3ECIF9O942 (was PA397834GG9R)
# AlphaMax forward curve (realized, post-go-live) if the daily forward engine has written one.
EQUITY_FWD_CURVE = Path("artifacts/walkforward/equity_live_fwd/equity.parquet")

# Managed-futures trend (built 2026-06-27). As of the v2 restart (2026-06-29) it is FOLDED INTO the
# flagship ALPHAC book at a deliberate modest 20% sleeve weight (see BOOK_WEIGHTS): it is the ONLY
# sleeve to clear deflation (DSR 0.83) and is ~0-correlated to the other two, so a small allocation
# keeps the book Sharpe flat AND lowers drawdown (crisis-robust trend). Equal-risk would over-weight
# it (low vol -> 60% of the book, which tanks the Sharpe), so the book uses FIXED weights.
MF_WF = "managed_futures"
MF_GO_LIVE = V3_GO_LIVE  # v3: fresh $1M account PA31FJRJQK69 (was PA3IQC5B7BC2)
MF_FWD_CURVE = Path("artifacts/walkforward/mf_live_fwd/equity.parquet")
# AlphaTrend is GENUINELY broker-executed as of go-live: live_cycle.py submits its 17-ETF book to
# Alpaca paper daily and records the realized marked-to-market account equity here. This realized
# curve — NOT the simulation — is what the public record shows from go-live forward.
MF_LIVE_DB = Path("var/trading_managed_futures.sqlite")

# ---- AlphaVintage: the PIT CPI-surprise size spread, live 2026-08-10 -------------------------
# The fourth sleeve. It trades the IWM/SPY size spread off the standardized AR(3) surprise in
# point-in-time CPI (headline PCPI + core PCPIX), and it is the only sleeve whose input is a
# revision-aware macro release rather than price, funding or a balance sheet — which is the whole
# source of its diversification. Measured on the 693-day 4-way overlap, adding it cut the book's
# average pairwise correlation from +0.0723 to +0.0274 and lifted the theoretical ceiling
# (s_bar / sqrt(rho_bar)) from 1.97 to 2.99.
#
# ITS OWN GO-LIVE, deliberately later than the book's. The v3 record opens 2026-08-07; this sleeve
# first held a position on 2026-08-10. It is entered in WEIGHT_SCHEDULE at its own date so the
# three days before it existed compound at THIRDS and only the days after compound at QUARTERS.
# Backdating it to V3_GO_LIVE would have been one line and would have restated three already
# published days — the exact defect WEIGHT_SCHEDULE was built to prevent.
#
# LEVERAGE, disclosed: live runs at HALF the probe's notional (gross 1.0x rather than the spec's
# 2.0x), because 2.0x exceeds live_cycle's _GROSS_HARD_CAP of 1.5x — which engages the GLOBAL kill
# switch rather than skipping the sleeve — and equals this account's Reg T overnight limit exactly.
# Sharpe is scale-invariant so the validated 0.3403 still applies; dollar return, vol and drawdown
# are all halved. See scripts/alphavintage_target.py for the full rationale.
VINTAGE_WF = "alphavintage_live"
VINTAGE_GO_LIVE = "2026-08-10"
VINTAGE_LIVE_DB = Path("var/trading_alphavintage.sqlite")

# The flagship ALPHAC is now a THREE-sleeve book at deliberate FIXED weights: the two proven sleeves
# keep ~equal weight, the new deflation-cleared trend sleeve enters as a modest 20% satellite. Fixed
# (not equal-risk) because equal-risk over-weights AlphaTrend's low vol and dilutes the book.
# v3 (2026-08-07): equal thirds, matching WEIGHT_SCHEDULE and the equal $1M accounts. See the note
# on WEIGHT_SCHEDULE for why equal beats both the old 40/40/20 and a measured equal-RISK scheme.
BOOK_WEIGHTS = {EQUITY_WF: 1 / 4, CRYPTO_WF: 1 / 4, MF_WF: 1 / 4, VINTAGE_WF: 1 / 4}


def _weights_prose() -> str:
    """How the book's weights are DESCRIBED, derived from BOOK_WEIGHTS so it cannot disagree.

    On 2026-08-07 BOOK_WEIGHTS moved from 40/40/20 to equal thirds and EIGHT published strings
    kept saying "fixed 40/40/20". The shipped artifact then contradicted itself inside one file:
    every sleeve carried weight 0.333 while the prose beside it named 40/40/20. Hand-typed prose
    about a constant is a second source of truth, and a second source of truth is a defect waiting
    for someone to change the first one. Derive it, and the class of bug closes.
    """
    vals = list(BOOK_WEIGHTS.values())
    if len({round(v, 6) for v in vals}) == 1:
        return {2: "halves", 3: "equal thirds", 4: "equal quarters"}.get(len(vals), "equal weights")
    return "/".join(str(round(v * 100)) for v in vals)


WEIGHTS_PROSE = _weights_prose()

#: How many sleeves compose the flagship, and the word for it — DERIVED, never typed.
#: The same lesson as _weights_prose: on 2026-08-10 AlphaVintage became the fourth sleeve and the
#: published `asset` string still read "3 near-uncorrelated sleeves" while the page beside it
#: listed four. Hand-typed prose about a constant is a second source of truth, and a second source
#: of truth is a defect waiting for someone to change the first one.
N_SLEEVES = len(BOOK_WEIGHTS)
N_SLEEVES_WORD = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}.get(N_SLEEVES, str(N_SLEEVES))

#: Average pairwise correlation of the LIVE sleeves, re-measured 2026-08-11 on the 693-day window
#: where all four overlap (2023-07-07..2026-06-01), each sleeve annualised on its own calendar.
#: Dropping AlphaVintage from the same computation reproduces the previously published 3-sleeve
#: figures EXACTLY (rho_bar +0.0723, s_bar +0.5288), which is what makes this number checkable
#: rather than asserted. Adding it cut rho_bar from +0.0723 to +0.0274 and lifted the theoretical
#: ceiling s_bar/sqrt(rho_bar) from 1.97 to 2.99 — the sleeve's entire contribution is
#: diversification, NOT return: its own net Sharpe is 0.3403 and does not clear our 0.95 gate.
RHO_BAR = 0.0274
RHO_BAR_PRIOR_3_SLEEVE = 0.0723


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


def load_probe_curve(name: str, path: str) -> SleeveCurve:
    """A validated PROBE curve, for a sleeve whose evidence is not a walk-forward run.

    AlphaVintage is the one such sleeve: it was validated by scripts/probe_cpi_surprise_size.py
    against a single pre-registered configuration (no sweep, no cell-picking), so its evidence
    lives at artifacts/probe/cpi_surprise_size/equity.parquet rather than under
    artifacts/walkforward/. Its live TARGET BOOK is written separately by
    scripts/alphavintage_target.py, which is why an `alphavintage_live` directory exists with legs
    but no equity.parquet — that artifact is a position file, not a track record, and reading it
    here would publish a curve that does not exist.

    The probe stores a NORMALISED equity path (starts at 1.0). Sleeve curves are published on a
    $100k basis, so it is rescaled here rather than at the call site — doing it at the call site is
    how one sleeve ends up on a different basis from the others without anyone noticing.
    """
    t = pq.read_table(path).to_pydict()
    tcol = next(c for c in ("ts", "date", "timestamp") if c in t)
    ecol = next(c for c in ("equity", "nav", "value") if c in t)
    eq = [float(x) for x in t[ecol]]
    base = eq[0] if eq and eq[0] else 1.0
    return SleeveCurve(name, list(t[tcol]), [100000.0 * v / base for v in eq])


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


#: Account-switch drops recorded during this run, surfaced at the end of main() rather than
#: buried mid-log. A curve silently losing days is exactly the kind of thing that should be
#: loud: it means a broker account changed and the published record just moved.
_LOG_ACCOUNT_SWITCH: list[str] = []


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

    # ---- ONE MARK PER DAY -------------------------------------------------------------------
    # equity_curve holds several marks per day (the daily live_cycle writes one, the hourly state
    # refresh writes another). Emitting them all put TWO points on the same date, and the daily
    # return between them is not a return at all. Keep the LAST mark of each day — the close.
    by_day: dict[str, float] = {}
    for d, eq in pts:
        by_day[d] = eq
    pts = sorted(by_day.items())

    # ---- ACCOUNT-SWITCH GUARD ---------------------------------------------------------------
    # *** THE +893% PHANTOM, caught 2026-08-11 on the LIVE PUBLIC RECORD. ***
    # On 2026-08-07 the v3 cutover put marks from TWO DIFFERENT BROKER ACCOUNTS into one curve:
    #     AlphaTrend  08-06 00:00  $1,000,000.00   (v3 account PA31FJRJQK69)
    #     AlphaTrend  08-07 05:32  $  100,681.45   (v2 account, $100k, written before the env
    #                                               files were switched)
    #     AlphaTrend  08-08 00:00  $1,000,000.00   (v3 again)
    # Rebasing on the first mark turned the v2 mark into 10,068 and the NEXT day's return into
    # +893%. Combined at one third, that published an ALPHAC curve of 100,000 -> 400,207 in a
    # single day: a 300% gain that never happened, served publicly at canlicapital.com.
    #
    # A day-over-day move beyond +/-50% is not a return for a market-neutral sleeve running gross
    # <= 1.0x — it is a different account. The threshold is deliberately far above anything these
    # sleeves can do (their daily sd is 0.7% to 1.3%, so 50% is ~40 standard deviations) and far
    # below an account swap, so it cannot fire on a real move. When it fires we keep the LATEST
    # segment: the sleeve's live record is the account it trades TODAY. The superseded account is
    # not deleted — it stays in artifacts/archive/ with its own published manifest — but it must
    # not be spliced into the current curve as though the two were one continuous track record.
    seg_start = 0
    for i in range(1, len(pts)):
        prev, cur = pts[i - 1][1], pts[i][1]
        if prev > 0 and cur > 0 and abs(math.log(cur / prev)) > math.log(1.5):
            seg_start = i
    if seg_start:
        dropped = pts[:seg_start]
        _LOG_ACCOUNT_SWITCH.append(
            f"{db.name}: dropped {len(dropped)} pre-switch mark(s) "
            f"({dropped[0][0]}..{dropped[-1][0]}, ${dropped[-1][1]:,.0f}) — superseded account"
        )
        pts = pts[seg_start:]

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
        now_ms = int(dt.datetime.now(dt.UTC).timestamp() * 1000)
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


#: THE COMMITTED WEIGHT SCHEDULE — APPEND-ONLY. (effective_date, {sleeve_key: weight}).
#:
#: WHY THIS EXISTS. `combined_live` rebuilds ALPHAC's entire live NAV from GO_LIVE on every publish.
#: It used to do that at whatever the sleeve weights are TODAY, which means the published live
#: record was not a record of what happened — it was a reconstruction of what would have happened
#: if today's weights had always applied. While the book sat at a frozen 40/40/20 that was
#: invisible. The moment a sleeve is added or a weight moves, EVERY previously published live day
#: silently changes value. For a fund whose product is a record a stranger can verify, that is the
#: wrong failure to ship, and it would have shipped with the six-sleeve deployment.
#:
#: THE RULE: each day compounds at the weights that were committed ON THAT DAY. To change weights,
#: APPEND a new (date, weights) entry. Never edit an existing one — an edit rewrites history, which
#: is precisely the defect this replaced. Entries must be in ascending date order; the loader
#: asserts it, because an out-of-order entry would silently apply the wrong weights to a past day.
WEIGHT_SCHEDULE: list[tuple[str, dict[str, float]]] = [
    # v3 opens at EQUAL THIRDS, because that is what the money actually does: each sleeve holds its
    # own $1,000,000 account, so equal weights are now a real dollar allocation rather than a
    # reporting convention. Under v2 the published 40/40/20 sat on seeds of $932k / $932k / $100k,
    # a dollar split of roughly 9:1 against the trend sleeve — the weights and the money disagreed.
    #
    # Equal weight is also the only scheme we can defend on evidence. Every sleeve's deflated
    # Sharpe sits between 0.000 and 0.210 against a 0.95 gate, so there is no statistical basis for
    # saying any of them deserves more capital than another; a fitted weight would be a claim the
    # measurements do not support. Equal-RISK was measured and rejected: it hands 32% to AlphaTrend
    # for having low volatility while it returned -0.23 on the window.
    (V3_GO_LIVE, {"crypto": 1 / 3, "equity": 1 / 3, "mf": 1 / 3}),
    # 2026-08-10 — AlphaVintage goes live and the book moves to EQUAL QUARTERS. APPENDED, not
    # edited: the three days from 2026-08-07 to 2026-08-09 keep compounding at thirds because that
    # is what the money actually did on those days. A stranger re-deriving the published curve from
    # the per-sleeve records must get the same number we did, and that is only true if a day's
    # weights are frozen once the day has passed.
    #
    # Equal quarters for the same reason v3 opened at equal thirds: each sleeve holds its own
    # $1,000,000 account, so equal weight is a real dollar allocation rather than a reporting
    # convention. And it remains the only scheme the evidence supports — every sleeve's deflated
    # Sharpe still sits far below the 0.95 gate, so any fitted weight would be a claim the
    # measurements cannot carry. AlphaVintage's own net Sharpe is 0.3403 (NW t 1.82) and it does
    # NOT clear that gate either; it earns its quarter by being uncorrelated, not by being better.
    (VINTAGE_GO_LIVE, {"crypto": 1 / 4, "equity": 1 / 4, "mf": 1 / 4, "vintage": 1 / 4}),
]


def _weights_on(date: str, schedule: list[tuple[str, dict[str, float]]]) -> dict[str, float]:
    """The committed weights in effect on ``date`` (the latest entry at or before it)."""
    active = schedule[0][1]
    for eff, w in schedule:
        if eff <= date:
            active = w
        else:
            break
    total = sum(abs(v) for v in active.values()) or 1.0
    return {k: v / total for k, v in active.items()}


def combined_live(
    sleeves: dict[str, list[dict]],
    market: dict[str, float] | None = None, tilt: float = 0.0,
    schedule: list[tuple[str, dict[str, float]]] | None = None,
) -> list[dict]:
    """ALPHAC live = the REALIZED live sleeve curves combined at the weights COMMITTED ON EACH DAY,
    PLUS a disclosed ``tilt`` net-long market overlay (``market`` = date -> the 0.5 BTC + 0.5 SPY
    factor return), compounded daily from the $100k seed.

    ``sleeves`` is {sleeve_key: live_curve}, keyed to match :data:`WEIGHT_SCHEDULE`. Honest: real
    per-sleeve returns, pre-committed dollar weights that are fixed once the day has passed, the
    overlay a SEPARATE labelled beta line (commoditized, dilutes Sharpe, adds crash tail), no
    fabricated history. A sleeve with no mark on a day contributes nothing that day, so the
    flagship accrues from go-live even when the sleeves came online on different days.
    """
    sched = schedule if schedule is not None else WEIGHT_SCHEDULE
    dates_in_order = [d for d, _ in sched]
    if dates_in_order != sorted(dates_in_order):
        raise ValueError(f"WEIGHT_SCHEDULE must be in ascending date order, got {dates_in_order}")
    rets = {k: _daily_returns(c) for k, c in sleeves.items()}
    if all(len(c) < 2 for c in sleeves.values()):
        return [{"date": GO_LIVE, "equity": 100000.0}]
    mkt = market or {}
    dates = sorted({GO_LIVE}.union(*[set(r) for r in rets.values()]))
    out: list[dict] = []
    val = 100000.0
    for i, d in enumerate(dates):
        if i:
            w = _weights_on(d, sched)
            step = sum(w.get(k, 0.0) * r.get(d, 0.0) for k, r in rets.items()) + tilt * mkt.get(d, 0.0)
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
        # "decorrelated" -> "near-uncorrelated" 2026-08-07: the measured average pairwise
        # correlation is +0.072, POSITIVE. Near-uncorrelated is a real and useful property and it
        # is what we have; decorrelated is what we claimed, and the site had built its headline on
        # the stronger word.
        "asset": f"Cross-asset book ({N_SLEEVES} near-uncorrelated sleeves, measured pairwise "
                 f"{RHO_BAR:+.4f}, + disclosed strategic long)",
        "desc": f"AlphaForge + AlphaMax + AlphaTrend + AlphaVintage combined at {WEIGHTS_PROSE} — "
                "carry / equity momentum / managed-futures trend / PIT macro surprise. We used to "
                "call these 'near-uncorrelated' and call that decorrelation 'the edge'. Their "
                f"average pairwise correlation is {RHO_BAR:+.4f} — POSITIVE. The diversification is "
                "real but smaller than we said. AlphaVintage joined 2026-08-10 and is the reason "
                f"that number improved from {RHO_BAR_PRIOR_3_SLEEVE:+.4f}: it is the only sleeve "
                "reading a revision-aware macro release rather than price, funding or a balance "
                "sheet, and it earns its share by being uncorrelated, NOT by being better — its own "
                "net Sharpe is 0.34 and does not clear our 0.95 deflation gate either. "
                "AlphaTrend's re-derived DSR is 0.000, not the 0.83 we published: it is "
                "the WORST of them on the deflation measure, not the best. We keep it for "
                "measured drawdown reduction (removing it makes the book's max DD 22.7% worse: "
                "-3.68% -> -4.51% on the current four-sleeve book; we previously published 69% "
                "and that figure does not reproduce under any configuration we can find), not "
                "for a demonstrated edge. PLUS a "
                f"DISCLOSED {TILT_PROSE} strategic net-long overlay (0.5 BTC + 0.5 SPY) held as a SEPARATE "
                "labelled line — commoditized beta that adds bull-market participation but DILUTES "
                "risk-adjusted return and adds crash tail-risk; never blended into the neutral sleeves.",
        "standalone_sharpe": None,
        "live_kind": f"Derived: {WEIGHTS_PROSE} combination of the {N_SLEEVES} live sleeves + the disclosed {TILT_PROSE} beta overlay.",
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
                "inverse-vol weighted. THE RE-DERIVATION IS DONE (2026-08-07) AND IT WENT AGAINST "
                "US: at the honest trial count (N=133) and the pooled trial variance, its DSR is "
                f"0.000 — not the 0.83 we published, and the WORST of the {N_SLEEVES} sleeves rather than "
                "the best. The old 0.83 rested on a V[SR] input ~80x too small and n_trials=5 while "
                "AlphaMax was graded at N=101; it was marked on an easier exam and then called the "
                "soundest. Net Sharpe 0.25 over its full 5,179-day history. Positive skew, "
                "two-decade stable, near-uncorrelated to equities. We keep it because removing it "
                "measurably worsens book drawdown, not because its edge is established.",
        "standalone_sharpe": 0.33,
        "live_kind": "LIVE broker-executed — its 17-ETF book is submitted to Alpaca paper daily "
                     "(fills at the US open). Genuine fills, not a simulation.",
        "caveat": "We called this 'the soundest sleeve'. On the re-derived numbers that was wrong: "
                  "its DSR is 0.000 at honest N=133, the lowest of the three. It IS genuinely "
                  "broker-executed on Alpaca paper and it does survive 2008/2020/2022 with ~0 "
                  "equity correlation. As of the v2 restart "
                  "(" + MF_GO_LIVE + ") it is FOLDED INTO the flagship ALPHAC book at a 20% weight. "
                  "The case for keeping it is measured drawdown reduction, plus the fact that its "
                  "recent 3 years (-0.23) are a small and unrepresentative slice of a 20.6-year "
                  "record (+0.25 full, +0.28 over 15y) — judging a trend sleeve on its worst window "
                  "is the most documented allocator error there is. The case against it is that "
                  "0.000 is 0.000. Both are stated because both are true.",
        "wf": MF_WF, "live_db": str(MF_LIVE_DB),
    },
    {
        "key": "alphavintage", "name": "AlphaVintage", "rank": 4,
        "asset": "PIT macro-surprise size spread (IWM/SPY)",
        "desc": "Point-in-time CPI surprise — the standardized AR(3) residual of headline (PCPI) "
                "and core (PCPIX) inflation, differenced WITHIN a single ALFRED vintage — traded "
                "as a dollar-neutral IWM-minus-SPY size spread, monthly.",
        "standalone_sharpe": 0.34,
        "live_kind": "LIVE broker-executed — the two-leg spread is submitted to a dedicated Alpaca "
                     "paper account (PA39G6N49JRY); first fills 2026-08-10 at the US open.",
        "caveat": "Live since " + VINTAGE_GO_LIVE + ", so the record is DAYS old and proves nothing "
                  "yet. Net Sharpe 0.3403 with Newey-West t 1.82 over 5,996 days does NOT clear our "
                  "0.95 deflation gate — it earns its quarter of the book by being UNCORRELATED "
                  "(-0.065 to equity momentum, -0.046 to managed futures), not by being better. Two "
                  "disclosures: it runs at HALF the researched notional (gross 1.0x not 2.0x) "
                  "because 2.0x breaches our own runaway brake and this account's Reg T limit — "
                  "Sharpe is unchanged by scaling, dollar return is halved; and the research "
                  "modelled NO short-borrow cost while the live sleeve is short SPY ~95% of days, "
                  "a drag we now charge at 50bp/yr (0.3403 -> ~0.3060).",
        "wf": VINTAGE_WF, "live_db": str(VINTAGE_LIVE_DB),
    },
    {
        "key": "alphaforge", "name": "AlphaForge", "rank": 5,
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


def crypto_uptime() -> dict:
    """Measured cycle uptime of the crypto sleeve's hourly loop, computed at PUBLISH time.

    Why this is computed rather than written down: the 2026-07-20 incident note went stale.
    It was prose, it described a single outage since 07-18, and the sleeve then went on
    missing most of its cycles for another two weeks while the note kept saying one thing and
    the machine did another. A disclosure that hardcodes a number starts decaying the moment
    the number moves. This one is re-measured on every publish, so the published record cannot
    drift away from the database again.

    Returns {} on any failure — a missing uptime block is honest; a fabricated one is not.
    """
    try:
        con = sqlite3.connect(f"file:{CRYPTO_LIVE_DB}?mode=ro", uri=True)
        try:
            ts = [r[0] / 1000.0 for r in con.execute(
                "SELECT cycle_ts FROM cycles ORDER BY cycle_ts")]
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    if len(ts) < 2:
        return {}
    now = dt.datetime.now(dt.UTC).timestamp()
    expected = max((now - ts[0]) / 3600.0, 1.0)          # the loop is hourly by design
    gaps = [(ts[i + 1] - ts[i]) / 3600.0 for i in range(len(ts) - 1)]
    dark = sum(g - 1 for g in gaps if g > 1.5) + (now - ts[-1]) / 3600.0
    return {
        "cycles_completed": len(ts),
        "cycles_expected": round(expected),
        "uptime_pct": round(100.0 * len(ts) / expected, 1),
        "dark_hours": round(dark),
        "record_days": round((now - ts[0]) / 86400.0, 1),
        "longest_outage_hours": round(max(gaps)) if gaps else 0,
        "outages_over_24h": sum(1 for g in gaps if g > 24),
        "dark_since_hours": round((now - ts[-1]) / 3600.0),
        "last_cycle_utc": dt.datetime.fromtimestamp(ts[-1], dt.UTC).strftime("%Y-%m-%d %H:%M"),
    }


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
        f"({WEIGHTS_PROSE}), and (b) gained a DISCLOSED +20% strategic net-long overlay (0.5 BTC + 0.5 "
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
        f"or metric changed with the reorder; the book's composition weights ({WEIGHTS_PROSE}) and every "
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
        "AlphaTrend (managed-futures trend) was the FIRST sleeve we took genuinely live: its 17-ETF "
        "book transacts on Alpaca paper, not in a simulator. We published DSR 0.83 for it and called "
        "it the first sleeve to CLEAR multiple-testing deflation, statistically real rather than a "
        "backtest fluke. RE-DERIVED 2026-08-07 at honest N=133 and pooled V[SR]=7.96e-04, its DSR is "
        "0.000: the LOWEST of the six sleeves we have measured, not the highest. The old 0.83 rested "
        "on a variance input roughly 80x too small and a trial count of 5 while its siblings were "
        "graded at N=101, so it was marked on an easier exam and then called the soundest. Net Sharpe "
        f"0.25 over its full 5,179-day history. It is folded into ALPHAC at {WEIGHTS_PROSE} for "
        "MEASURED drawdown reduction, not for a demonstrated edge. The screen suggested 0.73; the "
        "honest engine says 0.33 on the live window. We published every one of those numbers.",
        _crypto_uptime_verdict(),
        "CORRECTION 2026-08-06 — our crypto carry sleeve is a strategy that earns funding, and "
        "its LIVE paper account has never once booked funding. We found this ourselves and are "
        "publishing it before the fix rather than after. The mechanism, stated plainly so anyone "
        "can check it: funding is applied in exactly one place in this codebase, "
        "Ledger.apply_funding, and it is called from exactly one call site, the BACKTEST engine. "
        "The live paper broker's cash moves on one line and only one line, a fill: "
        "cash - qty*price - fee. No funding cashflow can reach the live account by any path. The "
        "size of what is missing is not marginal. Our committed walk-forward artifact for this "
        "sleeve reports funding_net of $19,500 against a total return of $38,236 on a $100k book "
        "over 2022-02 to 2026-06: about HALF of everything this strategy has ever earned is the "
        "funding it is designed to harvest. Removing it takes the sleeve's backtested Sharpe from "
        "0.653 to roughly 0.30. So AlphaForge's live record has been running against a hard "
        "ceiling of about half its validated Sharpe, and every live number we have published for "
        "this sleeve should be read in that light. What we are NOT doing: we are not restating "
        "the historical live curve. The marks we published were the marks we observed, and this "
        "record is append-only, so the fix applies FORWARD from the day it ships and the "
        "understated period stays visible in the chain. One number we are deliberately NOT "
        "putting on the record yet: our internal estimate of what funding would have added over "
        "the live window is dominated by a single name that redenominated roughly 100x inside "
        "the window, which makes the naive figure meaningless. We would rather publish no number "
        "than a number we cannot stand behind, so that one waits for the corrected accounting. "
        "This is the fourth time a defect in our plumbing, not our strategy, has moved a "
        "published number, and the lesson we wrote down in July holds: a fix is not done until a "
        "test pins the path that actually runs.",
        "CORRECTION 2026-08-06 — a factual claim in our 2026-07-20 incident note above is now "
        "false and we are marking it rather than editing it. That note said 'Bybit responds' as "
        "evidence the Binance failure was venue-specific. Re-measured from the same network on "
        "2026-08-06: Bybit does NOT respond, and neither do Kraken or Deribit. Binance, Bybit and "
        "Kraken all fail on connection reset in under a tenth of a second and Deribit times out. "
        "The conclusion the original note drew is unchanged and if anything strengthened, since "
        "the block is clearly broader than one venue, but the supporting fact it cited is no "
        "longer true and a reader checking our work today would find it wrong. One venue does "
        "answer: OKX responds normally and serves funding rates, 436 perpetual instruments and "
        "hourly candles. We are evaluating it, and we note in advance that moving venue is not a "
        "configuration change: the same carry signal computed on OKX has a cross-sectional rank "
        "correlation of only about 0.64 with the Binance one, so it would be a materially "
        "different strategy wearing the same name, and we will not splice the two curves "
        "together and call it one continuous record.",
        "FIXED 2026-08-06 — the funding gap disclosed above is now closed in the live path, "
        "forward only. Earlier today we published that our crypto carry sleeve had never once "
        "booked funding in live paper, which is roughly half of everything that strategy has "
        "ever earned. That is fixed: the live broker gained a funding path with the identical "
        "sign convention the backtest ledger uses (payment = -position * mark * rate, longs pay "
        "shorts on a positive rate), and the live loop now settles every stored funding event "
        "for the window just closed, before the strategy re-decides, so a settlement is charged "
        "against the position that was actually held through it. It is point-in-time by "
        "construction: the reader filters on each event's stored publication time, never on the "
        "settlement time, so a rate not yet knowable at the moment of the cycle stays invisible. "
        "Nine tests pin the running path rather than the intention, including one that asserts "
        "the live broker and the backtest ledger return identical figures for the same event, "
        "because two conventions would be worse than none. Three things we are deliberately NOT "
        "doing. We are not restating the historical curve: the marks we published are the marks "
        "we observed, the understated period stays in the signed chain, and the fix applies from "
        "today. We are not claiming an improvement yet: the sleeve has been dark on venue "
        "unreachability since 2026-08-03, so this books nothing until it trades again, and any "
        "future gain will show up in the forward record or not at all. And we are not putting a "
        "number on what it would have earned over the live window, because our own measurement "
        "of that is dominated by a single instrument that redenominated roughly 100x inside the "
        "window, which makes the figure meaningless. We would rather publish no number than one "
        "we cannot stand behind.",
        "RE-DERIVATION 2026-08-06 — we said we would recompute our deflated Sharpes honestly "
        "and publish whatever came back. Here it is, and it is bad. Deflated Sharpe is the "
        "probability a result beats what the best of N random trials would produce, so it needs "
        "two inputs we had both got wrong: N, and the variance of Sharpe across our own trials. "
        "Using the honest N of 127 distinct hypotheses and a V[SR] of 7.96e-04 pooled across all "
        "171 trials in every ledger, on each sleeve's full history: **AlphaMax 0.213** (annual "
        "Sharpe 0.699 over 728 days), **AlphaForge 0.052** (0.512 over 1,574 days), and "
        "**AlphaTrend 0.000** (0.249 over 5,177 days). Our deploy gate is 0.95. Nothing is "
        "close. AlphaTrend deserves the full explanation because its published 0.83 was the "
        "single best number on this site. We reproduced it exactly from its original inputs, "
        "n_trials=5 and V[SR]=1.0e-05, which returns 0.805. Then we corrected one input at a "
        "time. Holding N at 5 and using the honest pooled variance instead takes it to **0.098**; "
        "using the honest N as well takes it to **0.000**. So that 0.83 was not mainly about "
        "trial count. It rested on a Sharpe-variance input roughly EIGHTY TIMES smaller than the "
        "one measured across our own trial history, and a smaller variance means a lower bar to "
        "clear. Our other sleeves were graded against the larger, correct-order variance. We "
        "were, without noticing, grading one sleeve on an easier exam and then calling it the "
        "soundest. The honest position: **not one of our three sleeves is statistically "
        "distinguishable from luck once its own search is accounted for**, and the sleeve we "
        "called 'statistically real, not a backtest fluke' scores zero. That does not mean the "
        "strategies are worthless; it means our BACKTEST evidence cannot carry them, which is "
        "why the only thing that can settle it is a long forward record we have not yet earned. "
        "We publish this in full because a number that only survives on a favourable input is "
        "not evidence, and finding that out about our own best figure is exactly what this "
        "record exists to make impossible to hide.",
        "CORRECTION 2026-08-06 — we have been counting our own experiments in one place while "
        "running them in four, so every deflated Sharpe we publish is more flattering than it "
        "should be. Our honesty machinery penalises a result for how many ideas we tried before "
        "we picked it, and that count is read from a trial ledger. It reads ONE ledger, "
        "var/experiments.jsonl, which holds 127 rows and 101 distinct hypotheses. But research "
        "run under other data profiles writes to its own ledger, and those were never totalled "
        "anywhere: 35 more rows under the managed-futures profile, 12 under Sharadar, 1 under "
        "futures. Deduplicated across all four, the honest count is **127 distinct hypotheses, "
        "not 101** — our real search was 26% larger than the number we deflate against. Which "
        "directory a trial landed in is a filing convention. Multiple-testing correction does "
        "not care about filing conventions: those were all real hypotheses about the same "
        "markets, spent by the same researcher, hunting sleeves for the same book. The "
        "consequence is one-directional and it is against us: an undercounted N makes a "
        "deflated Sharpe look better, so every DSR on this record computed against N=101 (and "
        "the earlier N=93, and the N=27 our equity sleeve was first published at) reads better "
        "than the truth. We are not restating those figures today because re-deriving each one "
        "properly is its own piece of work and we would rather publish the error immediately "
        "than a hasty replacement. Treat every DSR on this site as an upper bound until they are "
        "re-derived. Fixed at the source: the audit now counts the union of every ledger, which "
        "also closes the evasion this revealed — a future search can no longer duck the budget "
        "by writing to a directory nobody adds up.",
        "CORRECTION 2026-08-06 — our social card has been advertising a forward Sharpe we "
        "stopped believing weeks ago. The image that unfurls whenever this site is shared on "
        "LinkedIn, X, Slack or anywhere else read 'FORWARD EXPECTATION 0.7 TO 1.0 SHARPE, AFTER "
        "DEFLATION'. Our published expectation is 0.3 to 0.9, so the FLOOR was overstated by a "
        "factor of 2.3, and the words 'after deflation' made it a specific technical claim "
        "rather than loose marketing. The same card said 'three quant algorithms' when we "
        "publish four, and called the book market-neutral without mentioning the +20% net-long "
        "overlay we disclose everywhere else. It went stale when we lowered the band on "
        "2026-07-29 and nothing pointed at it, because it is an image rather than a number in "
        "an artifact, and our freshness checks only ever look at artifacts. Replaced with a card "
        "that carries NO performance figure at all: a picture that travels across the internet "
        "for months and cannot be corrected in a reader's cache has no business quoting a Sharpe "
        "ratio. Note for anyone verifying: the social platforms cache these aggressively, so the "
        "old card may keep appearing on previously-shared links for some time. That is the "
        "clearest possible argument for never putting a number on one. Also corrected in the "
        "same pass: our app manifest still named the firm 'Canli Capital / AlphaForge' and "
        "described it as an engine for crypto perpetual futures, which describes ONE 40% sleeve "
        "rather than the book.",
        "CORRECTION 2026-08-06 — the decorrelation we call 'the edge' was measured on a basket "
        "containing a strategy we do not trade, and correcting it removes our headline claim. "
        "We publish an average pairwise sleeve correlation of -0.04 and describe this book as "
        "'three near-uncorrelated sleeves; that decorrelation is the edge'. That -0.04 was "
        "computed over FOUR equity curves, and one of them, prereg_investment, is not a sleeve. "
        "The book is and always has been three sleeves: AlphaForge, AlphaMax and AlphaTrend. The "
        "script's own comment described its inputs as 'the four curves that make up the live "
        "book', which was simply not true of the book. Recomputed on the three sleeves we "
        "actually trade, over the identical 728-day window: average pairwise correlation is "
        "**+0.072, positive**, not -0.040; average sleeve Sharpe is 0.529; and the worst pair, "
        "AlphaMax against AlphaTrend, correlates at **+0.21** because momentum and trend are "
        "close cousins and always were. Why this matters more than a third decimal place: a "
        "book of N sleeves has effective breadth N/(1+(N-1)*rho), which converges to 1/rho, so "
        "its Sharpe can never exceed s/sqrt(rho). At a NEGATIVE rho that ceiling does not "
        "exist, and we have been reasoning and planning as though it did not. At the true "
        "+0.072 the ceiling is **1.97** — meaning no number of additional sleeves of this "
        "quality, not fifty and not two hundred, can take this book past a Sharpe of about 2. "
        "Our stated goal is 2.5. On the correlation we have now measured rather than assumed, "
        "that goal is unreachable by adding sleeves, and it was our own measurement error that "
        "hid the ceiling. Fixed at the source, and the corrected figure is now what the "
        "analysis emits. We are stating this in full because it is the single most load-bearing "
        "number in our research, we got it wrong, and the error ran in the direction that "
        "flattered the plan.",
        "CORRECTION 2026-08-06 — for six weeks our two public sites published two different "
        "track records for the same book, and the stale one was the flattering one. "
        "app.canlicapital.com was serving glass-box artifacts last generated 2026-06-24: a "
        "track record reading 0.00% return over '3 days live' with NAV at a clean $100,000, "
        "while canlicapital.com served the truth for the identical book, -2.54% over 38 days "
        "with NAV $97,459. Anyone who opened the dashboard saw a flat, unblemished record. "
        "Anyone who opened the landing page saw a loss. Both were live at the same time. The "
        "cause was mundane and that is the point: our publisher copies paper-state.json to both "
        "sites but the three glass-box exporters wrote only to the landing site's directory, so "
        "the dashboard's copies simply stopped updating on 2026-06-24 and nothing alerted. Our "
        "health check verifies that both hosts serve the same paper-state.json; it never checked "
        "the glass-box files, so the gap was invisible to the monitor built to catch exactly this. "
        "Fixed at the source: all three exporters now write one stamped string to both directories, "
        "so the two hosts are byte-identical by construction and cannot disagree even about a "
        "content hash. We are stating this plainly because a firm whose entire claim is that its "
        "record cannot be quietly re-picked was, for six weeks, publishing two different inception "
        "stories on two different hosts, and the more favourable one was the one that was wrong.",
        "CORRECTION 2026-08-06 — we have said AlphaTrend 'CLEARED multiple-testing deflation' "
        "and it did not. Our deploy gate is DSR >= 0.95. AlphaTrend's DSR is 0.83. **0.83 does "
        "not clear 0.95**, and the sentence on this record calling it 'the FIRST sleeve to CLEAR "
        "multiple-testing deflation, statistically real, not a backtest fluke' was wrong when we "
        "wrote it and has been wrong every day since. What is true is narrower and we should have "
        "written it: AlphaTrend scores far better on that measure than anything else we have "
        "built, and it was the closest any sleeve had come. That is not the same as clearing. "
        "There is a second problem behind the first. AlphaTrend's 0.83 was computed at "
        "n_trials=5, while AlphaMax was graded against N=101 on the same record. Those two "
        "numbers are not comparable, and presenting them side by side flattered the one graded "
        "against fewer trials. Re-graded against the ledger as it actually stands the figure "
        "falls, and we are re-deriving it before we publish a replacement rather than quoting a "
        "number we have not recomputed. Until that lands, treat AlphaTrend's DSR on this site as "
        "WITHDRAWN rather than merely caveated.",
        "DISCLOSURE 2026-08-06 — our sleeve-admission gate is not calibrated, and we have been "
        "applying it in a way that protects what we already own. Two facts sit badly together. "
        "First, to clear DSR >= 0.95 on a 21-year daily sample at our current trial ledger, a "
        "candidate must print an annualised net Sharpe of about **1.64** (and about 1.11 even at "
        "the nine trials we originally pre-registered). Essentially nothing in the published "
        "factor literature is that strong; the best-documented effects sit under 0.8. We ran the "
        "nine canonical, 25-year-replicated effects through our own gate and not one of them "
        "passes at any trial count. Second, **both sleeves we actually run also fail it** — "
        "AlphaMax at DSR 0.17, AlphaTrend at 0.83 — and we deployed them anyway, while using the "
        "same gate to kill four whole asset classes at the design stage before spending a single "
        "trial on them. A bar that incumbents are exempt from and challengers are not is not a "
        "standard, it is an incumbency advantage, and we are naming it as ours. Two construction "
        "defects behind the gate compound this and are also ours to state: there is NO beta hedge "
        "implemented anywhere in this codebase, yet our own pre-registration mandates one for "
        "betting-against-beta and kills the candidate if realised beta exceeds 0.2, so that kill "
        "was guaranteed before any data was loaded; and our fundamentals screen was run with no "
        "positive control, which means its eight null results cannot distinguish 'these factors "
        "do not work' from 'this harness does not work'. We are rebuilding the admission test to "
        "separate the two questions it currently conflates, significance of a pre-registered "
        "candidate versus deflation of a book selected from many. We will publish the replacement "
        "and re-grade every sleeve against it, including the ones we already own, and we expect "
        "that to make our own numbers look worse rather than better.",
        "DISCLOSURE 2026-08-06 — the sleeve we call 'crypto funding carry' is 20% commodities, "
        "and two sleeves we present as decorrelated are trading the same metals and the same "
        "crude. Our universe rule ranks Binance perpetuals purely on 30-day median quote volume "
        "and has no predicate on what the contract actually tracks. Binance lists perps on "
        "commodities, and they are liquid enough to rank in. Four of AlphaForge's twenty current "
        "members are therefore not crypto at all: XAU (gold) and XAG (silver), which entered "
        "2026-03-01, and CL (WTI) and BZ (Brent), which entered 2026-06-01. Their prices confirm "
        "what they are — gold marks near $4,543, silver near $75.62, WTI near $89.35, Brent near "
        "$93.00. Meanwhile AlphaTrend, the sleeve we hold BECAUSE it is decorrelated, currently "
        "holds GLD, SLV, USO, DBC, DBA and UNG. So gold, silver and crude sit on both sides of a "
        "book whose entire construction rests on those sides being independent. We are not "
        "claiming this has hurt returns; carry on a gold perp may be a perfectly good trade. Two "
        "things about it are nonetheless wrong and are ours to say. First, our public description "
        "of this sleeve says 'crypto', and for a fifth of its universe that is not accurate. "
        "Second, and more consequential: the -0.04 average pairwise sleeve correlation we publish "
        "was measured on a window ending 2026-06-01, which is the very day the crude perps "
        "entered and only three months after the metals did. That figure therefore describes a "
        "book with less overlap than the one we are running now, and the honest reading is that "
        "our measured decorrelation is likely to be better than our future decorrelation. Since "
        "average correlation is the binding constraint on everything this book is trying to "
        "become, that error runs in the direction that flatters us, which is the direction we "
        "have committed to publishing fastest.",
        "DISCLOSURE 2026-08-06 — our crypto universe has not rebalanced since 2026-06-01 and we "
        "did not notice until we went looking for something else. The universe rebuilds monthly "
        "at a month boundary inside the live cycle. Membership rows exist for 2025-11-01 through "
        "2026-06-01 without a gap, and then stop: the 2026-07-01 and 2026-08-01 rebalances both "
        "failed to run, because the sleeve was dark for most of that period on the venue "
        "unreachability documented above. This is a second-order cost of an outage that we had "
        "only accounted for in missed cycles: the sleeve did not merely stop trading, it froze "
        "its own definition of what it trades, and has spent over two months holding a universe "
        "selected against two-month-old liquidity. We are recording it here rather than quietly "
        "rebuilding, because an outage that silently changes what a strategy IS matters more than "
        "one that merely pauses it.",
        "CORRECTION 2026-08-11 — this site published a 300% one-day gain that never happened, and "
        "it stood for three days. Our flagship live curve read 100,000.00 on 2026-08-07 and "
        "400,207.73 on 2026-08-08. ALPHAC is market-neutral and runs gross at or below 1.0x; it "
        "cannot quadruple in a session, and it did not. The cause was mundane and entirely ours. "
        "On 2026-08-07 the book moved to fresh $1M accounts, and the routine that records broker "
        "equity wrote history with INSERT OR REPLACE — merging each account's history into "
        "whatever was already stored rather than replacing it. Rows written while a profile still "
        "pointed at the SUPERSEDED account therefore survived at any timestamp the new account's "
        "history did not happen to cover. AlphaTrend's curve ended up holding $1,000,000 marks "
        "from the new account interleaved with a $100,681.45 mark from the old $100k one. The "
        "reader rebased on the first mark, turning that row into 10,068, and the step to the next "
        "day published as a +893% return; at one third weight that is +297% on the book. Two "
        "compounding defects: several marks a day meant two points shared a date, so a 'daily "
        "return' was computed between two marks of the same afternoon; and nothing rejected a "
        "step that is arithmetically impossible for the strategy. Both are fixed. The writer now "
        "REPLACES the curve, since a broker's full history is authoritative on its own and "
        "merging into it is unsound — which also self-healed the stored data, taking two sleeve "
        "curves from 68 and 52 mixed marks down to 4 and 4 clean ones. The reader keeps one mark "
        "per day and refuses to splice a superseded account into a current record. Six tests pin "
        "the exact marks that produced 400,207, and one asserts a genuine -10% day is NOT "
        "mistaken for an account switch, because a guard that trimmed real drawdowns would "
        "flatter this record rather than protect it. The corrected figure for the same window is "
        "99,887.94, i.e. -0.11%. We are stating the wrong number here in full rather than "
        "replacing it quietly: it was public, it was flattering, and anyone who looked at this "
        "site in those three days saw it.",
        "ADDED 2026-08-10 — AlphaVintage joins the book as a fourth live sleeve and the weights "
        "move to equal quarters. It trades the IWM/SPY size spread off the point-in-time CPI "
        "surprise (the standardized AR(3) residual of headline and core inflation, differenced "
        "WITHIN a single ALFRED vintage), and it is the only sleeve here reading a revision-aware "
        "macro release rather than price, funding or a balance sheet. Two things must be said "
        "plainly. First, it does NOT clear our deflation gate: net Sharpe 0.3403 with a "
        "Newey-West t of 1.82 over 5,996 days. It earns its quarter by being uncorrelated "
        "(-0.065 to equity momentum, -0.046 to managed futures), not by being better — adding it "
        "cut the book's average pairwise correlation from +0.0723 to +0.0274. Second, it runs at "
        "HALF the researched notional: the pre-registered spec sizes each leg at 1.0x NAV for "
        "2.0x gross, which exceeds our own runaway brake and equals this account's Reg T "
        "overnight limit exactly, leaving no cushion on a month-long hold. Sharpe is "
        "scale-invariant so the validated figure still applies; the dollar return, the volatility "
        "and the drawdown are all halved. A third disclosure we owe: the research modelled NO "
        "short-borrow cost while the live sleeve is short SPY on about 95% of days. Charged at "
        "50bp/yr that is 0.3403 -> roughly 0.3060, and the live sleeve is therefore held to a "
        "harsher standard than the study that justified it. The days before 2026-08-10 continue "
        "to compound at equal thirds; we appended a dated weight entry rather than restating "
        "three already-published days.",
        "CHANGE 2026-08-12 — we cut the strategic beta overlay from +20% to +10%, on measurement "
        "rather than taste, and we are showing the numbers that decided it. The overlay was never "
        "claimed to be alpha; what nobody had done was measure what it does to the book. Measured "
        "on the 4-sleeve research book over its 1,061-day common window, and then stressed by "
        "replaying the market factor's worst equal-length stretch under an UNCHANGED neutral core "
        "so that only the overlay varies. Measured window / crash stress, by overlay size: 0% "
        "gives 1.396 / 1.396; 5% gives 1.667 / 1.308; 10% gives 1.784 / 1.192; 12.5% gives 1.799 "
        "/ 1.128; 20% gives 1.760 / 0.929; 30% gives 1.651 / 0.686. The SHAPE decides it, not any "
        "one cell: measured-window Sharpe is FLAT from 5% to 15% while crash-stress Sharpe falls "
        "monotonically with size and the worst day grows steadily (-0.90% at 0%, -1.26% at 10%, "
        "-2.02% at 20%). When one axis is flat and the other is monotone you take the lower "
        "number — the same upside for strictly less tail. Cutting 20% to 10% therefore costs "
        "nothing measurable in the window (1.760 to 1.784, marginally higher) while recovering "
        "+0.26 of stress Sharpe and cutting the worst day roughly in half. WE DELIBERATELY DID "
        "NOT PICK THE PEAK: 12.5% maximises the measured window, and choosing the argmax of a "
        "curve fitted to one window is the selection trap our own deflation discipline exists to "
        "prevent. And we correct ourselves in passing: an earlier internal note claimed 10% would "
        "halve the upside to 1.578. That figure was a linear interpolation, never measured, and "
        "it was wrong — the upside is essentially unchanged. We did NOT cut it to zero: equity beta "
        "has positive long-run drift and this capital is explicitly stated to want participation, "
        "so removing it entirely would trade real expected return for a cleaner-looking ratio. "
        "TWO CAVEATS THAT BOTH CUT THE SAME WAY, stated because they make our own prior numbers "
        "look better than they should. First, the crash stress ran at effectively HALF weight: the "
        "market factor is 0.5 BTC + 0.5 SPY and a missing leg contributes zero, but our BTC series "
        "begins 2020-01-01, so the pre-2020 stress was SPY-only. A real crash in which both legs "
        "fall together costs more than the -0.47 Sharpe we measured. Second, the window in which "
        "the overlay LOOKED good rose +121.6% with a worst drawdown of -28.2%, against -54.4% "
        "available in that same factor's own history — the upside is measured in a bull market and "
        "the downside is not. Every published figure that carried the +20% overlay, including the "
        "in-sample 1.80, describes a configuration we no longer run; the neutral-core figure "
        "(1.396 on the current four sleeves) is unchanged and always was the honest one.",
        "CORRECTION 2026-08-12 — the number we use to justify keeping AlphaTrend does not "
        "reproduce, and it overstated the case by about 3x. We publish that AlphaTrend is held "
        "'for measured drawdown reduction (removing it makes the book's max DD 69% worse), not "
        "for a demonstrated edge'. Re-measured on the current four-sleeve book, removing it takes "
        "max drawdown from -3.68% to -4.51%, i.e. 22.7% worse — not 69%. We looked for a "
        "configuration that yields 69% and could not find one: on the three-sleeve book we "
        "previously ran at 40/40/20 it is 16.6%, at equal thirds 20.5%, and with the beta overlay "
        "applied it falls to 4.4-7.0%. The rest of the sleeve's disclosure stands and is if "
        "anything harsher than "
        "before: leave-one-out on the current book shows AlphaTrend CONTRIBUTES -0.092 Sharpe "
        "(removing it would raise the book from 1.396 to 1.488), its standalone Sharpe of 0.248 "
        "is the weakest of the four, and its re-derived DSR is 0.000. So it is held for a real "
        "but materially smaller diversification benefit than we claimed. WHAT WE DID NOT DO: "
        "change its weight. A weight sweep shows a clean monotone trade — roughly 0.13 Sharpe per "
        "1 percentage point of drawdown, with no optimum anywhere — so any weight we picked off "
        "that curve would be a risk preference dressed as a measurement, and choosing the "
        "in-sample argmax is the selection trap our deflation discipline exists to prevent. Equal "
        "weights remain what the evidence supports: no sleeve's deflated Sharpe justifies more "
        "capital than any other's, which is exactly why they are equal.",
    ]


def _crypto_uptime_verdict() -> str:
    """STRUCTURAL VERDICT on the crypto sleeve's venue access — the promise we made ourselves.

    The 2026-07-20 OPEN INCIDENT entry (kept above, unedited, because this list is append-only)
    committed us to a follow-up in its own words: "If it proves persistent it is a STRUCTURAL
    problem for a sleeve built on a single venue, and we will say that too." It proved
    persistent. This is that entry, and its numbers are measured at publish time so it cannot
    go stale the way the note above did.
    """
    u = crypto_uptime()
    if not u:
        return ("STRUCTURAL VERDICT 2026-08-05 — the crypto sleeve's venue access is a standing "
                "structural problem, not a run of bad luck. Uptime could not be measured at this "
                "publish (the sleeve's cycle database was unreadable), which is itself reported "
                "rather than quietly omitted.")
    return (
        "STRUCTURAL VERDICT 2026-08-05 — the crypto sleeve's venue unreachability is STRUCTURAL, "
        "and we said we would say so. The 2026-07-20 note above promised: 'if it proves persistent "
        "it is a STRUCTURAL problem for a sleeve built on a single venue, and we will say that "
        "too.' It has proved persistent, so here is the number we had not put on the record until "
        f"now: across its entire live history the hourly loop has completed {u['cycles_completed']} "
        f"of {u['cycles_expected']} expected cycles — an uptime of {u['uptime_pct']}%. It has been "
        f"dark for roughly {u['dark_hours']} hours of a {u['record_days']}-day record, with "
        f"{u['outages_over_24h']} separate outages longer than a day and a longest single outage of "
        f"{u['longest_outage_hours']} hours. As of this publish it has been dark "
        f"{u['dark_since_hours']} hours; its last observed cycle was {u['last_cycle_utc']} UTC. "
        "WHAT THIS MEANS, stated plainly rather than buried: this sleeve carries 40% of the "
        "flagship's weight, so for most of the forward record our largest single position has not "
        "been managed. The published curve is not wrong — we never roll forward a mark we did not "
        "observe, so the sleeve's line simply stops when the venue does — but a 40%-weight sleeve "
        "that is dark most of the time is not meaningfully 'live', and describing it as live "
        "without this number attached would have been a half-truth. The forward track record is "
        "the whole basis on which this book asks to be believed, and it is being accrued on a "
        "book whose biggest sleeve is mostly absent. WHAT WE ARE DOING: the diagnosis is unchanged "
        "and venue-specific (the general internet and our equity broker respond normally from the "
        "same machine while the exchange endpoint fails on connect). Two fixes are real — hosting "
        "the loop somewhere with unobstructed access, and removing the single-venue dependency "
        "altogether by adding a second exchange. We flag the first honestly: our own deploy "
        "runbook records that reaching a venue from a different region is a COMPLIANCE decision "
        "and not merely an operations one, so it will not be done as a silent infrastructure "
        "tweak. Until one of those lands, read this sleeve's contribution to the live record as "
        f"what it is — {u['uptime_pct']}% of the intended trading."
    )


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
    # AlphaVintage's evidence is a pre-registered PROBE, not a walk-forward — see load_probe_curve.
    vintage_wf = load_probe_curve(VINTAGE_WF, "artifacts/probe/cpi_surprise_size/equity.parquet")
    sleeves = [equity_wf, crypto_wf, mf_wf, vintage_wf]
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
        "alphavintage": sample_curve(vintage_wf.ts_ms, vintage_wf.equity, scale=1.0),
        "alphac": sample_curve(book.days, book.equity_curve, scale=100000.0),
    }
    # live (realized) curves - honest, no fabricated history
    crypto_live = read_live_db(CRYPTO_LIVE_DB)
    equity_live = read_live_db(EQUITY_LIVE_DB, go_live=EQ_GO_LIVE)  # realized broker fills, $100k-rebased
    # AlphaTrend: the REALIZED Alpaca-paper account equity (genuine broker fills), seeded from its
    # own go-live. live_cycle.py writes a mark each daily run; the curve accrues real marks as the
    # ETF book fills and marks to market. No simulation, no backdating.
    mf_live = read_live_db(MF_LIVE_DB, go_live=MF_GO_LIVE)
    # The combined live curve reads WEIGHT_SCHEDULE, not weights derived here.
    #
    # REMOVED 2026-08-07: this block computed w_cr/w_eq/w_mf as book.weights[...].mean() — the mean
    # weight from TODAY's combine_book run — and handed them to combined_live, which applied them to
    # every day back to go-live. The comment above them said "committed fixed dollar weights (NOT
    # re-estimated live)", and while the book sat at a frozen 40/40/20 that was true in effect. It
    # was not true in mechanism: any change to the weights would have retroactively restated every
    # published live day. Weights now come from the append-only WEIGHT_SCHEDULE so a past day's
    # value cannot move.
    # Clamp every REALIZED sleeve curve to <= today BEFORE combining, so a future-dated vendor/
    # engine bar can neither be published nor leak into the combined book or the transparency chain.
    # AlphaVintage: REALIZED equity from its own Alpaca paper account (PA39G6N49JRY), seeded from
    # its own go-live. live_cycle.py --profile alphavintage writes a mark each daily run.
    vintage_live = read_live_db(VINTAGE_LIVE_DB, go_live=VINTAGE_GO_LIVE)
    crypto_live = clamp_live(crypto_live)
    equity_live = clamp_live(equity_live)
    mf_live = clamp_live(mf_live) or [{"date": MF_GO_LIVE, "equity": 100000.0}]
    vintage_live = clamp_live(vintage_live) or [{"date": VINTAGE_GO_LIVE, "equity": 100000.0}]
    live = {
        "alphaforge": crypto_live,
        "alphamax": equity_live,
        "managed_futures": mf_live,
        "alphavintage": vintage_live,
        # A sleeve with no mark on a day contributes nothing that day (see combined_live), so the
        # flagship accrues correctly across sleeves that came online on different dates — which is
        # exactly the case here: vintage has no marks before 2026-08-10 and must not invent any.
        "alphac": clamp_live(combined_live(
            {"crypto": crypto_live, "equity": equity_live, "mf": mf_live, "vintage": vintage_live},
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
    # AlphaVintage's book is the two-leg spread written by scripts/alphavintage_target.py. Read
    # from the SAME artifact live_cycle submits from, so the published holdings cannot drift from
    # the ones actually sent to the broker.
    vintage_hold = read_equity_holdings(f"artifacts/walkforward/{VINTAGE_WF}")
    holdings = {
        "alphaforge": cr_hold, "alphamax": eq_hold,
        "managed_futures": mf_hold, "alphavintage": vintage_hold, "alphac": eq_hold,
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
            # Machine-readable uptime for the one sleeve that runs its own hourly loop. A reader
            # comparing "live_days" against reality deserves the denominator too: elapsed days
            # say how long we have CLAIMED to be live, uptime says how much of it we actually
            # traded. Emitted as data, not only prose, so the site cannot show one without the
            # other and a verifier can check it without parsing English.
            **({"cycle_uptime": crypto_uptime()} if a["key"] == "alphaforge" else {}),
        })

    metrics = {
        "in_sample_sharpe": round(float(book.sharpe), 2),
        # ALPHAC carries a disclosed net-long overlay, +10% since 2026-08-11 (it was +20% until
        # then; cut on measurement, not taste). The in-window Sharpe is the TILTED book's, and it
        # is INFLATED by a favourable bull window — the overlay is commoditized beta, which
        # DILUTES honest-forward Sharpe rather than improving it. Read STRATEGIC_TILT_PCT for the
        # live figure; this comment has already been stale once and a number in prose beside a
        # derived value is exactly how the site came to assert things the record had withdrawn.
        "neutral_core_in_sample_sharpe": round(float(book_neutral.sharpe), 2),
        # Widened + lowered after the 2026-06-27 red-team AND the 2026-06-29 tilt: the neutral 0.7-1.0
        # is optimistic for the LIVE book (crypto carry flat, equity deep-history forward ~0.08/DSR
        # 0.34); the +20% beta does not lift forward Sharpe and adds crash tail. Honest band is wider.
        "honest_forward_sharpe": (
            f"0.3 to 0.9 (the {TILT_PROSE} beta does NOT improve this — it adds bull upside + "
            "crash risk, not risk-adjusted quality; real chance of ~0 yr1)"
        ),
        "in_sample_cagr_pct": round(float(book.cagr) * 100, 1),
        "honest_forward_return_pct": "0 to 14 (vol-targeted; lower bound is real)",
        # The measured book curve starts 2023-07 and contains NO 2020-Covid / 2022 bear, so this
        # computed number is a LIVE-OVERLAP artifact, not a risk estimate. The honest crisis-
        # inclusive worst-case lives in realistic_worst_dd_pct (the headline the UI shows).
        "max_drawdown_pct": round(float(book.maxdd) * 100, 1),
        "max_drawdown_note": "live-overlap window only (2023-07+); EXCLUDES 2022 & Covid — NOT a risk estimate",
        # neutral core -15 to -18, PLUS the +20% overlay's ~-7% hit in a crypto-50%/equity-20% crash.
        "realistic_worst_dd_pct": (
            f"-22 to -28 (incl. the {TILT_PROSE} strategic-long overlay's crash tail)"
        ),
        # CORRECTED 2026-08-07. This field published "Calm: ~-0.02" — a NEGATIVE average pairwise
        # correlation, and the site called that decorrelation "the edge". It was measured on a
        # basket containing `prereg_investment`, a curve we do NOT trade. The three sleeves we
        # actually trade are POSITIVELY correlated. Measured two independent ways on the same
        # window (1,061 days): +0.0724 via portfolio/book.py::combine_book (the live code path)
        # and +0.0723 via a weekday-intersection analysis. The published figure flattered us.
        "correlation_value": RHO_BAR,
        "correlation": (
            f"Measured {RHO_BAR:+.4f} average pairwise correlation across the {N_SLEEVES_WORD} "
            "live sleeves — POSITIVE. The prior three-sleeve book measured "
            f"{RHO_BAR_PRIOR_3_SLEEVE:+.4f}; AlphaVintage lowered it without improving any "
            "standalone edge claim. In risk-off the pairwise correlations can spike, so the "
            "diversification benefit may shrink exactly in the left tail. We size on the stressed "
            "matrix."
        ),
        "gauntlet_grade": "C+",
        "gauntlet_pass": (
            "real but modest; no sleeve clears the multiple-testing gate in-sample, so the only "
            "credible next evidence is a live record where the full book transacts through a "
            "risk-off episode"
        ),
        # BOOK-level live_days must track the BOOK (ALPHAC), not one sleeve. This read from
        # crypto_live, which was harmless while crypto was the reference sleeve but became wrong
        # once (a) ALPHAC was made the flagship on 2026-08-01 and (b) the crypto venue outages
        # started truncating that sleeve's curve. With crypto dark since 2026-08-03 the headline
        # read 35 days while ALPHAC, AlphaMax and AlphaTrend all read 37 — the book UNDERSTATED
        # its own live period because its least-available sleeve was standing in for it.
        # health_check.py's C4c-livedays caught exactly this. Per-sleeve live_days are unchanged
        # and still computed from each sleeve's OWN curve, so the crypto sleeve continues to
        # report its true 35 — which, next to cycle_uptime, is the honest picture.
        "live_days": live_days_elapsed(live["alphac"]),
    }

    state = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "go_live_date": GO_LIVE,
        "rebaseline": {
            "v1": {"go_live": V1_GO_LIVE, "ended": V1_ENDED,
                   "result": "flat, $0 realized ($100k -> $100k); crypto carry held cash, "
                             "equity/MF days-old at baseline",
                   "config": "market-neutral, net beta ~0, no strategic tilt"},
            "v2": {"go_live": V2_GO_LIVE, "ended": V2_ENDED,
                   "config": "3-sleeve market-neutral core (AlphaForge + AlphaMax + AlphaTrend, "
                             f"{WEIGHTS_PROSE}) + DISCLOSED +20% strategic net-long overlay "
                             "(0.5 BTC + 0.5 SPY), held as a separate labelled line",
                   "result": "39 days. AlphaMax $1,000,000 -> $932,338 on its own account; "
                             "AlphaTrend $100,000 -> $100,603. Both accounts still EXIST at the "
                             "broker (PA397834GG9R, PA3IQC5B7BC2) and remain independently "
                             "checkable; the full record is frozen read-only in artifacts/archive/."},
            "v3": {"go_live": V3_GO_LIVE,
                   "config": "every sleeve moved to its OWN fresh $1,000,000 Alpaca paper account "
                             "(AlphaMax PA3ECIF9O942, AlphaTrend PA31FJRJQK69, AlphaLedger "
                             "PA3DYIG9B4AL), so equal book weights are a real dollar allocation "
                             "rather than a reporting convention",
                   "why": "the v2 seeds were mismatched ($932k / $100k), which made the published "
                          "40/40/20 weights describe a dollar split that was really ~9:1, and "
                          "$100k is too small for a wide dollar-neutral book: whole-share "
                          "truncation on shorts cost AlphaMax 8.79% of its short notional and "
                          "pushed it +2.40% NET LONG. At $1M that is 0.37% and +0.10%."},
            "disclosure": "v1 (2026-06-21..06-29) ran flat at the $100k baseline and is SUPERSEDED, "
                          "NOT deleted: it remains in the signed transparency chain (seq 0..4, "
                          "Bitcoin-anchored). v2 (2026-06-29..08-07) ran 39 days and is likewise "
                          "superseded, not deleted: its accounts are still open at the broker and "
                          "its full record is frozen with a published manifest digest. v3 restarts "
                          "the forward record on 2026-08-07 on equal $1M accounts. Each re-baseline "
                          "RESETS the forward record rather than splicing it: v2's last mark and "
                          "v3's first mark are NOT one day's return, and reporting them as such "
                          "would have invented +7.26% for AlphaMax and +894% for AlphaTrend. "
                          "We re-baseline in the open; we never silently rewrite 'live since'.",
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
            # "three decorrelated sleeves" was removed 2026-08-07: their average pairwise
            # correlation measures +0.072, POSITIVE. They are near-uncorrelated, which is a real
            # and useful property, but "decorrelated" overstated it and the site had built its
            # headline claim on that word.
            # DERIVED, never typed — 2026-08-12. This string said "three near-uncorrelated sleeves
            # ... +0.072 ... +20% overlay" for a day after the book became FOUR sleeves at rho_bar
            # +0.0274 with a +10% overlay, because the sleeve count, the correlation and the tilt
            # were all hand-typed here while the values they described moved. Same defect class as
            # WEIGHTS_PROSE and N_SLEEVES exist to close; now every figure in it is interpolated.
            "style": f"Market-neutral core (equity momentum + crypto funding carry + managed-futures "
            f"trend + PIT macro surprise, {N_SLEEVES_WORD} near-uncorrelated sleeves at "
            f"{WEIGHTS_PROSE}, measured average pairwise correlation {RHO_BAR:+.4f}) PLUS a "
            f"disclosed {TILT_PROSE} strategic net-long overlay",
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
                # APPENDED 2026-08-12, and it should have been appended on 2026-08-10 when the
                # sleeve went live. It was added to `algorithms` but not here, so for two days the
                # published artifact said the book had FOUR algorithms in one field and THREE
                # sleeves in another — and anything reading book.sleeves (the transparency chain's
                # book_sleeves payload among them) saw a book that did not include a sleeve holding
                # $1M of live positions. Appended at the END to preserve composition order, per the
                # note above, so the signed chain sees an addition rather than a reshuffle.
                {"key": "alphavintage", "name": "AlphaVintage", "desc": ALGO_BY_KEY["alphavintage"]["desc"],
                 "standalone_sharpe": 0.34,
                 "weight": round(float(book.weights[VINTAGE_WF].mean()), 3)},
            ],
        },
        "research_curve": research["alphac"],
        "live_curve": live["alphac"],
    }
    # ---- PUBLISH GATE — the last thing between a computed number and a public page ----------
    # Every other guard in this repo protects an INPUT. Nothing protected the OUTPUT, so on
    # 2026-08-08 a database merge defect published a flagship curve reading 100,000 -> 400,207: a
    # 300% one-day gain on a market-neutral book, live for three days, caught only because a human
    # looked at a chart. Fixing that merge was necessary; it does not make the CLASS of failure
    # unpublishable. This does, for the arithmetic-impossibility half of it.
    #
    # FAILS CLOSED, and that trade is deliberate: this script runs hourly and unattended, so the
    # choice on a violation is between a stale site and a confidently wrong one. For a product
    # whose entire claim is a record a stranger can verify, stale is recoverable and wrong is not.
    # Exiting here also leaves the PREVIOUS good artifact in place rather than truncating it.
    gate = check_published_state(state)
    print(f"  {gate.summary()}")
    if not gate.ok:
        print("  REFUSING TO WRITE data/paper/state.json — the previous artifact stands.")
        print("  Investigate the curve above before republishing; do NOT loosen the bound to pass.")
        raise SystemExit(1)

    out = Path("data/paper/state.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(state, indent=2))
    print(f"wrote {out}  ({len(algorithms)} algorithms; in-sample SR {book.sharpe:.2f}; "
          f"crypto live pts {len(crypto_live)}, equity live pts {len(equity_live)})")
    # A curve that silently dropped days is exactly the thing that must be loud. A broker account
    # changed and the published record moved with it; if that was not intended, someone has to see
    # it on the run that did it, not discover it later from a chart that looks wrong.
    for msg in _LOG_ACCOUNT_SWITCH:
        print(f"  !! ACCOUNT SWITCH — {msg}")
    for app in (Path.home() / "meridian-app" / "public", Path.home() / "meridian" / "public"):
        if app.is_dir():
            (app / "paper-state.json").write_text(json.dumps(state, indent=2))
            print(f"copied to {app / 'paper-state.json'}")


if __name__ == "__main__":
    main()
