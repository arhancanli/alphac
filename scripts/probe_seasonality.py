#!/usr/bin/env python3
"""PROBE — CROSS-SECTIONAL SAME-CALENDAR-MONTH SEASONALITY. Spec LOCKED 2026-07-20.

The last untested item on the ranked backlog. Evidence base: Keloharju-Linnainmaa-Nyberg
JF2016 (same-month returns persist); Jensen-Kelly-Pedersen JF2023 list seasonality among
the themes that replicate out-of-sample across 93 countries — but explicitly as one of
their WEAKEST replicators. Two prior campaign findings bound the honest expectation:
turn-of-month standalone already died here (gross Sharpe 0.35/0.32/0.13 on SPY/QQQ/IWM,
sign-flipping on the small-cap leg, before the committed 6bp), and every "better momentum"
variant that ran corr>0.85 to plain 12-1 died as momentum-in-costume.

=============================== PRE-REGISTERED SPEC ================================
Everything below was fixed BEFORE any result was computed. One spec, no search.

UNIVERSE   : the 33-ETF expanded macro basket (data/lake_mf_exp) — equity indices,
             single-country equity, rates/credit, commodities, FX. Daily total-return
             adjusted closes. NOTE the honest limitation: 33 names is a THIN
             cross-section for a rank strategy (a real seasonality study runs
             thousands of stocks); this is the low-turnover ETF version because the
             single-name version is already known to die on turnover.
SIGNAL     : at each month-end t, for each asset, the MEAN of that asset's returns in
             the SAME CALENDAR MONTH over the trailing N=10 years, using only months
             that completed strictly BEFORE t (point-in-time; the current occurrence is
             never in its own signal). Assets with <6 prior same-month observations are
             ineligible that month.
BOOK       : cross-sectional rank on the signal; LONG the top K=8, SHORT the bottom K=8,
             EQUAL weight, dollar-neutral, gross 1.0 (0.5 per side).
TIMING     : decide at month-end close t; weights become effective the NEXT session
             (no same-bar fill) and are held until the next month-end decision.
COSTS      : 6bp one-way charged on every weight change + 50bp/yr borrow accrued daily
             on the short leg (the committed ETF schedule).
METRICS    : blessed machinery — alphaforge.analytics.metrics.summarize on daily returns
             and alphaforge.validation.dsr.dsr_from_returns.

PRE-REGISTERED SCREEN GATE (both required to justify spending a walk-forward trial):
    (1) net Sharpe >= 0.30, AND
    (2) |corr to a plain 12-1 momentum book on the SAME universe| < 0.50.
Gate (2) is the decisive one: month t-12 sits INSIDE the 12-1 formation window, so this
signal is NOT orthogonal to momentum by construction. If the correlation is high this is
momentum wearing a calendar costume — the exact failure that killed residual momentum
(corr 0.87) and 52-week-high (corr 0.42) here — and the verdict is NULL regardless of Sharpe.

FAILING THE GATE IS A FULL SUCCESS. No walk-forward is run and no ledger trial is spent
unless the screen earns it. Nothing is re-tuned to make it pass.

    uv run python scripts/probe_seasonality.py
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

LAKE = "data/lake_mf_exp/ohlcv_1d"
N_YEARS = 10            # trailing same-calendar-month history
MIN_OBS = 6             # minimum prior same-month observations to be eligible
K_SIDE = 8              # names per side
COST_ONEWAY = 0.0006    # 6bp
BORROW_ANN = 0.0050     # 50bp/yr on the short leg
OUT = Path("artifacts/sweep/seasonality_probe")


def load_panel() -> pd.DataFrame:
    files = sorted(glob.glob(f"{LAKE}/instrument_id=*/**/*.parquet", recursive=True))
    if not files:
        raise SystemExit(f"no data under {LAKE}")
    frames: dict[str, pd.Series] = {}
    for iid in sorted({f.split("instrument_id=")[1].split("/")[0] for f in files}):
        ff = [f for f in files if f"instrument_id={iid}/" in f]
        df = pd.concat([pd.read_parquet(f, columns=["ts_open", "close"]) for f in ff])
        df = df.drop_duplicates("ts_open").sort_values("ts_open")
        s = pd.Series(
            df["close"].astype(float).values,
            index=pd.to_datetime(df["ts_open"], unit="ms").dt.normalize().values,
        )
        frames[iid.split(":")[-1].replace("USD", "")] = s[~s.index.duplicated()]
    px = pd.DataFrame(frames).sort_index()
    return px


def month_end_index(idx: pd.DatetimeIndex) -> list[pd.Timestamp]:
    s = pd.Series(1, index=idx)
    return list(s.groupby([idx.year, idx.month]).apply(lambda g: g.index[-1]).values)


def build_weights(px: pd.DataFrame, signal_fn) -> pd.DataFrame:
    """Monthly rank book -> daily weight frame, effective the session AFTER the decision."""
    rets_d = np.log(px).diff()
    m_ends = [pd.Timestamp(t) for t in month_end_index(px.index)]
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for i, t in enumerate(m_ends[:-1]):
        score = signal_fn(px, rets_d, t)
        score = score.dropna()
        if len(score) < 2 * K_SIDE:
            continue
        ranked = score.sort_values(ascending=False)
        longs, shorts = ranked.index[:K_SIDE], ranked.index[-K_SIDE:]
        nxt = px.index[px.index > t]
        if len(nxt) == 0:
            break
        start = nxt[0]                      # effective NEXT session — no same-bar fill
        end = m_ends[i + 1]
        seg = (px.index >= start) & (px.index <= end)
        w.loc[seg, longs] = 0.5 / K_SIDE
        w.loc[seg, shorts] = -0.5 / K_SIDE
    return w, rets_d


def seasonal_signal(px: pd.DataFrame, rets_d: pd.DataFrame, t: pd.Timestamp) -> pd.Series:
    """Mean return in the SAME calendar month over the trailing N years, strictly PIT."""
    m_ret = px.resample("ME").last().pct_change()
    hist = m_ret[m_ret.index < t]                      # only completed months before t
    target_month = (t.month % 12) + 1                  # the month we are about to hold
    same = hist[hist.index.month == target_month]
    same = same.tail(N_YEARS)
    out = same.mean()
    out[same.count() < MIN_OBS] = np.nan
    return out


def momentum_signal(px: pd.DataFrame, rets_d: pd.DataFrame, t: pd.Timestamp) -> pd.Series:
    """Plain 12-1: ln(C_{t-21}/C_{t-252}) — the control for the costume test."""
    h = px[px.index <= t]
    if len(h) < 260:
        return pd.Series(np.nan, index=px.columns)
    return np.log(h.iloc[-21] / h.iloc[-252])


def pnl(w: pd.DataFrame, rets_d: pd.DataFrame) -> pd.Series:
    held = w.shift(1).fillna(0.0)                      # yesterday's book earns today
    gross = (held * rets_d).sum(axis=1)
    turn = (w - w.shift(1)).abs().sum(axis=1).fillna(0.0)
    cost = turn * COST_ONEWAY
    borrow = held.clip(upper=0).abs().sum(axis=1) * (BORROW_ANN / 252.0)
    return (gross - cost - borrow).dropna(), turn


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    px = load_panel()
    print("=" * 74)
    print("CROSS-SECTIONAL SAME-CALENDAR-MONTH SEASONALITY — pre-registered screen")
    print(f"universe {px.shape[1]} ETFs | {px.index.min().date()}..{px.index.max().date()}")

    w_s, rets_d = build_weights(px, seasonal_signal)
    r_s, turn_s = pnl(w_s, rets_d)
    w_m, _ = build_weights(px, momentum_signal)
    r_m, _ = pnl(w_m, rets_d)

    live = r_s[w_s.abs().sum(axis=1).shift(1).fillna(0) > 0]
    if len(live) < 250:
        print(f"INSUFFICIENT: only {len(live)} live days — cannot screen honestly")
        return 0

    from alphaforge.analytics.metrics import summarize  # noqa: PLC0415
    from alphaforge.validation.dsr import dsr_from_returns  # noqa: PLC0415

    def ann(r):
        sd = r.std(ddof=0)
        return float(r.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0

    gross_only = (w_s.shift(1).fillna(0.0) * rets_d).sum(axis=1).loc[live.index]
    sr_net, sr_gross = ann(live), ann(gross_only)
    both = pd.concat([live.rename("s"), r_m.rename("m")], axis=1).dropna()
    corr = float(both["s"].corr(both["m"])) if len(both) > 100 else float("nan")
    eq = (1 + live).cumprod()
    dd = float((eq / eq.cummax() - 1).min())
    n_eligible = int((w_s.abs().sum(axis=1) > 0).sum())

    print(f"\nlive window   : {live.index.min().date()}..{live.index.max().date()} ({len(live)} days, {n_eligible} held)")
    print(f"net Sharpe    : {sr_net:+.3f}      (gross {sr_gross:+.3f})")
    print(f"ann turnover  : {turn_s.sum() / (len(live) / 252):.2f}x")
    print(f"maxDD         : {dd * 100:.2f}%")
    print(f"corr to 12-1  : {corr:+.3f}   <- the costume test (gate: |corr| < 0.50)")
    print(f"momentum ctrl : net Sharpe {ann(r_m):+.3f} on the same universe")

    g1, g2 = sr_net >= 0.30, abs(corr) < 0.50
    print(f"\nGATE (1) net Sharpe >= 0.30 : {'PASS' if g1 else 'FAIL'}")
    print(f"GATE (2) |corr| < 0.50      : {'PASS' if g2 else 'FAIL'}")
    verdict = "PROCEED to walk-forward" if (g1 and g2) else "NULL — no trial spent"
    print(f"VERDICT: {verdict}")
    print("=" * 74)

    pd.DataFrame({"ret": live}).to_parquet(OUT / "daily_returns.parquet")
    import json
    (OUT / "result.json").write_text(json.dumps({
        "spec": "same-calendar-month seasonality, N=10y, K=8/side, 33-ETF, monthly, 6bp+50bp borrow",
        "net_sharpe": sr_net, "gross_sharpe": sr_gross, "corr_to_momentum_12_1": corr,
        "ann_turnover": float(turn_s.sum() / (len(live) / 252)), "max_dd": dd,
        "momentum_control_sharpe": ann(r_m), "n_days": len(live),
        "gate_sharpe": bool(g1), "gate_corr": bool(g2), "verdict": verdict,
    }, indent=1))
    print(f"artifacts: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
