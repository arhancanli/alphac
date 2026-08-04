#!/usr/bin/env python3
"""PROBE — TRACK B / STEP 2: LETF end-of-day forced-rebalance flow study (research screen).

=============================== PRE-REGISTration ================================
Written BEFORE any outcome statistic was computed (2026-07-12). Research-only,
ledger-free event/IC screen per the zoo_screen protocol: NO walk-forward gauntlet
run, NO append to var/experiments.jsonl (disclosed in the report).

MECHANISM. Daily-reset leveraged/inverse ETFs must trade in the direction of the
day's underlying move near the close to reset leverage. Dollar rebalance demand
for one fund = AUM * (L^2 - L) * r_day (positive coefficient for BOTH long and
inverse funds). Families studied (14 funds, free SEC N-PORT AUM, quarterly filed
anchors, NAV-propagated daily):

    QQQ : TQQQ(+3) SQQQ(-3)                       SOXX*: SOXL(+3) SOXS(-3)
    SPY : UPRO(+3) SPXU(-3) SPXL(+3) SPXS(-3)     IWM : TNA(+3) TZA(-3)
    TLT : TMF(+3) TMV(-3)                         XLF : FAS(+3) FAZ(-3)

  *Semis leg measured PRIMARILY on SMH bars (IEX coverage), SOXX as robustness;
   SOXL/SOXS actually track the ICE Semiconductor index — both ETFs are proxies.

SIGNAL (knowable ~15:30 ET). r_1530(t) = (P_15:30 + div_exdate)/P_prevclose - 1
using IEX bars (signal bar = last 1-min bar starting in [15:25,15:29], its close;
prev close = last bar <= 15:59 of t-1, its close). FLOW$(t) = r_1530(t) * M_f(t),
M_f(t) = sum_i (L_i^2-L_i) * AUM_i(t-1). flow_z = FLOW$ / trailing-252d std of
FLOW$ (shifted; min 120 obs) — strictly PIT.

PRE-REGISTERED QUESTIONS
(a) CONTINUATION into the close: does FLOW predict r_last30 = close(15:59-bar)/
    P_15:30 - 1?  Tests: per-family OLS slope (bps per 1 sigma flow) with
    Newey-West(5) t; pooled panel with day-clustered SE; decile table of
    r_last30 by flow_z; and the MECHANISM discriminator — interaction
    r_last30 ~ b*r_1530 + c*(r_1530 x m_z) with m_z = within-family standardized
    log multiplier M_f: c>0 says continuation scales with the LETF book (flow),
    not just plain intraday momentum (b).
(b) OVERNIGHT: same regressions for r_on = (next 09:30 open + div)/close - 1 and
    r_cc = (next close + div)/close - 1. Literature expectation: REVERSAL
    (negative slope) as the forced flow's price pressure decays.
(c) TRADEABLE SPEC net of the committed ETF schedule (configs/managed_futures.yaml:
    1bp commission + 3bp half-spread + 2bp latency = 6bp one-way; borrow 50bp/yr
    on short overnight legs)?  PRIMARY (pre-registered): trigger when |flow_z| >=
    trailing-252d 90th percentile of |flow_z| (shifted, PIT, min 120 obs);
      - intraday continuation leg: enter sign(flow) at the OPEN of the first bar
        starting in [15:31,15:35] (>=60s after the signal is knowable; no same-bar
        fill), exit at the last bar <=15:59 close (MOC proxy); costs 2 x 6bp.
      - overnight reversal leg: enter -sign(flow) at the 15:59-bar close (MOC
        proxy), exit next day at the first [09:30,09:34] bar open (opening-auction
        proxy); costs 2 x 6bp + borrow on shorts; dividends credited/debited.
    Portfolio = equal weight across families triggered that day. Robustness grid
    DISCLOSED as a screen (not deployment tuning): threshold in {80th, 90th, 95th}.
    Equity curves + per-calendar-year table across the 2020H2/2021/2022/2023/2024/
    2025/2026H1 regimes. NOTE: 2018 is NOT answerable locally — the free IEX lake
    starts 2020-07-27 (step-1 finding); stated in the verdict, resolvable only via
    QC cloud or the paid Databento slice.

HONESTY GUARDS (pre-registered):
  - IEX noise floor: step-1 measured ~0.5-1.2bp median daily-return tracking error
    (max ~3bp). If conditional last-30-min effects are < ~2bp the study is
    UNDERPOWERED on free data and says so.
  - AUM error bars: quarterly N-PORT anchors are exact (filed); within-quarter
    daily values are NAV-factor + geometric-flow interpolation. The alternative
    flow-based monthly reconstruction disagrees by an amount reported as the AUM
    error bar (it produces impossible negative AUM for high-churn inverse funds —
    which is why anchors+interpolation is primary). STRICT filing-lag PIT AUM
    (60-day lag, forward NAV propagation only) is run as robustness for (a); live
    traders read same-day AUM off issuer pages (real-time public, archive-missing),
    so best-estimate interpolation is the closest reconstruction of what was
    actually knowable — but the tradeable spec (c) uses STRICT PIT AUM only.
  - Days lacking a [15:25,15:29] signal bar, a [15:31,15:35] fill bar, a
    [15:55,15:59] close bar, or (for overnight) a next-day [09:30,09:34] bar are
    dropped (kills early closes and thin-coverage IEX days); per-family valid-day
    counts reported.
  - Dividends: Alpaca corporate-actions API ex-dates/rates; ETF's own ex-date
    distribution added back to returns (the LETF levers the INDEX, which does not
    drop on the tracking ETF's ex-date).
==================================================================================

Inputs (all pre-existing/new sanctioned paths):
    data/research/intraday_probe/lake/alpaca_1min_full/{SYM}_{YYYY}.parquet
    data/research/intraday_probe/letf/nport_aum/letf_monthly_aum.parquet

Outputs:
    data/research/intraday_probe/letf/flow_panel.parquet
    data/research/intraday_probe/letf/dividends_alpaca.parquet   (cache)
    data/research/intraday_probe/letf/letf_flow_results.json
    data/research/intraday_probe/letf/strategy_equity_{spec}.parquet

Usage:  uv run python scripts/probe_letf_flow.py
"""
# ruff: noqa: E501
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
sys.path.insert(0, str(_ROOT / "scripts"))

LAKE = _ROOT / "data" / "research" / "intraday_probe" / "lake" / "alpaca_1min_full"
AUM_PQ = _ROOT / "data" / "research" / "intraday_probe" / "letf" / "nport_aum" / "letf_monthly_aum.parquet"
OUT = _ROOT / "data" / "research" / "intraday_probe" / "letf"
OUT.mkdir(parents=True, exist_ok=True)

# committed ETF frictions (configs/managed_futures.yaml)
ONE_WAY_BPS = 1.0 + 3.0 + 2.0          # commission + half_spread + latency = 6bp
BORROW_BPS_ANNUAL = 50.0
INIT_CASH = 50_000.0

FAMILIES = {  # family -> (primary bar symbol, [(ticker, L), ...])
    "QQQ": ("QQQ", [("TQQQ", 3), ("SQQQ", -3)]),
    "SPY": ("SPY", [("UPRO", 3), ("SPXU", -3), ("SPXL", 3), ("SPXS", -3)]),
    "SOXX": ("SMH", [("SOXL", 3), ("SOXS", -3)]),   # SMH primary bars, SOXX robustness
    "IWM": ("IWM", [("TNA", 3), ("TZA", -3)]),
    "TLT": ("TLT", [("TMF", 3), ("TMV", -3)]),
    "XLF": ("XLF", [("FAS", 3), ("FAZ", -3)]),
}
BAR_SYMBOLS = ["SPY", "QQQ", "IWM", "SOXX", "SMH", "TLT", "XLF"]
Y0, Y1 = 2020, 2026


# ----------------------------------------------------------------- minute lake --
def load_daily_frame(sym: str) -> pd.DataFrame:
    """Per-day anchor prices from the IEX 1-min lake (ET session, label=bar start)."""
    parts = []
    for y in range(Y0, Y1 + 1):
        f = LAKE / f"{sym}_{y}.parquet"
        if f.exists():
            parts.append(pd.read_parquet(f, columns=["t", "open", "close", "volume"]))
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts, ignore_index=True)
    et = df["t"].dt.tz_convert("America/New_York")
    df = df.assign(day=et.dt.normalize().dt.tz_localize(None), hm=et.dt.hour * 60 + et.dt.minute)
    df = df[(df["hm"] >= 570) & (df["hm"] < 960)]

    def _agg(g: pd.DataFrame) -> pd.Series:
        sig = g[(g["hm"] >= 925) & (g["hm"] <= 929)]
        fill = g[(g["hm"] >= 931) & (g["hm"] <= 935)]
        clo = g[(g["hm"] >= 955) & (g["hm"] <= 959)]
        opn = g[(g["hm"] >= 570) & (g["hm"] <= 574)]
        l30 = g[g["hm"] >= 930]
        return pd.Series({
            "sig_px": sig["close"].iloc[-1] if len(sig) else np.nan,
            "fill_px": fill["open"].iloc[0] if len(fill) else np.nan,
            "close_px": clo["close"].iloc[-1] if len(clo) else np.nan,
            "open_px": opn["open"].iloc[0] if len(opn) else np.nan,
            "dvol_l30": float((l30["close"] * l30["volume"]).sum()),
            "n_bars": len(g),
        })

    out = df.groupby("day").apply(_agg, include_groups=False)
    out.index = pd.DatetimeIndex(out.index)
    return out.sort_index()


# ------------------------------------------------------------------- dividends --
def load_dividends() -> pd.DataFrame:
    cache = OUT / "dividends_alpaca.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    import httpx
    from probe_intraday_alpaca import HEADERS  # tested key loader from step 1
    rows = []
    with httpx.Client(timeout=30) as cli:
        for sym in BAR_SYMBOLS:
            token = None
            while True:
                params = {"symbols": sym, "types": "cash_dividend",
                          "start": "2020-01-01", "end": "2026-12-31", "limit": 1000}
                if token:
                    params["page_token"] = token
                r = cli.get("https://data.alpaca.markets/v1beta1/corporate-actions",
                            params=params, headers=HEADERS)
                if r.status_code == 429:
                    time.sleep(5)
                    continue
                r.raise_for_status()
                js = r.json()
                for d in (js.get("corporate_actions") or {}).get("cash_dividends", []):
                    rows.append({"symbol": sym, "ex_date": d["ex_date"], "rate": float(d["rate"])})
                token = js.get("next_page_token")
                if not token:
                    break
    df = pd.DataFrame(rows)
    df["ex_date"] = pd.to_datetime(df["ex_date"])
    df = df.groupby(["symbol", "ex_date"], as_index=False)["rate"].sum()
    df.to_parquet(cache, index=False)
    return df


# ------------------------------------------------------------------------- AUM --
def build_daily_aum(frames: dict[str, pd.DataFrame], divs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Daily AUM per LETF on the master grid: best-estimate + strict-PIT variants."""
    aum = pd.read_parquet(AUM_PQ)
    filed = aum[aum["method"] == "filed"].copy()
    recon = aum[aum["method"] == "reconstructed"].copy()
    grid = frames["SPY"].index  # master calendar

    # total-return daily series per bar symbol (div added on the ETF's own ex-date)
    tr = {}
    for sym, fr in frames.items():
        px = fr["close_px"].reindex(grid)
        dv = divs[divs["symbol"] == sym].set_index("ex_date")["rate"].reindex(grid).fillna(0.0)
        tr[sym] = ((px + dv) / px.shift(1) - 1.0).fillna(0.0)

    best, strict = {}, {}
    interp_vs_recon = []
    fam_of = {t: f for f, (_, ts) in FAMILIES.items() for t, _ in ts}
    sym_of_fam = {f: s for f, (s, _) in FAMILIES.items()}
    for tick, g in filed.groupby("ticker"):
        fam = fam_of[tick]
        L = int(g["leverage"].iloc[0])
        r_u = tr[sym_of_fam[fam]]
        F = (1.0 + L * r_u).cumprod()
        g = g.sort_values("month_end")
        anchors = [(pd.Timestamp(m), float(a), pd.Timestamp(fd))
                   for m, a, fd in zip(g["month_end"], g["net_assets"], g["filing_date"]) if a > 0]
        # positions of anchor dates on the grid (last grid day <= anchor date)
        pos = np.searchsorted(grid, [a[0] for a in anchors], side="right") - 1
        keep = [(p, a) for p, a in zip(pos, anchors) if p >= 0]
        s_best = pd.Series(np.nan, index=grid)
        s_strict = pd.Series(np.nan, index=grid)
        Fv = F.to_numpy()
        for i, (p0, (m0, a0, fd0)) in enumerate(keep):
            if i + 1 < len(keep):
                p1, (m1, a1, _) = keep[i + 1]
                if p1 <= p0:
                    continue
                nav = Fv[p0:p1 + 1] / Fv[p0]
                G = a1 / (a0 * nav[-1]) if a0 * nav[-1] > 0 else 1.0
                tau = np.arange(p1 - p0 + 1) / (p1 - p0)
                s_best.iloc[p0:p1 + 1] = a0 * nav * np.sign(G) * np.abs(G) ** tau
            else:  # after last anchor: NAV propagation only
                nav = Fv[p0:] / Fv[p0]
                s_best.iloc[p0:] = a0 * nav
        # strict PIT: latest anchor with filing_date <= t, NAV-propagated forward
        fd_sorted = sorted(keep, key=lambda x: x[1][2])
        for p0, (m0, a0, fd0) in fd_sorted:
            fpos = np.searchsorted(grid, fd0, side="left")
            start = max(fpos, p0)
            if start < len(grid):
                s_strict.iloc[start:] = a0 * (Fv[start:] / Fv[p0])
        best[tick] = s_best
        strict[tick] = s_strict
        # error bar: interpolated month-end vs flow-based reconstruction
        rg = recon[recon["ticker"] == tick]
        for m, a in zip(rg["month_end"], rg["net_assets"]):
            p = np.searchsorted(grid, pd.Timestamp(m), side="right") - 1
            b = s_best.iloc[p] if p >= 0 else np.nan
            if np.isfinite(b) and b > 0 and np.isfinite(a):
                interp_vs_recon.append({"ticker": tick, "leverage": L, "rel_diff": a / b - 1.0})
    err = pd.DataFrame(interp_vs_recon)
    err_stats = {}
    if len(err):
        err["side"] = np.where(err["leverage"] > 0, "long3x", "inverse3x")
        for side, gg in err.groupby("side"):
            err_stats[side] = {"n": int(len(gg)),
                               "median_abs_rel_diff": round(float(gg["rel_diff"].abs().median()), 3),
                               "p90_abs_rel_diff": round(float(gg["rel_diff"].abs().quantile(0.9)), 3)}
    return pd.DataFrame(best), pd.DataFrame(strict), err_stats


# ------------------------------------------------------------------ panel build --
def build_panel(frames: dict[str, pd.DataFrame], divs: pd.DataFrame,
                aum_best: pd.DataFrame, aum_strict: pd.DataFrame,
                semis_sym: str = "SMH") -> pd.DataFrame:
    grid = frames["SPY"].index
    rows = []
    for fam, (sym_default, members) in FAMILIES.items():
        sym = semis_sym if fam == "SOXX" else sym_default
        fr = frames[sym].reindex(grid)
        dv = divs[divs["symbol"] == sym].set_index("ex_date")["rate"].reindex(grid).fillna(0.0)
        prev_close = fr["close_px"].shift(1)
        r_1530 = (fr["sig_px"] + dv) / prev_close - 1.0
        r_last30 = fr["close_px"] / fr["sig_px"] - 1.0
        r_intraleg = fr["close_px"] / fr["fill_px"] - 1.0
        nxt_open = fr["open_px"].shift(-1)
        nxt_close = fr["close_px"].shift(-1)
        dv_next = dv.shift(-1).fillna(0.0)
        r_on = (nxt_open + dv_next) / fr["close_px"] - 1.0
        r_cc = (nxt_close + dv_next) / fr["close_px"] - 1.0
        k = pd.Series({t: (L * L - L) for t, L in members})
        m_best = (aum_best[[t for t, _ in members]] * k).sum(axis=1).reindex(grid)
        m_strict = (aum_strict[[t for t, _ in members]] * k).sum(axis=1).reindex(grid)
        d = pd.DataFrame({
            "family": fam, "bar_symbol": sym, "date": grid,
            "r_1530": r_1530.values, "r_last30": r_last30.values,
            "r_intraleg": r_intraleg.values, "r_on": r_on.values, "r_cc": r_cc.values,
            "mult_best": m_best.shift(1).values, "mult_strict": m_strict.shift(1).values,
            "dvol_l30": fr["dvol_l30"].values,
        })
        rows.append(d)
    p = pd.concat(rows, ignore_index=True)
    p["flow"] = p["r_1530"] * p["mult_best"]
    p["flow_strict"] = p["r_1530"] * p["mult_strict"]
    # PIT z-scale: trailing std of past flows only
    def _z(g: pd.DataFrame, col: str) -> pd.Series:
        sd = g[col].shift(1).rolling(252, min_periods=120).std()
        return g[col] / sd
    p = p.sort_values(["family", "date"]).reset_index(drop=True)
    p["flow_z"] = p.groupby("family", group_keys=False).apply(lambda g: _z(g, "flow"), include_groups=False).reset_index(level=0, drop=True)
    p["flow_z_strict"] = p.groupby("family", group_keys=False).apply(lambda g: _z(g, "flow_strict"), include_groups=False).reset_index(level=0, drop=True)
    return p


# ------------------------------------------------------------------- statistics --
def ols_nw(y: np.ndarray, X: np.ndarray, lags: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """OLS with Newey-West HAC t-stats. X excludes constant (added here)."""
    X1 = np.column_stack([np.ones(len(y)), X])
    XtX = X1.T @ X1
    beta = np.linalg.solve(XtX, X1.T @ y)
    e = y - X1 @ beta
    Z = X1 * e[:, None]
    S = Z.T @ Z
    for lag in range(1, lags + 1):
        w = 1.0 - lag / (lags + 1.0)
        G = Z[lag:].T @ Z[:-lag]
        S += w * (G + G.T)
    Vi = np.linalg.inv(XtX)
    V = Vi @ S @ Vi
    t = beta / np.sqrt(np.diag(V))
    return beta, t


def ols_cluster(y: np.ndarray, X: np.ndarray, groups: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """OLS with cluster-robust (by group) t-stats. X excludes constant."""
    X1 = np.column_stack([np.ones(len(y)), X])
    XtX = X1.T @ X1
    beta = np.linalg.solve(XtX, X1.T @ y)
    e = y - X1 @ beta
    S = np.zeros((X1.shape[1], X1.shape[1]))
    for g in np.unique(groups):
        m = groups == g
        v = X1[m].T @ e[m]
        S += np.outer(v, v)
    G = len(np.unique(groups))
    n, kk = X1.shape
    S *= (G / (G - 1)) * ((n - 1) / (n - kk))
    Vi = np.linalg.inv(XtX)
    V = Vi @ S @ Vi
    t = beta / np.sqrt(np.diag(V))
    return beta, t


def question_ab(p: pd.DataFrame, ycol: str, xcol: str = "flow_z") -> dict:
    """Per-family + pooled regressions of ycol (in bps) on flow_z (+ decile table)."""
    out: dict = {"per_family": {}}
    for fam, g in p.groupby("family"):
        g = g.dropna(subset=[ycol, xcol])
        if len(g) < 200:
            out["per_family"][fam] = {"n": int(len(g)), "note": "too few valid days"}
            continue
        b, t = ols_nw(g[ycol].to_numpy() * 1e4, g[[xcol]].to_numpy())
        out["per_family"][fam] = {"n": int(len(g)), "bps_per_sigma": round(float(b[1]), 2), "t_nw5": round(float(t[1]), 2)}
    g = p.dropna(subset=[ycol, xcol])
    days = g["date"].astype("int64").to_numpy()
    b, t = ols_cluster(g[ycol].to_numpy() * 1e4, g[[xcol]].to_numpy(), days)
    out["pooled"] = {"n": int(len(g)), "bps_per_sigma": round(float(b[1]), 2), "t_dayclustered": round(float(t[1]), 2)}
    # decile table
    g = g.copy()
    g["dec"] = pd.qcut(g[xcol], 10, labels=False, duplicates="drop")
    dec = g.groupby("dec").agg(mean_bps=(ycol, lambda s: float(s.mean() * 1e4)),
                               mean_flow_z=(xcol, "mean"), n=(ycol, "size"))
    out["decile_mean_bps"] = {int(i): round(r["mean_bps"], 2) for i, r in dec.iterrows()}
    # era splits (pooled slope)
    for label, lo, hi in (("early_to_2022", "2020-07-01", "2022-12-31"), ("2023_2026H1", "2023-01-01", "2026-12-31")):
        gg = g[(g["date"] >= lo) & (g["date"] <= hi)]
        if len(gg) > 300:
            bb, tt = ols_cluster(gg[ycol].to_numpy() * 1e4, gg[[xcol]].to_numpy(), gg["date"].astype("int64").to_numpy())
            out[f"era_{label}"] = {"n": int(len(gg)), "span": f"{gg['date'].min().date()}..{gg['date'].max().date()}",
                                   "bps_per_sigma": round(float(bb[1]), 2), "t": round(float(tt[1]), 2)}
    return out


def interaction_test(p: pd.DataFrame, ycol: str) -> dict:
    """y ~ r_1530 + r_1530 * m_z (within-family standardized log multiplier)."""
    g = p.dropna(subset=[ycol, "r_1530", "mult_best"]).copy()
    g["logm"] = np.log10(g["mult_best"].clip(lower=1e6))
    g["m_z"] = g.groupby("family")["logm"].transform(lambda s: (s - s.mean()) / (s.std() or 1.0))
    g["inter"] = g["r_1530"] * g["m_z"]
    days = g["date"].astype("int64").to_numpy()
    b, t = ols_cluster(g[ycol].to_numpy() * 1e4, g[["r_1530", "inter"]].to_numpy() * 1e2, days)
    return {"n": int(len(g)),
            "momentum_bps_per_1pct_r1530": round(float(b[1]), 2), "t_mom": round(float(t[1]), 2),
            "flow_interaction_bps_per_1pct_x_sigma_logAUM": round(float(b[2]), 2), "t_inter": round(float(t[2]), 2),
            "note": "m_z is full-sample standardized (mechanism inference, not a trading rule)"}


# -------------------------------------------------------------------- strategy --
def run_strategy(p: pd.DataFrame, q: float, leg: str) -> tuple[pd.Series, dict]:
    """PIT spec on STRICT AUM flow. leg in {'intraday_cont','overnight_rev'}."""
    p = p.sort_values(["family", "date"]).copy()
    az = p.groupby("family", group_keys=False)["flow_z_strict"].apply(
        lambda s: s.abs().shift(1).rolling(252, min_periods=120).quantile(q)).reset_index(level=0, drop=True)
    p["thr"] = az
    p["trig"] = (p["flow_z_strict"].abs() >= p["thr"]) & p["thr"].notna()
    sign = np.sign(p["flow_z_strict"])
    rt = 2 * ONE_WAY_BPS * 1e-4
    if leg == "intraday_cont":
        p["leg_ret"] = sign * p["r_intraleg"] - rt
        need = ["r_intraleg"]
    else:  # overnight reversal
        borrow = (BORROW_BPS_ANNUAL / 252.0) * 1e-4
        shorts = (-sign > 0) * 0 + (-sign < 0) * 1  # short when -sign(flow) < 0
        p["leg_ret"] = -sign * p["r_on"] - rt - shorts * borrow
        need = ["r_on"]
    p.loc[~p["trig"] | p[need[0]].isna() | sign.eq(0), "leg_ret"] = np.nan
    trig = p[p["leg_ret"].notna()]
    port = trig.groupby("date")["leg_ret"].mean()
    grid = pd.DatetimeIndex(sorted(p["date"].unique()))
    port = port.reindex(grid).fillna(0.0)
    yr = port.groupby(port.index.year)
    per_year = {int(y): {"net_ret_pct": round(float((1 + s).prod() - 1) * 100, 2),
                         "n_trades": int(trig[trig["date"].dt.year == y].shape[0])}
                for y, s in yr}
    mu, sd = port.mean(), port.std(ddof=1)
    hit = float((trig["leg_ret"] > 0).mean()) if len(trig) else float("nan")
    stats = {"threshold_pctile": int(q * 100), "n_family_trades": int(len(trig)),
             "trades_per_year": round(len(trig) / max(len(grid) / 252, 1e-9), 1),
             "mean_bps_per_trade_net": round(float(trig["leg_ret"].mean() * 1e4), 2) if len(trig) else None,
             "hit_rate": round(hit, 3),
             "ann_sharpe_alldays": round(float(mu / sd * np.sqrt(252)), 2) if sd > 0 else None,
             "total_net_ret_pct": round(float((1 + port).prod() - 1) * 100, 2),
             "per_year": per_year}
    return port, stats


def equity_ms(net: pd.Series, init: float = INIT_CASH) -> pd.Series:
    eq = init * (1.0 + net).cumprod()
    ms = pd.DatetimeIndex(eq.index).to_numpy(dtype="datetime64[ms]").astype("int64")
    return pd.Series(eq.to_numpy(float), index=pd.Index(ms, name="ts"), name="equity")


# ------------------------------------------------------------------------ main --
def main() -> int:
    from alphaforge.analytics.metrics import summarize

    print("loading minute lake ...")
    frames = {s: load_daily_frame(s) for s in BAR_SYMBOLS}
    for s, f in frames.items():
        ok = f.dropna(subset=["sig_px", "fill_px", "close_px"])
        print(f"  {s:4s} days={len(f):4d} valid_signal_days={len(ok):4d} span={f.index.min().date()}..{f.index.max().date()}")
    divs = load_dividends()
    print(f"dividends: {len(divs)} ex-date rows cached")

    print("building daily AUM (filed anchors + NAV/geometric-flow interpolation) ...")
    aum_best, aum_strict, aum_err = build_daily_aum(frames, divs)

    print("building family-day panel ...")
    p = build_panel(frames, divs, aum_best, aum_strict, semis_sym="SMH")
    p.to_parquet(OUT / "flow_panel.parquet", index=False)
    valid = p.dropna(subset=["r_1530", "r_last30", "flow_z"])
    per_fam_days = valid.groupby("family").size().to_dict()
    print(f"  panel rows={len(p)}  valid={len(valid)}  per-family={per_fam_days}")

    # descriptive flow scale
    latest = p.dropna(subset=["mult_best"]).groupby("family").tail(1).set_index("family")["mult_best"] / 1e9
    big_flow = valid.groupby("family")["flow"].apply(lambda s: float(s.abs().quantile(0.95)) / 1e9)

    results: dict = {
        "probe": "TRACK_B_STEP_2_letf_forced_rebalance_flow",
        "date": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "window": f"{valid['date'].min().date()}..{valid['date'].max().date()}",
        "protocol": "research-only event/IC screen; NO walk-forward gauntlet; ZERO appends to var/experiments.jsonl (N stays 102); disclosed",
        "families_multiplier_busd_latest": {k: round(float(v), 1) for k, v in latest.items()},
        "flow_p95_abs_busd": {k: round(float(v), 2) for k, v in big_flow.items()},
        "valid_days_per_family": {k: int(v) for k, v in per_fam_days.items()},
        "aum_error_bars": aum_err,
    }

    print("Q(a) continuation into the close ...")
    results["qa_continuation_last30"] = question_ab(valid, "r_last30")
    results["qa_interaction_mechanism"] = interaction_test(valid, "r_last30")
    # strict-PIT AUM robustness
    vs = p.dropna(subset=["r_1530", "r_last30", "flow_z_strict"])
    b, t = ols_cluster(vs["r_last30"].to_numpy() * 1e4, vs[["flow_z_strict"]].to_numpy(), vs["date"].astype("int64").to_numpy())
    results["qa_strict_pit_aum_pooled"] = {"n": int(len(vs)), "bps_per_sigma": round(float(b[1]), 2), "t": round(float(t[1]), 2)}
    # semis robustness on SOXX bars
    frames_soxx = dict(frames)
    p_soxx = build_panel(frames_soxx, divs, aum_best, aum_strict, semis_sym="SOXX")
    g = p_soxx[p_soxx["family"] == "SOXX"].dropna(subset=["r_last30", "flow_z"])
    if len(g) > 200:
        b, t = ols_nw(g["r_last30"].to_numpy() * 1e4, g[["flow_z"]].to_numpy())
        results["qa_semis_on_soxx_bars"] = {"n": int(len(g)), "bps_per_sigma": round(float(b[1]), 2), "t_nw5": round(float(t[1]), 2)}

    print("Q(b) overnight ...")
    results["qb_overnight_close_to_open"] = question_ab(p.dropna(subset=["r_on", "flow_z"]), "r_on")
    results["qb_close_to_next_close"] = question_ab(p.dropna(subset=["r_cc", "flow_z"]), "r_cc")

    print("Q(c) tradeable spec (STRICT PIT AUM) ...")
    strat = {}
    for leg in ("intraday_cont", "overnight_rev"):
        for q in (0.80, 0.90, 0.95):
            port, st = run_strategy(p, q, leg)
            key = f"{leg}_q{int(q*100)}"
            strat[key] = st
            if q == 0.90:  # primary
                eq = equity_ms(port)
                eq.to_frame("equity").to_parquet(OUT / f"strategy_equity_{leg}_q90.parquet")
                sm = summarize(eq)
                st["blessed_summarize"] = {"net_sharpe": round(float(sm.sharpe), 2),
                                           "ann_vol": round(float(sm.vol_ann), 4),
                                           "max_dd": round(float(sm.max_dd), 4),
                                           "cagr": round(float(sm.cagr), 4)}
    results["qc_strategy_grid"] = strat
    results["qc_primary"] = {"spec": "q90; intraday_cont + overnight_rev reported separately; equal-weight across triggered families",
                             "costs": "6bp one-way x2 per leg (+borrow 50bp/yr on short overnight)"}

    # power / noise-floor honesty
    sd30 = float(valid["r_last30"].std() * 1e4)
    eff = results["qa_continuation_last30"]["pooled"]["bps_per_sigma"]
    results["power_analysis"] = {
        "iex_noise_floor_bps": "0.5-1.2 median (max ~3) per step-1 measurement",
        "sigma_r_last30_bps": round(sd30, 1),
        "pooled_effect_bps_per_sigma_flow": eff,
        "underpowered_flag": bool(abs(eff) < 2.0),
        "meaning": "if |effect| < ~2bp it is inside the IEX single-venue noise band -> free data cannot settle it",
    }
    # ---- POST-HOC diagnostic (NOT pre-registered; added after the first full run and
    # labeled as such): the only significant Q(a) cell was TLT (+1.9bps/sigma, t 3.9).
    # Discriminate flow vs plain late-day momentum: (i) same regression with r_1530
    # standardized by its OWN trailing std — NO AUM anywhere; (ii) within-TLT AUM
    # interaction. If (i) matches and (ii) is <=0, the cell is NOT the flow mechanism.
    gt = valid[valid["family"] == "TLT"].sort_values("date").copy()
    rz = gt["r_1530"] / gt["r_1530"].shift(1).rolling(252, min_periods=120).std()
    gt = gt.assign(rz=rz).dropna(subset=["rz", "r_last30"])
    bm, tm = ols_nw(gt["r_last30"].to_numpy() * 1e4, gt[["rz"]].to_numpy())
    lm = np.log10(gt["mult_best"])
    mz = (lm - lm.mean()) / lm.std()
    bi, ti = ols_nw(gt["r_last30"].to_numpy() * 1e4, np.column_stack([gt["rz"], gt["rz"] * mz]))
    results["post_hoc_tlt_diagnostic"] = {
        "label": "POST-HOC (not pre-registered) — mechanism check on the single significant Q(a) cell",
        "momentum_only_no_aum": {"n": int(len(gt)), "bps_per_sigma": round(float(bm[1]), 2), "t_nw5": round(float(tm[1]), 2)},
        "within_tlt_aum_interaction": {"bps": round(float(bi[2]), 2), "t_nw5": round(float(ti[2]), 2)},
        "reading": "momentum-only t matches the flow_z t and the AUM interaction is non-positive -> the TLT cell is TLT-specific last-30-min momentum (or venue artifact), NOT forced-rebalance flow; also inconsistent cross-sectionally (smallest-flow family, biggest t)",
    }

    results["caveats"] = [
        "2018 regime NOT testable locally: free IEX lake starts 2020-07-27 (step-1 finding); needs QC cloud or paid Databento 2018-05+ slice",
        "semis family measured on SMH bars (SOXX too thin on IEX pre-2024); SOXL/SOXS actually track the ICE Semi index — proxy error stated, SOXX robustness reported",
        "AUM within-quarter values are interpolated between exact filed anchors; disagreement vs flow-based reconstruction reported in aum_error_bars (inverse funds worst)",
        "flow multiplier omits 2x/-2x funds (SSO/SDS/QLD/QID/SDOW...), futures-based levered ETNs and OTC-swap hedge timing differences -> LEVEL of flow is a floor, not a ceiling",
        "IEX bars are a single-venue proxy for official auction prints; MOC/open-auction fills approximated by 15:59-bar close / 09:30-bar open",
    ]

    (OUT / "letf_flow_results.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
