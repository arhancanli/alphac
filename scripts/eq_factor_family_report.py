#!/usr/bin/env python3
"""Honest synthesis for a family of equity-factor walk-forwards (glass-box decision tool).

Given several `af research walkforward --out <dir>` runs (each a single factor on the Sharadar
survivorship-free research lake), this prints the ONE honest comparison that decides KEEP/KILL:

  * per factor: net Sharpe, Deflated Sharpe (DSR), daily-return SKEW (the short-vol/crash check),
    max drawdown, turnover, OOS days;
  * the pairwise CORRELATION matrix of the OOS return streams — the prize is decorrelation, so
    two factors that both "work" but correlate 0.8 are ONE bet, not two;
  * if a momentum benchmark run is passed (--momentum), each factor's correlation to it (does it
    diversify the live 12-1 momentum sleeve, or duplicate it?).

It reads ONLY real artifacts (walkforward.json + equity.parquet); nothing is assumed. Default
verdict prior: most equity factors are exhausted, so expect mostly KILLs and hope for 1-2 that
clear a modest net Sharpe AND decorrelate. Usage:

    eq_factor_family_report.py <name>=<out_dir> [<name>=<out_dir> ...] [--momentum <out_dir>]
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def _load(out_dir: str) -> dict:
    d = Path(out_dir)
    wf = json.loads((d / "walkforward.json").read_text())
    s, v = wf.get("summary", {}), wf.get("validation", {})
    eq_path = d / "equity.parquet"
    rets = None
    if eq_path.exists():
        e = pd.read_parquet(eq_path)
        idx = pd.to_datetime(e["ts"], unit="ms", utc=True) if "ts" in e.columns else None
        r = pd.Series(e["equity"].to_numpy(dtype="float64"), index=idx).pct_change().dropna()
        rets = r
    skew = kurt = float("nan")
    if rets is not None and len(rets) > 10:
        z = (rets - rets.mean()) / rets.std(ddof=0)
        skew = float((z**3).mean())
        kurt = float((z**4).mean())
    return {
        "sharpe": float(s.get("sharpe", float("nan"))),
        "dsr": float(v.get("dsr", float("nan"))),
        "clears_gate": v.get("clears_dsr_gate"),
        "vol_ann": float(s.get("vol_ann", float("nan"))),
        "max_dd": float(s.get("max_dd", float("nan"))),
        "turnover_ann": float(s.get("turnover_ann", float("nan"))),
        "n_days": s.get("n_days"),
        "skew": skew,
        "kurt": kurt,
        "rets": rets,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="eq_factor_family_report")
    ap.add_argument("specs", nargs="+", help="name=out_dir pairs")
    ap.add_argument("--momentum", default=None, help="out_dir of a momentum benchmark run")
    a = ap.parse_args(argv)

    runs: dict[str, dict] = {}
    for spec in a.specs:
        name, _, out = spec.partition("=")
        runs[name] = _load(out)
    mom = _load(a.momentum) if a.momentum else None

    print("=" * 92)
    print(f"{'factor':<16}{'netSharpe':>10}{'DSR':>8}{'skew':>8}{'kurt':>8}{'maxDD':>8}{'turnover':>10}{'days':>7}  verdict")
    print("-" * 92)
    for name, r in runs.items():
        # honest KEEP bar: net Sharpe >= 0.40 AND skew not deeply negative AND decorrelated (checked below)
        keep = (r["sharpe"] >= 0.40) and (r["skew"] > -1.0)
        verdict = "candidate" if keep else "KILL/null"
        print(f"{name:<16}{r['sharpe']:>10.3f}{r['dsr']:>8.3f}{r['skew']:>8.2f}{r['kurt']:>8.1f}{r['max_dd']:>8.3f}{r['turnover_ann']:>10.1f}{r['n_days']!s:>7}  {verdict}")
    print("=" * 92)

    # pairwise correlation of OOS return streams (decorrelation is the prize)
    series = {n: r["rets"] for n, r in runs.items() if r["rets"] is not None}
    if mom and mom["rets"] is not None:
        series["[momentum]"] = mom["rets"]
    if len(series) >= 2:
        mat = pd.concat(series.values(), axis=1, keys=series.keys()).corr()
        print("\nOOS return-stream correlations (decorrelation = the real diversification test):")
        print(mat.round(2).to_string())
        print("\nRule: a candidate must clear net Sharpe AND correlate < ~0.3 to [momentum] AND to the others")
        print("(two factors correlated > 0.5 are one bet, not two — deploy at most one of a correlated pair).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
