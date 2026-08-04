#!/usr/bin/env python3
"""PROBE — PRE-REGISTERED CEF DEEP-DISCOUNT SCREEN + FORWARD EXPERIMENT SPEC.

CANDIDATE 2. LOCKED 2026-07-19 BEFORE any signal, event-study or portfolio number
was computed on the collected data. (Structural checks only were run first: history
depth = ~4.7y weekly / 1y daily, currently-listed funds only, price not
distribution-adjusted — see scripts/collect_cef.py.)

=============================== WHAT IS TESTABLE TODAY ===============================
Free history = CEFConnect 5Y endpoint: ~243 weekly points (~2021-07..now) PER
CURRENTLY LISTED FUND. That makes any backtest here a SURVIVORSHIP-BIASED SCREEN:
funds that were tendered / open-ended / merged / liquidated since 2021 (often the
activist wins, sometimes the blow-ups) are absent, and the listed-universe-at-t is
not reconstructable. Per house rules this is a CHEAP SCREEN: it does NOT append to
var/experiments.jsonl (disclosed here and in the report; ledger N at spec time = 111).
Bias direction is genuinely two-sided (missing NAV-terminal wins understate the long
leg; missing liquidation losers overstate it), so the screen is a viability read,
NOT a bless-grade number. The bless-grade path is the FORWARD experiment (below).

================================ 1. DATA (LOCKED) ================================
- data/research/cef/history/{T}.json  weekly_5y: price, NAV, discount per fund.
  Points snapped to W-FRI (last obs per week). Joint price+NAV required.
- data/research/cef/snapshots/dailypricing_*.json (latest): universe, category,
  DistributionRatePrice (CURRENT rate — see distribution handling).
- data/research/cef/activist_13d/events.json: 13D/G subject events, 2001+.
- Hedge prices: data/lake_mf ohlcv_1d SPY + IEF (Yahoo TOTAL-RETURN adjusted per
  scripts/mf_etf_load.py docstring => hedge dividends are already in the price).
- UNIVERSE: all funds in the latest snapshot EXCEPT the four physical-commodity
  trusts (CEF, PHYS, PSLV, SPPP: redemption features, no activist path) and funds
  with fewer than 104 joint weekly obs. No other exclusions.

============================ 2. SIGNAL (LOCKED, FROM LITERATURE) =====================
At week t (W-FRI close), per fund i, using data <= t only:
  disc = 100*(P/NAV - 1)  (CEFConnect Discount field; negative = discount)
  z    = (disc_t - mean(disc, trailing 52w)) / std(disc, trailing 52w, ddof=0),
         requiring 52 obs (z-window per Thompson'78..Patro'17 replications; NOT tuned).
  ENTRY: z <= -1.0 AND disc <= -10.0        EXIT: z >= -0.25 OR disc >= -5.0
  Max 25 holdings (deepest z first when over). Equal weight, weekly rebalance.
Execution: signal at close t -> fill at NEXT weekly close (t+1) -> held weights are
target.shift(2) vs the close-to-close weekly return they earn. No same-bar fills.

========================== 3. HYPOTHESES + GATES (LOCKED) ============================
H1 (signal validity — DISTRIBUTION-CLEAN primary): entry-event funds narrow their
  discount vs the universe. Event = fund enters the signal set at t (not in at t-1).
  Effect_h = mean over events of [ (disc_{t+h} - disc_t) - median_universe(disc_{t+h} - disc_t) ]
  for h in {4, 13, 26} weeks (universe = funds with valid z at t, not in signal set).
  t-stat: collapse events to per-week cohort means, then HAC (Newey-West, lag = h)
  on the cohort series.  GATE: h=13 effect >= +1.0 discount point with |t| >= 2.
H2 (economic viability net of COMMITTED costs): hedged weekly portfolio
  long  = signal set, EW, gross 1.0
  hedge = short 0.5*SPY + 0.5*IEF, dollar-matched to long gross (beta assumed 1.0)
  costs = CEF leg 41bp ONE-WAY (6bp house commission-equivalent + 35bp half-spread,
          median CEF spread ~0.7%) on CEF turnover; ETF leg 6bp one-way on hedge
          turnover; 50bp/yr borrow on hedge gross (house committed borrow).
  distributions: CEF price history is price-only while CEFs pay ~7-8%/yr. PRIMARY
          variant accrues DistributionRatePrice/52 per held week (CURRENT snapshot
          rate — NOT PIT, disclosed approximation). SENSITIVITY variant = price-only
          (understates the long leg). BOTH reported.
  GATE: PRIMARY net Sharpe >= 0.5 (weekly x sqrt(52), blessed summarize on the
  weekly epoch-ms equity curve). If PRIMARY passes but PRICE-ONLY nets < 0, verdict
  degrades to AMBIGUOUS (the edge would live inside a non-PIT accrual assumption).
H3 (descriptive only, NO gate): share of held fund-weeks with an ACTIVE activist
  13D (whitelisted activist filed 13D/13D-A on the fund <= t and within 24 months);
  plus today's actionable watchlist (entry-signal AND active 13D).
VERDICT: PASS = H1 gate AND H2 gate. Anything else = NULL / AMBIGUOUS-NULL — park
the backtest, keep the forward collection. An honest NULL is a full success.
DSR: reported INFORMATIONALLY (fresh-trial n=2 convention AND at ledger N=111,
periods_per_year=52). NO ledger append (screen-grade data).

===================== 4. PRE-REGISTERED FORWARD EXPERIMENT (THE REAL TEST) ===========
Because the free backtest cannot be survivorship-clean, the decision-grade evidence
is FORWARD: run scripts/collect_cef.py daily (snapshot+edgar). That accrues a PIT
discount + catalyst tape including future delistings (terminal events land IN the
tape). Rules identical to sections 1-3 frozen as of the collection start date
(2026-07-19), evaluated on forward data only:
  - paper portfolio per section 2/H2 (weekly, W-FRI, same costs), and
  - H1 event study forward.
  EVALUATION GATE (single look, ~2027-07-19, >=48 forward weekly obs): forward
  PRIMARY net Sharpe > 0 AND forward h=13 H1 effect > 0. Passing THAT is what earns
  a var/experiments.jsonl append (one trial, spec hash below) and promotion
  consideration; failing appends the NULL the same way.
The spec dict + sha256 is written to data/research/cef/FORWARD_SPEC.json and
artifacts/sweep/cef_probe/FORWARD_SPEC.json at every run of this probe; the hash is
printed so any later tampering with the frozen rules is detectable.

Usage:  uv run python scripts/probe_cef_discount.py
Artifacts -> artifacts/sweep/cef_probe/
"""
# ruff: noqa: E501
from __future__ import annotations

import datetime as dt
import glob
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

CEF_DIR = _ROOT / "data" / "research" / "cef"
LAKE_MF = _ROOT / "data" / "lake_mf"
OUT = _ROOT / "artifacts" / "sweep" / "cef_probe"
OUT.mkdir(parents=True, exist_ok=True)

# ------------------------------ LOCKED SPEC CONSTANTS ------------------------------
EXCLUDE_PHYSICAL = {"CEF", "PHYS", "PSLV", "SPPP"}
MIN_WEEKLY_OBS = 104
Z_WINDOW = 52
ENTRY_Z, ENTRY_DISC = -1.0, -10.0
EXIT_Z, EXIT_DISC = -0.25, -5.0
MAX_HOLDINGS = 25
CEF_ONE_WAY = 0.0041          # 6bp + 35bp half-spread
ETF_ONE_WAY = 0.0006
BORROW_ANN = 0.0050
HEDGE = {"SPY": 0.5, "IEF": 0.5}
H1_HORIZONS = (4, 13, 26)
H1_GATE_H, H1_GATE_EFFECT, H1_GATE_T = 13, 1.0, 2.0
H2_GATE_SHARPE = 0.5
ACTIVIST_STALE_WEEKS = 104    # 24 months
WEEKS_PER_YEAR = 52.0
LEDGER_N_AT_SPEC = 111        # var/experiments.jsonl distinct trials at spec time

SPEC = {
    "name": "cef_deep_discount_candidate2",
    "locked": "2026-07-19",
    "universe": "CEFConnect DailyPricing minus physical trusts, >=104 joint weekly obs",
    "signal": {"z_window_w": Z_WINDOW, "entry": {"z": ENTRY_Z, "disc": ENTRY_DISC},
               "exit": {"z": EXIT_Z, "disc": EXIT_DISC}, "max_holdings": MAX_HOLDINGS,
               "weighting": "equal", "rebalance": "W-FRI", "fill": "next weekly close (shift 2 vs c2c return)"},
    "hedge": {"legs": HEDGE, "dollar_matched": True, "beta_assumed": 1.0},
    "costs": {"cef_one_way": CEF_ONE_WAY, "etf_one_way": ETF_ONE_WAY, "borrow_ann_on_hedge": BORROW_ANN},
    "distributions": "PRIMARY accrues current DistributionRatePrice/52 (non-PIT, disclosed); sensitivity = price-only",
    "h1": {"horizons_w": list(H1_HORIZONS), "gate": {"h": H1_GATE_H, "effect_pts": H1_GATE_EFFECT, "t": H1_GATE_T}},
    "h2": {"gate_net_sharpe": H2_GATE_SHARPE},
    "forward": {"start": "2026-07-19", "eval": "~2027-07-19, >=48 weekly obs, single look",
                "gate": "fwd PRIMARY net Sharpe > 0 AND fwd h13 H1 effect > 0",
                "ledger": "append exactly one trial at forward evaluation, pass or fail"},
    "no_ledger_append_today": "backtest is survivorship-biased screen-grade (disclosed)",
}
SPEC_HASH = hashlib.sha256(json.dumps(SPEC, sort_keys=True).encode()).hexdigest()

_STOPWORDS = {"FUND", "TRUST", "INC", "THE", "CO", "CORP", "LTD", "LP", "LLC", "OF", "FOR", "&", "AND"}


def _norm_name(s: str) -> str:
    s = re.sub(r"\(.*?\)", " ", s.upper())
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return " ".join(w for w in s.split() if w not in _STOPWORDS)


# --------------------------------- data loading ---------------------------------

def load_snapshot() -> pd.DataFrame:
    paths = sorted(glob.glob(str(CEF_DIR / "snapshots" / "dailypricing_*.json")))
    if not paths:
        raise SystemExit("BLOCKER: no snapshot. Run scripts/collect_cef.py first.")
    funds = json.loads(Path(paths[-1]).read_text())["funds"]
    df = pd.DataFrame(funds).set_index("Ticker")
    print(f"[data] snapshot {Path(paths[-1]).name}: {len(df)} funds")
    return df


def load_weekly_panels() -> tuple[pd.DataFrame, pd.DataFrame]:
    """(disc, px) weekly W-FRI panels from history/*.json weekly_5y."""
    disc_cols: dict[str, pd.Series] = {}
    px_cols: dict[str, pd.Series] = {}
    files = sorted(glob.glob(str(CEF_DIR / "history" / "*.json")))
    if not files:
        raise SystemExit("BLOCKER: no history. Run scripts/collect_cef.py --parts history.")
    for f in files:
        rec = json.loads(Path(f).read_text())
        t = rec["ticker"]
        rows = rec.get("weekly_5y") or []
        if not rows:
            continue
        d = pd.DataFrame(rows)
        d["dt"] = pd.to_datetime(d["DataDate"]).dt.normalize()
        d = d.dropna(subset=["NAVData", "Data"])
        d = d[(d["NAVData"] > 0) & (d["Data"] > 0)]
        if d.empty:
            continue
        wk = d["dt"].dt.to_period("W-FRI").dt.end_time.dt.normalize()  # snap to that week's Friday
        d = d.assign(wk=wk).groupby("wk").last()
        disc_cols[t] = 100.0 * (d["Data"] / d["NAVData"] - 1.0)
        px_cols[t] = d["Data"]
    disc = pd.DataFrame(disc_cols).sort_index()
    px = pd.DataFrame(px_cols).sort_index()
    print(f"[data] weekly panels: {disc.shape[1]} funds x {disc.shape[0]} weeks ({disc.index.min().date()}..{disc.index.max().date()})")
    return disc, px


def load_hedge_weekly(index: pd.DatetimeIndex) -> pd.DataFrame:
    out = {}
    for tick in HEDGE:
        pat = str(LAKE_MF / "ohlcv_1d" / f"instrument_id=XUSE:CASH:{tick}USD" / "**" / "*.parquet")
        fs = glob.glob(pat, recursive=True)
        if not fs:
            raise SystemExit(f"BLOCKER: no lake_mf data for {tick}")
        df = pd.concat([pd.read_parquet(p) for p in fs])
        ts_raw = df["ts_open"]
        ts = (pd.to_datetime(ts_raw, unit="ms", utc=True) if pd.api.types.is_integer_dtype(ts_raw)
              else pd.to_datetime(ts_raw, utc=True)).dt.tz_localize(None)
        s = pd.Series(df["close"].to_numpy(float), index=ts).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        out[tick] = s.resample("W-FRI").last()
    h = pd.DataFrame(out).reindex(index).ffill(limit=1)
    return h


def load_activist_events() -> pd.DataFrame:
    p = CEF_DIR / "activist_13d" / "events.json"
    if not p.exists():
        print("[data] WARNING: no activist events (run collect_cef.py --parts edgar); H3 skipped")
        return pd.DataFrame(columns=["activist", "subject_ticker", "subject_display", "form", "file_date"])
    ev = pd.DataFrame(json.loads(p.read_text())["events"])
    ev = ev[ev["form"].astype(str).str.contains("13D", na=False)]  # catalyst = 13D only (13G = passive)
    ev["file_date"] = pd.to_datetime(ev["file_date"])
    print(f"[data] activist 13D events: {len(ev)}")
    return ev


def map_events_to_tickers(ev: pd.DataFrame, snap: pd.DataFrame) -> pd.DataFrame:
    """Resolve subject -> CEFConnect ticker: direct token, else normalized-name match."""
    if ev.empty:
        return ev.assign(ticker=pd.Series(dtype=str))
    known = set(snap.index)
    name_map = {_norm_name(n): t for t, n in snap["Name"].astype(str).items()}
    tickers = []
    for _, r in ev.iterrows():
        tk = r.get("subject_ticker")
        if isinstance(tk, str) and tk in known:
            tickers.append(tk)
            continue
        nm = _norm_name(str(r.get("subject_display") or ""))
        hit = name_map.get(nm)
        if hit is None:
            hit = next((t for k, t in name_map.items() if k and (k in nm or nm in k)), None)
        tickers.append(hit)
    ev = ev.assign(ticker=tickers)
    n_ok = ev["ticker"].notna().sum()
    print(f"[data] 13D events mapped to listed tickers: {n_ok}/{len(ev)} (unmatched = delisted/non-CEF subjects; flagged)")
    return ev


# --------------------------------- signal engine ---------------------------------

def build_signal(disc: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    mu = disc.rolling(Z_WINDOW, min_periods=Z_WINDOW).mean()
    sd = disc.rolling(Z_WINDOW, min_periods=Z_WINDOW).std(ddof=0)
    z = (disc - mu) / sd.replace(0.0, np.nan)
    member = pd.DataFrame(False, index=disc.index, columns=disc.columns)
    held: set[str] = set()
    for t in disc.index:
        zrow, drow = z.loc[t], disc.loc[t]
        held = {c for c in held if not (pd.isna(zrow[c]) or pd.isna(drow[c])
                                        or zrow[c] >= EXIT_Z or drow[c] >= EXIT_DISC)}
        cand = [c for c in disc.columns if c not in held
                and pd.notna(zrow[c]) and pd.notna(drow[c])
                and zrow[c] <= ENTRY_Z and drow[c] <= ENTRY_DISC]
        cand.sort(key=lambda c: zrow[c])
        for c in cand:
            if len(held) >= MAX_HOLDINGS:
                break
            held.add(c)
        member.loc[t, list(held)] = True
    return member, z


def run_backtest(member: pd.DataFrame, px: pd.DataFrame, hedge_px: pd.DataFrame,
                 dist_rate: pd.Series, accrue: bool) -> pd.DataFrame:
    """Weekly hedged net returns. Held weights = target.shift(2) (no same-bar fill)."""
    ret = px.pct_change()
    ret = ret.where(ret.abs() < 0.60)  # data-error guard (weekly move >60% = bad print), disclosed
    if accrue:
        acc = (dist_rate.reindex(px.columns).fillna(0.0) / 100.0 / WEEKS_PER_YEAR)
        ret = ret.add(acc, axis=1)
    hret = hedge_px.pct_change()
    target = member.div(member.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    eff = target.shift(2).fillna(0.0)
    rows = []
    prev_w = pd.Series(0.0, index=px.columns)
    prev_hg = 0.0
    for t in px.index:
        w = eff.loc[t]
        r = ret.loc[t].fillna(0.0)
        long_ret = float((w * r).sum())
        gross_long = float(w.sum())
        hr = hret.loc[t] if t in hret.index else pd.Series(dtype=float)
        hedge_ret = -gross_long * float(sum(HEDGE[k] * hr.get(k, 0.0) if pd.notna(hr.get(k, np.nan)) else 0.0 for k in HEDGE))
        port_gross = long_ret + hedge_ret
        drift = prev_w * (1.0 + ret.loc[t].fillna(0.0))
        drift = drift / drift.sum() * prev_w.sum() if prev_w.sum() > 0 and drift.sum() > 0 else prev_w
        cef_turn = float((w - drift).abs().sum())
        hedge_turn = abs(gross_long - prev_hg)
        cost = cef_turn * CEF_ONE_WAY + hedge_turn * ETF_ONE_WAY + gross_long * BORROW_ANN / WEEKS_PER_YEAR
        rows.append({"ts": t, "long_ret": long_ret, "hedge_ret": hedge_ret,
                     "gross": port_gross, "cost": cost, "net": port_gross - cost,
                     "net_long_only": long_ret - cef_turn * CEF_ONE_WAY,
                     "n_held": int((w > 0).sum()), "turnover_cef": cef_turn})
        prev_w, prev_hg = w, gross_long
    return pd.DataFrame(rows).set_index("ts")


# --------------------------------- H1 event study ---------------------------------

def event_study(member: pd.DataFrame, disc: pd.DataFrame, z: pd.DataFrame) -> dict:
    entries = member & ~member.shift(1, fill_value=False)
    out = {}
    for h in H1_HORIZONS:
        fwd = disc.shift(-h) - disc
        cohort = []
        for t in disc.index:
            evs = entries.loc[t]
            names = list(evs[evs].index)
            if not names:
                continue
            valid = z.loc[t].notna() & ~member.loc[t]
            ctrl = fwd.loc[t, valid[valid].index].median()
            vals = fwd.loc[t, names].dropna()
            if len(vals) == 0 or pd.isna(ctrl):
                continue
            cohort.append({"t": t, "mean_excess": float((vals - ctrl).mean()), "n": len(vals)})
        cs = pd.DataFrame(cohort).set_index("t") if cohort else pd.DataFrame()
        if cs.empty:
            out[h] = {"effect_pts": None, "t_stat": None, "n_events": 0, "n_cohorts": 0}
            continue
        x = cs["mean_excess"].to_numpy(float)
        eff = float(x.mean())
        # HAC (Newey-West, lag = h) on the cohort series
        n = len(x)
        xc = x - eff
        g0 = float((xc @ xc) / n)
        var = g0
        for lag in range(1, min(h, n - 1) + 1):
            wgt = 1.0 - lag / (h + 1.0)
            var += 2.0 * wgt * float((xc[:-lag] @ xc[lag:]) / n)
        se = np.sqrt(max(var, 1e-12) / n)
        out[h] = {"effect_pts": round(eff, 3), "t_stat": round(eff / se, 2),
                  "n_events": int(cs["n"].sum()), "n_cohorts": n}
    return out


# ------------------------------------- main --------------------------------------

def main() -> int:
    from alphaforge.analytics.metrics import summarize
    from alphaforge.validation.dsr import dsr_from_returns

    print(f"SPEC sha256 = {SPEC_HASH}")
    snap = load_snapshot()
    disc, px = load_weekly_panels()

    # locked universe filter
    keep = [c for c in disc.columns
            if c not in EXCLUDE_PHYSICAL and disc[c].notna().sum() >= MIN_WEEKLY_OBS]
    disc, px = disc[keep], px[keep]
    print(f"[universe] {len(keep)} funds after exclusions (physical trusts + <{MIN_WEEKLY_OBS} obs)")

    member, z = build_signal(disc)
    n_sig = member.sum(axis=1)
    print(f"[signal] holdings/week: mean={n_sig.mean():.1f} max={int(n_sig.max())} weeks_with_any={(n_sig > 0).sum()}/{len(n_sig)}")

    # ---- H1 (distribution-clean) ----
    h1 = event_study(member, disc, z)
    g = h1.get(H1_GATE_H, {})
    h1_pass = (g.get("effect_pts") is not None and g["effect_pts"] >= H1_GATE_EFFECT
               and g.get("t_stat") is not None and abs(g["t_stat"]) >= H1_GATE_T)

    # ---- H2 ----
    hedge_px = load_hedge_weekly(px.index)
    dist_col = snap["DistributionRatePrice"] if "DistributionRatePrice" in snap.columns else pd.Series(dtype=float)
    dist_rate = pd.to_numeric(dist_col, errors="coerce")
    bt_primary = run_backtest(member, px, hedge_px, dist_rate, accrue=True)
    bt_price = run_backtest(member, px, hedge_px, dist_rate, accrue=False)

    def perf(bt: pd.DataFrame) -> dict:
        held_any = bt["n_held"] > 0
        start = held_any.idxmax() if held_any.any() else bt.index[0]
        active = bt["net"].loc[start:]  # trim mechanical z-warm-up; mid-sample flat weeks stay
        eq = (1.0 + active).cumprod() * 50_000.0
        ms_idx = (pd.DatetimeIndex(eq.index).tz_localize("UTC") - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)
        s = summarize(pd.Series(eq.to_numpy(), index=ms_idx))
        wk = active.to_numpy(float)
        sr_w = wk.mean() / wk.std(ddof=1) if wk.std(ddof=1) > 0 else float("nan")
        return {"summ": s, "net": active, "sharpe_weekly_ann": float(sr_w * np.sqrt(WEEKS_PER_YEAR))}

    p_pri, p_px = perf(bt_primary), perf(bt_price)
    h2_pass = p_pri["sharpe_weekly_ann"] >= H2_GATE_SHARPE
    ambiguous = h2_pass and p_px["sharpe_weekly_ann"] < 0.0

    dsr_fresh = dsr_from_returns(p_pri["net"], 2, 1.0, WEEKS_PER_YEAR)
    dsr_ledger = dsr_from_returns(p_pri["net"], LEDGER_N_AT_SPEC, 1.0, WEEKS_PER_YEAR)

    # ---- H3 descriptive ----
    ev = map_events_to_tickers(load_activist_events(), snap)
    h3: dict = {"note": "descriptive only, no gate"}
    watchlist: list[dict] = []
    if not ev.empty:
        ev_ok = ev.dropna(subset=["ticker"])
        ev_ok = ev_ok[ev_ok["ticker"].isin(disc.columns)]
        last_13d: dict[str, pd.Timestamp] = ev_ok.groupby("ticker")["file_date"].max().to_dict()
        # active-13D coverage of held fund-weeks
        held_weeks = 0
        cat_weeks = 0
        for t in member.index:
            names = member.loc[t]
            for c in names[names].index:
                held_weeks += 1
                by_fund = ev_ok[ev_ok["ticker"] == c]["file_date"]
                if ((by_fund <= t) & (by_fund >= t - pd.Timedelta(weeks=ACTIVIST_STALE_WEEKS))).any():
                    cat_weeks += 1
        h3["held_fund_weeks"] = held_weeks
        h3["with_active_13d"] = cat_weeks
        h3["coverage"] = round(cat_weeks / held_weeks, 3) if held_weeks else None
        # today's watchlist
        t_last = disc.index[-1]
        for c in disc.columns:
            zc, dc = z.loc[t_last, c], disc.loc[t_last, c]
            if pd.isna(zc) or pd.isna(dc) or not (zc <= ENTRY_Z and dc <= ENTRY_DISC):
                continue
            lf = last_13d.get(c)
            active = bool(lf is not None and lf >= t_last - pd.Timedelta(weeks=ACTIVIST_STALE_WEEKS))
            watchlist.append({"ticker": c, "discount_pct": round(float(dc), 2), "z": round(float(zc), 2),
                              "active_13d": active,
                              "last_13d": str(lf.date()) if lf is not None else None,
                              "name": str(snap["Name"].get(c, ""))})
        watchlist.sort(key=lambda r: r["z"])

    verdict = "PASS" if (h1_pass and h2_pass and not ambiguous) else ("AMBIGUOUS-NULL" if (h1_pass and h2_pass and ambiguous) else "NULL")

    result = {
        "candidate": "CEF deep-discount satellite (Candidate 2)",
        "spec_sha256": SPEC_HASH,
        "grade": "SCREEN (survivorship-biased free history; NOT bless-grade; NO ledger append — disclosed)",
        "window": f"{disc.index.min().date()}..{disc.index.max().date()} (weekly, {len(disc)} weeks)",
        "universe_funds": len(keep),
        "h1_event_study_discount_pts_vs_universe": h1,
        "h1_gate": {"h": H1_GATE_H, "need_effect": H1_GATE_EFFECT, "need_t": H1_GATE_T, "pass": bool(h1_pass)},
        "h2_primary_with_dist_accrual": {
            "net_sharpe_weekly_ann": round(p_pri["sharpe_weekly_ann"], 3),
            "blessed_summarize_sharpe": round(float(p_pri["summ"].sharpe), 3),
            "ann_vol": round(float(p_pri["summ"].vol_ann), 3),
            "max_dd": round(float(p_pri["summ"].max_dd), 3),
            "cagr": round(float(p_pri["summ"].cagr), 3),
        },
        "h2_sensitivity_price_only": {"net_sharpe_weekly_ann": round(p_px["sharpe_weekly_ann"], 3)},
        "h2_gate": {"need": H2_GATE_SHARPE, "pass": bool(h2_pass), "ambiguous_dist_dependence": bool(ambiguous)},
        "dsr_informational": {"fresh_trial": round(float(dsr_fresh.dsr), 3),
                              "at_ledger_n111": round(float(dsr_ledger.dsr), 3),
                              "psr": round(float(dsr_fresh.psr), 3)},
        "avg_holdings": round(float(n_sig.mean()), 1),
        "avg_weekly_cef_turnover": round(float(bt_primary["turnover_cef"].mean()), 4),
        "h3_activist_overlap": h3,
        "watchlist_today_n": len(watchlist),
        "verdict": verdict,
        "forward_experiment": SPEC["forward"],
        "caveats": [
            "survivorship: currently-listed funds only (two-sided bias, disclosed)",
            "distribution accrual uses CURRENT rates (non-PIT approximation)",
            "5Y weekly series is vendor-downsampled; hedge beta assumed 1.0",
            ">60% weekly-move prints treated as data errors (excluded)",
        ],
    }

    (OUT / "result.json").write_text(json.dumps(result, indent=2))
    (OUT / "watchlist_today.json").write_text(json.dumps({"asof": str(disc.index[-1].date()), "watchlist": watchlist}, indent=2))
    bt_primary.to_parquet(OUT / "weekly_curve_primary.parquet")
    bt_price.to_parquet(OUT / "weekly_curve_price_only.parquet")
    fwd = {"spec": SPEC, "spec_sha256": SPEC_HASH, "written_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
    (OUT / "FORWARD_SPEC.json").write_text(json.dumps(fwd, indent=2))
    (CEF_DIR / "FORWARD_SPEC.json").write_text(json.dumps(fwd, indent=2))

    print("\n================= CEF DEEP-DISCOUNT — PRE-REGISTERED SCREEN =================")
    for k, v in result.items():
        print(f"  {k}: {v}")
    print(f"  watchlist (top 10 of {len(watchlist)}):")
    for r in watchlist[:10]:
        print(f"    {r['ticker']:6s} disc={r['discount_pct']:7.2f}%  z={r['z']:6.2f}  13D={'YES ' + str(r['last_13d']) if r['active_13d'] else 'no'}  {r['name'][:38]}")
    print("  artifacts:", OUT)
    print("  LEDGER: no append (screen-grade). Forward evaluation appends one trial either way.")
    print("=============================================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
