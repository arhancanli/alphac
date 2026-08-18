#!/usr/bin/env python3
"""ANALYSIS — is the book's diversification still there in the stress?

THE QUESTION. The published average pairwise correlation of the live book is +0.0274, and the
14-sleeve objective needs rho_bar at or below +0.0090 for a 2.0 Sharpe and NEGATIVE for 2.5.
But that is the ORDINARY correlation. The admission contract also carries
`stressed_pairwise_correlation_max = 0.50`, and `docs/SLEEVE_DISCOVERY_PROGRAM.md` says
plainly that "a low unconditional point estimate cannot pass". Nobody has published what the
CURRENT book's stressed correlation is. Diversification that evaporates in a crisis is not
diversification; it is a low unconditional number.

*** THE STRESS DEFINITION IS PREDECLARED HERE, IN CODE, BEFORE ANY RESULT IS COMPUTED. ***

Two rules, both fixed as constants below, both EXOGENOUS to the book, and BOTH reported. They
are not selected after the fact and no third rule is added later:

    S1_DRAWDOWN   SPY drawdown from its trailing 252-session running maximum is <= -10%.
    S2_TAIL       SPY trailing 5-session return is in the worst 5% of the sample.

WHY EXOGENOUS MATTERS, and it is the trap this whole file is built to avoid: defining stress by
the BOOK's own worst days conditions on the sum of the series being correlated. That inflates
measured pairwise correlation mechanically -- selection on the dependent variable -- and would
manufacture a scary number that means nothing. SPY knows nothing about these sleeves.

WHAT THIS IS NOT. No hypothesis is registered, no return is opened, no candidate is admitted or
killed. It measures sleeves already deployed. Zero trials; the ledger is asserted unmoved.

FAITHFULNESS PIN. The all-days numbers computed here are asserted equal to
`alphaforge.portfolio.book.combine_book`'s own `corr`, which is the shipped path. A stressed
statistic computed by a private re-implementation that disagrees with production on the easy
case would be worthless, so the run FAILS if they disagree.

    uv run python scripts/analyze_stressed_correlation.py
"""
# ruff: noqa: E501
from __future__ import annotations

import glob
import json
import sys
from itertools import combinations
from pathlib import Path

import duckdb
import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from alphaforge.portfolio.book import SleeveCurve, _daily_returns, combine_book  # noqa: E402

# ----- PREDECLARED, exogenous, both reported, never reselected ------------------------------
S1_DRAWDOWN_THRESHOLD = -0.10
S1_RUNNING_MAX_SESSIONS = 252
S2_TAIL_HORIZON_SESSIONS = 5
S2_TAIL_PERCENTILE = 5.0
STRESS_RULES = ("S1_DRAWDOWN", "S2_TAIL")
MIN_STRESS_OBS = 63  # the contract's own floor for a stressed estimate
# --------------------------------------------------------------------------------------------

SPY_LAKE = "data/lake_mf/ohlcv_1d"
SPY_ID = "XUSE:CASH:SPYUSD"
DAY_MS = 86_400_000

# All FOUR live sleeves.
#
# CORRECTION 2026-08-18: an earlier revision of this file excluded AlphaVintage and asserted its
# curve "does not exist anywhere", because it looked only under artifacts/walkforward/. That was
# wrong. AlphaVintage was validated as a probe, so its curve is at artifacts/probe/<probe>/ --
# exactly where probe_cpi_surprise_size.py's own write_curve() call puts it, and it holds 25 years
# (2001-06-29 onward), the second-deepest history in the project. The curve_store defect it was
# cited as an instance of was FIXED for this sleeve; the claim that it was still open was a
# directory assumption, not a measurement. Sleeve curves live in two places and anything walking
# them must look in both.
SLEEVES = {
    "AlphaForge": "artifacts/walkforward/crypto_carry_wk/equity.parquet",
    "AlphaMax": "artifacts/walkforward/k30_dn_63/equity.parquet",
    "AlphaTrend": "artifacts/walkforward/mf_live_fwd/equity.parquet",
    "AlphaVintage": "artifacts/probe/cpi_surprise_size/equity.parquet",
}
# LONG-HISTORY FAMILY PROXIES. The deployed pair AlphaMax x AlphaTrend is the book's worst
# (+0.21) and can only be measured over 728 days containing ~16 stressed ones. The same
# ECONOMIC families have 21-26 year pre-registered runs covering 2008, 2020 and 2022. These are
# PROXIES: they answer "do these return sources decouple in a crisis", NOT "what did the
# deployed sleeve do". Different configs, different universes, same mechanism. Never quote a
# proxy number as the deployed sleeve's correlation.
FAMILY_PROXIES = {
    "momentum": "artifacts/walkforward/prereg_momentum/equity.parquet",
    "trend": "artifacts/walkforward/prereg_trend/equity.parquet",
    "asset_growth": "artifacts/walkforward/prereg_investment/equity.parquet",
}
PROXY_FOR = {
    "momentum|trend": "AlphaMax x AlphaTrend (deployed all-days +0.2100, the book's worst pair)",
    "asset_growth|momentum": "AlphaLedger x AlphaMax (claimed -0.367, the biggest diversifier)",
    "asset_growth|trend": "AlphaLedger x AlphaTrend",
}

OUT_DIR = _ROOT / "artifacts" / "analysis" / "stressed_correlation"
LEDGER = _ROOT / "var" / "experiments.jsonl"


def load_curve(name: str, rel: str) -> SleeveCurve:
    df = duckdb.connect().execute(
        f"SELECT ts, equity FROM read_parquet('{_ROOT / rel}') ORDER BY ts"
    ).df()
    return SleeveCurve(name=name, ts_ms=df.ts.astype("int64").tolist(), equity=df.equity.astype(float).tolist())


def spy_stress_masks() -> tuple[np.ndarray, dict[str, np.ndarray]]:
    files = glob.glob(f"{_ROOT / SPY_LAKE}/**/*.parquet", recursive=True)
    if not files:
        raise SystemExit(f"ABORT: no SPY parquet under {SPY_LAKE}")
    # epoch_ms() in SQL, NOT .astype("int64") in pandas. duckdb hands back a tz-aware
    # Timestamp here, and .astype("int64") on that yields NANOseconds -- dividing by DAY_MS
    # then produced a day axis off by a factor of 1e6, zero overlap with the book, and a
    # confident "no stress days" that was pure unit error. The sleeve curves' own `ts`
    # column really is int64 epoch ms, which is what made the mismatch easy to miss.
    df = duckdb.connect().execute(
        f"""SELECT epoch_ms(ts_open) AS ts_ms, close FROM read_parquet('{_ROOT / SPY_LAKE}/**/*.parquet')
            WHERE instrument_id = '{SPY_ID}' ORDER BY ts_open"""
    ).df()
    if df.empty:
        raise SystemExit(f"ABORT: {SPY_ID} not found in {SPY_LAKE}")
    days = (df.ts_ms.astype("int64") // DAY_MS).to_numpy()
    px = df.close.astype(float).to_numpy()

    run_max = np.array([px[max(0, i - S1_RUNNING_MAX_SESSIONS + 1) : i + 1].max() for i in range(px.size)])
    dd = px / run_max - 1.0
    s1 = dd <= S1_DRAWDOWN_THRESHOLD

    h = S2_TAIL_HORIZON_SESSIONS
    r5 = np.full(px.size, np.nan)
    r5[h:] = px[h:] / px[:-h] - 1.0
    finite = np.isfinite(r5)
    cut = np.percentile(r5[finite], S2_TAIL_PERCENTILE)
    s2 = finite & (r5 <= cut)
    return days, {"S1_DRAWDOWN": s1, "S2_TAIL": s2}


def main() -> int:
    before = sum(1 for _ in LEDGER.open()) if LEDGER.exists() else 0
    curves = [load_curve(n, r) for n, r in SLEEVES.items()]
    names = [c.name for c in curves]

    book = combine_book(curves, scheme="equal_risk")
    day_index = {int(d): i for i, d in enumerate(book.days)}
    n = len(book.days)

    # Reconstruct each sleeve's genuinely-ACTIVE days (book.py excludes padded zeros).
    active: dict[str, np.ndarray] = {}
    for c in curves:
        d, _ = _daily_returns(c)
        m = np.zeros(n, dtype=bool)
        for x in d:
            i = day_index.get(int(x))
            if i is not None:
                m[i] = True
        active[c.name] = m

    spy_days, spy_masks = spy_stress_masks()
    spy_pos = {int(d): i for i, d in enumerate(spy_days)}
    regimes: dict[str, np.ndarray] = {"ALL": np.ones(n, dtype=bool)}
    for rule in STRESS_RULES:
        m = np.zeros(n, dtype=bool)
        for j, d in enumerate(book.days):
            i = spy_pos.get(int(d))
            if i is not None and spy_masks[rule][i]:
                m[j] = True
        regimes[f"STRESS:{rule}"] = m
        regimes[f"CALM:{rule}"] = ~m

    # CAN-THIS-FAIL GUARD. S2_TAIL marks the worst 5% of SPY days BY CONSTRUCTION, so it can
    # only be empty over the book window if the two day axes fail to intersect. An empty
    # stress set would otherwise read as the reassuring "no stress in this book", which is
    # exactly the false negative a unit error already produced here once.
    if regimes["STRESS:S2_TAIL"].sum() == 0:
        raise SystemExit(
            "ABORT: S2_TAIL selected zero days over the book window. That rule marks the worst "
            "5% of SPY sessions by construction, so an empty result means the SPY and book day "
            "axes do not intersect -- a unit or window bug, never a finding."
        )

    rets = book.sleeve_returns
    out_pairs: dict[str, dict[str, float]] = {}
    rho_bar: dict[str, float] = {}
    obs: dict[str, int] = {}
    for rname, rmask in regimes.items():
        pair_vals: dict[str, float] = {}
        for a, b in combinations(names, 2):
            mask = active[a] & active[b] & rmask
            if mask.sum() >= 2:
                ca, cb = rets[a][mask], rets[b][mask]
                pair_vals[f"{a}|{b}"] = (
                    float(np.corrcoef(ca, cb)[0, 1]) if np.std(ca) > 1e-12 and np.std(cb) > 1e-12 else 0.0
                )
            else:
                pair_vals[f"{a}|{b}"] = float("nan")
        out_pairs[rname] = pair_vals
        vals = [v for v in pair_vals.values() if np.isfinite(v)]
        rho_bar[rname] = float(np.mean(vals)) if vals else float("nan")
        obs[rname] = int(rmask.sum())

    # FAITHFULNESS PIN against the shipped path.
    for (a, b), prod in book.corr.items():
        mine = out_pairs["ALL"][f"{a}|{b}"]
        if not (np.isnan(prod) and np.isnan(mine)) and abs(float(prod) - mine) > 1e-9:
            raise SystemExit(f"ABORT: replication disagrees with combine_book on {a}|{b}: {mine} vs {prod}")

    print("=" * 96)
    print("  STRESSED CORRELATION — is the diversification there when it is needed?")
    print("=" * 96)
    print(f"  sleeves: {', '.join(names)}   ({n} common days)")
    print(f"\n  replication PINNED to combine_book on all-days pairs: OK")
    for rname in ("ALL", "CALM:S1_DRAWDOWN", "STRESS:S1_DRAWDOWN", "CALM:S2_TAIL", "STRESS:S2_TAIL"):
        bar, k = rho_bar[rname], obs[rname]
        flag = "  <-- BELOW the contract's 63-observation floor, treat as indicative" if (
            rname.startswith("STRESS") and k < MIN_STRESS_OBS) else ""
        print(f"\n  {rname:<20} days={k:<6} rho_bar={bar:+.4f}{flag}")
        for p, v in out_pairs[rname].items():
            print(f"      {p:<28} {v:+.4f}")

    print("\n  REQUIRED at N=14 (from analyze_breadth_acquisition): rho_bar <= +0.0090 for 2.0,")
    print("  <= -0.0219 for 2.5. Those requirements are on the ORDINARY correlation; a book whose")
    print("  stressed correlation is far higher meets the target on paper and not in a crisis.")

    # ---- per-pair MAXIMAL windows -----------------------------------------------------
    # The three-way intersection is bound by AlphaMax's 729 days (2023-07+), a window with
    # almost no stress in it. Each PAIR can be measured over its own overlap instead, which
    # for AlphaForge|AlphaTrend reaches back to 2022-02 and therefore includes the 2022 bear
    # market. More observations is strictly more information -- but these windows are NOT
    # comparable to one another and are deliberately NOT averaged into a headline rho_bar,
    # because averaging correlations measured over different regimes invents a number that
    # describes no period that ever happened.
    per_pair: dict[str, dict[str, object]] = {}
    day_rets = {c.name: dict(zip(*[x.tolist() for x in _daily_returns(c)], strict=True)) for c in curves}
    for a, b in combinations(names, 2):
        shared = sorted(set(day_rets[a]) & set(day_rets[b]))
        if len(shared) < 2:
            continue
        ra = np.array([day_rets[a][d] for d in shared])
        rb = np.array([day_rets[b][d] for d in shared])
        entry: dict[str, object] = {
            "days": len(shared),
            "window": [int(shared[0]), int(shared[-1])],
            "corr_all": float(np.corrcoef(ra, rb)[0, 1]),
        }
        for rule in STRESS_RULES:
            sm = np.array([bool(spy_masks[rule][spy_pos[d]]) if d in spy_pos else False for d in shared])
            for label, mm in (("stress", sm), ("calm", ~sm)):
                k = int(mm.sum())
                v = (float(np.corrcoef(ra[mm], rb[mm])[0, 1])
                     if k >= 2 and np.std(ra[mm]) > 1e-12 and np.std(rb[mm]) > 1e-12 else float("nan"))
                entry[f"{label}_{rule}"] = v
                entry[f"{label}_{rule}_days"] = k
        per_pair[f"{a}|{b}"] = entry

    print("\n  PER-PAIR ON EACH PAIR'S OWN MAXIMAL WINDOW (not comparable across rows;")
    print("  deliberately NOT averaged into a headline number):")
    for pk, e in per_pair.items():
        print(f"\n    {pk}   {e['days']} shared days   all={e['corr_all']:+.4f}")
        for rule in STRESS_RULES:
            sd, cd = e[f"stress_{rule}_days"], e[f"calm_{rule}_days"]
            sv, cv = e[f"stress_{rule}"], e[f"calm_{rule}"]
            enough = "" if sd >= MIN_STRESS_OBS else f"  (below the {MIN_STRESS_OBS}-obs floor)"
            print(f"      {rule:<12} calm {cv:+.4f} ({cd}d)   stress {sv:+.4f} ({sd}d){enough}")

    # ---- long-history FAMILY PROXIES ---------------------------------------------------
    proxies = {n: load_curve(n, r) for n, r in FAMILY_PROXIES.items()}
    proxy_rets = {n: dict(zip(*[x.tolist() for x in _daily_returns(c)], strict=True)) for n, c in proxies.items()}
    proxy_out: dict[str, dict[str, object]] = {}
    print("\n" + "=" * 96)
    print("  LONG-HISTORY FAMILY PROXIES — 21-26y, spanning 2008 / 2020 / 2022")
    print("  These are FAMILIES, not the deployed sleeves. Do not quote them as sleeve correlations.")
    print("=" * 96)
    for a, b in combinations(sorted(proxies), 2):
        shared = sorted(set(proxy_rets[a]) & set(proxy_rets[b]))
        if len(shared) < 2:
            continue
        ra = np.array([proxy_rets[a][d] for d in shared])
        rb = np.array([proxy_rets[b][d] for d in shared])
        e: dict[str, object] = {
            "days": len(shared), "corr_all": float(np.corrcoef(ra, rb)[0, 1]),
            "proxy_for": PROXY_FOR.get(f"{a}|{b}", ""),
        }
        print(f"\n    {a} x {b}   {len(shared)} shared days   all={e['corr_all']:+.4f}")
        if e["proxy_for"]:
            print(f"      proxy for: {e['proxy_for']}")
        for rule in STRESS_RULES:
            sm = np.array([bool(spy_masks[rule][spy_pos[d]]) if d in spy_pos else False for d in shared])
            for label, mm in (("calm", ~sm), ("stress", sm)):
                k = int(mm.sum())
                v = (float(np.corrcoef(ra[mm], rb[mm])[0, 1])
                     if k >= 2 and np.std(ra[mm]) > 1e-12 and np.std(rb[mm]) > 1e-12 else float("nan"))
                e[f"{label}_{rule}"] = v
                e[f"{label}_{rule}_days"] = k
            flag = "" if e[f"stress_{rule}_days"] >= MIN_STRESS_OBS else "  (below floor)"
            print(f"      {rule:<12} calm {e[f'calm_{rule}']:+.4f} ({e[f'calm_{rule}_days']}d)"
                  f"   stress {e[f'stress_{rule}']:+.4f} ({e[f'stress_{rule}_days']}d){flag}")
        proxy_out[f"{a}|{b}"] = e

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "result.json").write_text(json.dumps({
        "sleeves": names,
        "correction_2026_08_18": (
            "An earlier revision excluded AlphaVintage claiming its curve did not exist. It does, at "
            "artifacts/probe/cpi_surprise_size/equity.parquet, with 25 years of history. Sleeve curves "
            "live under artifacts/walkforward/ AND artifacts/probe/; the exclusion was a directory "
            "assumption, not a measurement."
        ),
        "common_days": n,
        "stress_rules_predeclared": {
            "S1_DRAWDOWN": {"spy_drawdown_from_trailing_max": S1_DRAWDOWN_THRESHOLD,
                            "running_max_sessions": S1_RUNNING_MAX_SESSIONS},
            "S2_TAIL": {"spy_trailing_return_sessions": S2_TAIL_HORIZON_SESSIONS,
                        "worst_percentile": S2_TAIL_PERCENTILE},
            "exogenous": True,
            "note": "declared as module constants before any result was computed; both reported, neither reselected",
        },
        "observations": obs, "rho_bar": rho_bar, "pairwise": out_pairs,
        "per_pair_maximal_window": per_pair,
        "family_proxies_long_history": proxy_out,
        "family_proxy_note": "economic families over 21-26y, NOT the deployed sleeves; never quote as sleeve correlation",
        "per_pair_note": "each pair on its own overlap; NOT comparable across pairs and never averaged",
        "replication_pinned_to": "alphaforge.portfolio.book.combine_book.corr",
        "claim_boundary": "Measures deployed sleeves only. No hypothesis registered, no return opened, 0 trials.",
    }, indent=2, sort_keys=True) + "\n")

    after = sum(1 for _ in LEDGER.open()) if LEDGER.exists() else 0
    if before != after:
        raise SystemExit(f"ABORT: ledger moved {before} -> {after}; the zero-trial claim is void.")
    print(f"\n  ledger unmoved ({after}); 0 hypotheses consumed")
    print(f"  written: {OUT_DIR / 'result.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
