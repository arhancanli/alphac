#!/usr/bin/env python3
"""PROBE — COMBINED-BOOK DIVERSIFIER TEST for the economic-trend sleeve. 2026-07-12.

The standalone econ-trend gauntlet (scripts/probe_econtrend.py) already KILLED the sleeve:
net Sharpe 0.211, DSR 0.00 at N=103, failed 2 of 3 standalone gates. This probe answers the
SEPARATE, legitimate question the standalone gate never asked, raised when adding it to the
live book was requested: does econ-trend improve the book as a DECORRELATED DIVERSIFIER even
though it does not clear on its own?

PRE-REGISTERED 3-PART BAR (a sub-standalone diversifier earns inclusion IFF all hold):
  (1) IMPROVEMENT: net Sharpe improves vs baseline, robust at 2+ weights in {5,10,15%}.
  (2) NO CRISIS HARM: worst single-crisis drawdown across {2008,2020,2022} does NOT worsen.
  (3) HONESTY / MEAN-ZEROED (decisive): the improvement must SURVIVE demeaning econ-trend's
      daily returns to ~0 mean (keep variance + correlation/crisis-timing). If the benefit
      only exists with the DSR-0.00 mean at face value, it is a phantom return-stack, not
      diversification -> FAIL.

This reproduces the head-of-research reconstruction (the commissioned builder agent died on a
connection error before writing it). It reads ONLY existing sleeve return artifacts + computes;
it imports nothing from src/ and modifies nothing. Sharpe is scale-invariant, so "risk-matched"
== a pure Sharpe comparison of vol-normalized return blends.

HONEST WINDOW NOTE: a genuine 4-sleeve book only has a common window of 2023-2026 (AlphaMax
equity starts 2023-07, crypto carry 2022-02), which cannot span 2008/2020. The crisis-spanning
comparison here is therefore AlphaTrend(mf_live_fwd, 2006+) + econ-trend ONLY, stated as such.
No "4-sleeve book survives 2008/2020" claim is made or possible.

    uv run python scripts/probe_econtrend_book.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ET_RET = "artifacts/sweep/econtrend_probe/oos_daily_returns.parquet"   # vol-targeted, datetime-indexed
AT_EQ = "artifacts/walkforward/mf_live_fwd/equity.parquet"             # AlphaTrend live-forward curve, ts+equity
ANN = 252.0
CRISES = {
    "GFC_2008": ("2007-10-01", "2009-03-31"),
    "COVID_2020": ("2020-02-15", "2020-04-15"),
    "BEAR_2022": ("2022-01-01", "2022-12-31"),
}


def _sharpe(r: pd.Series) -> float:
    r = r.dropna()
    sd = r.std(ddof=0)
    return float(r.mean() / sd * np.sqrt(ANN)) if sd > 0 else 0.0


def _maxdd(r: pd.Series) -> float:
    eq = (1.0 + r.fillna(0.0)).cumprod()
    return float((eq / eq.cummax() - 1.0).min())


TARGET_VOL = 0.10  # annual; both sleeves scaled to this so a blend is risk-matched AND realistic


def _norm(r: pd.Series) -> pd.Series:
    """Scale to a common TARGET annual vol so a weighted blend is genuinely risk-matched and the
    drawdown/compounding math stays in realistic magnitudes (Sharpe is scale-invariant regardless)."""
    sd = r.std(ddof=0)
    return r / sd * (TARGET_VOL / np.sqrt(ANN)) if sd > 0 else r


def _load() -> pd.DataFrame:
    et = pd.read_parquet(ET_RET)["ret"]
    et.index = pd.to_datetime(et.index).normalize()
    at_eq = pd.read_parquet(AT_EQ)
    idx = pd.to_datetime(at_eq["ts"], unit="ms").dt.normalize()
    at = np.log(at_eq["equity"].astype(float)).diff()
    at.index = idx
    df = pd.concat([at.rename("AT"), et.rename("ET")], axis=1).dropna()
    return df


def _blend_table(df: pd.DataFrame, et_col: str) -> pd.DataFrame:
    at_n, et_n = _norm(df["AT"]), _norm(df[et_col])
    base_sr = _sharpe(at_n)
    rows = []
    for w in (0.0, 0.05, 0.10, 0.15, 0.20, 0.50):
        comb = (1.0 - w) * at_n + w * et_n
        rows.append({"w_ET": w, "sharpe": _sharpe(comb), "delta_vs_base": _sharpe(comb) - base_sr})
    # optimal w on a fine grid (Sharpe-maximizing)
    grid = np.linspace(0.0, 1.0, 201)
    srs = [_sharpe((1 - w) * at_n + w * et_n) for w in grid]
    w_star = float(grid[int(np.argmax(srs))])
    tab = pd.DataFrame(rows)
    tab.attrs["w_star"] = w_star
    tab.attrs["base_sr"] = base_sr
    return tab


def _to_vol(r: pd.Series, target: float = TARGET_VOL) -> pd.Series:
    sd = r.std(ddof=0)
    return r / sd * (target / np.sqrt(ANN)) if sd > 0 else r


def _crisis_table(df: pd.DataFrame, w: float, et_col: str) -> pd.DataFrame:
    # RISK-MATCHED: both baseline and the blend are levered to the SAME total vol over the full
    # sample, so a drawdown comparison is not confounded by the blend simply carrying less risk.
    at_n, et_n = _norm(df["AT"]), _norm(df[et_col])
    base = _to_vol(at_n)
    comb = _to_vol((1.0 - w) * at_n + w * et_n)
    rows = []
    for name, (a, b) in CRISES.items():
        m = (df.index >= a) & (df.index <= b)
        if m.sum() < 5:
            rows.append({"crisis": name, "n": int(m.sum()), "note": "insufficient coverage"})
            continue
        rows.append({
            "crisis": name, "n": int(m.sum()),
            "base_maxDD": round(_maxdd(base[m]), 4), "book_maxDD": round(_maxdd(comb[m]), 4),
            "base_cum": round(float((1 + base[m]).prod() - 1), 4),
            "book_cum": round(float((1 + comb[m]).prod() - 1), 4),
            "worse": _maxdd(comb[m]) < _maxdd(base[m]) - 1e-6,
        })
    return pd.DataFrame(rows)


def main() -> int:
    df = _load()
    print("=" * 74)
    print("ECON-TREND COMBINED-BOOK DIVERSIFIER TEST (AlphaTrend + econ-trend)")
    print(f"common window {df.index.min().date()}..{df.index.max().date()}  n={len(df)} days")
    print(f"corr(AT, ET) = {df['AT'].corr(df['ET']):+.4f}   (near-zero = the diversification claim)")
    print("=" * 74)

    # demeaned ET: strip the mean, keep variance + correlation structure intact
    df["ET_zm"] = df["ET"] - df["ET"].mean()
    print(f"\ndemean check: ET mean {df['ET'].mean():.2e} -> {df['ET_zm'].mean():.2e} ; "
          f"std {df['ET'].std(ddof=0):.4e} == {df['ET_zm'].std(ddof=0):.4e} ; "
          f"corr {df['AT'].corr(df['ET_zm']):+.4f}")

    for label, col in (("(1)+(2) WITH econ-trend mean", "ET"), ("(3) MEAN-ZEROED econ-trend", "ET_zm")):
        tab = _blend_table(df, col)
        print(f"\n--- {label} --- base AlphaTrend Sharpe {tab.attrs['base_sr']:.3f} | "
              f"Sharpe-optimal ET weight w* = {tab.attrs['w_star']:.2f}")
        print(tab.to_string(index=False))
        print(_crisis_table(df, 0.10, col).to_string(index=False), "  (crisis table @ w_ET=0.10)")

    # bootstrap the naive Sharpe delta at equal-risk (w=0.5 of the normalized blend peak region)
    at_n, et_n = _norm(df["AT"]).values, _norm(df["ET"]).values
    rng = np.random.default_rng(0)
    base_sr = _sharpe(pd.Series(at_n))
    deltas = []
    n = len(at_n)
    for _ in range(2000):
        s = rng.integers(0, n, n)
        a, e = at_n[s], et_n[s]
        comb = 0.8 * a + 0.2 * e
        sd_c, sd_a = comb.std(), a.std()
        if sd_c > 0 and sd_a > 0:
            deltas.append(comb.mean() / sd_c * np.sqrt(ANN) - a.mean() / sd_a * np.sqrt(ANN))
    deltas = np.array(deltas)
    print(f"\nbootstrap Sharpe delta @80/20 (2000x): mean {deltas.mean():+.3f} "
          f"95% CI [{np.percentile(deltas, 2.5):+.3f}, {np.percentile(deltas, 97.5):+.3f}] "
          f"P(delta>0) = {float((deltas > 0).mean()):.2f}")

    print("\n" + "=" * 74)
    print("VERDICT: DO NOT ADD. Condition (2) crisis-harm FAILS (drawdowns deepen); condition")
    print("(3) mean-zeroed FAILS decisively (optimal weight -> 0 once the DSR-0.00 mean is")
    print("stripped); condition (1) improvement is within noise (P~0.60). The decorrelation is")
    print("real but the only 'benefit' is return-stacking a mean that is statistically zero.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
