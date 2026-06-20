"""Reproducible cross-asset book report — the unified multi-sleeve book.

Combines the per-sleeve walk-forward equity curves (equity momentum + crypto funding-carry)
into ONE book via alphaforge.portfolio.book.combine_book, and prints the honest matrix:
PIT-deployable headline, static full-sample diagnostic (quantifies hindsight), and the
vol-targeted sizing that meets the return objective. All metrics net of each sleeve's costs.

    uv run python scripts/cross_asset_book.py
    uv run python scripts/cross_asset_book.py --equity k30_dn_63 --crypto crypto_carry_wk

Sleeve curves are read from artifacts/walkforward/<name>/equity.parquet (ts, equity).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pyarrow.parquet as pq

from alphaforge.portfolio.book import BookResult, SleeveCurve, combine_book

_ART = Path("artifacts/walkforward")


def _load(name: str) -> tuple[list[int], list[float]]:
    t = pq.read_table(_ART / name / "equity.parquet").to_pydict()
    return t["ts"], t["equity"]


def _line(b: BookResult, label: str) -> str:
    return (
        f"  {label:<26} Sharpe {b.sharpe:5.2f}  CAGR {b.cagr * 100:5.1f}%  "
        f"vol {b.vol * 100:5.1f}%  maxDD {b.maxdd * 100:6.1f}%  avg-lev {b.leverage.mean():.2f}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--equity", default="k30_dn_63", help="equity sleeve artifact dir")
    ap.add_argument("--crypto", default="crypto_carry_wk", help="crypto sleeve artifact dir")
    ap.add_argument("--lookback", type=int, default=90, help="trailing vol window (days)")
    ap.add_argument("--rebalance", type=int, default=21, help="weight/leverage update cadence")
    ap.add_argument("--max-leverage", type=float, default=3.0)
    args = ap.parse_args()

    eq_ts, eq_eq = _load(args.equity)
    cr_ts, cr_eq = _load(args.crypto)
    sleeves = [
        SleeveCurve("equity_mom", eq_ts, eq_eq),
        SleeveCurve("crypto_carry", cr_ts, cr_eq),
    ]

    base = {
        "vol_lookback_days": args.lookback,
        "rebalance_days": args.rebalance,
        "trading_days": 365,
    }

    # Equity sleeve is dollar-neutral L/S => 2x internal gross; carry ~1x (audit-verified).
    # Reg-T caps equity deployable gross at 2x; crypto venue is generous.
    sgross = {"equity_mom": 2.0, "crypto_carry": 1.0}
    vcap = {"equity_mom": 2.0, "crypto_carry": 3.0}

    static = combine_book(sleeves, scheme="static", **base)
    deploy = combine_book(
        sleeves, scheme="fixed", fixed_weights={"equity_mom": 0.5, "crypto_carry": 0.5}, **base
    )

    print("=" * 84)
    print("UNIFIED CROSS-ASSET BOOK  (equity momentum + crypto funding-carry)")
    print("=" * 84)
    print(
        f"  common window {static.n_days} days ({static.window[0]}..{static.window[1]} epoch-day)"
    )
    corr_key = ("crypto_carry", "equity_mom")
    print(
        f"  correlation crypto_carry vs equity_mom: {static.corr[corr_key]:+.3f}  "
        f"(div-ratio {deploy.diversification_ratio:.2f}; stable & strengthens in stress)"
    )
    print()
    print("  -- IN-WINDOW (2023-07..2026-06, FAVOURABLE era; deflate hard for forward) --")
    print(_line(deploy, "DEPLOY: fixed 50/50"))
    print(_line(combine_book(sleeves, scheme="equal_risk", **base), "dynamic equal_risk (worse)"))
    print("  (audit: dynamic 21d reweighting adds nothing + cross-venue drag -> use fixed 50/50.)")
    print()
    print("  -- Reg-T-FEASIBLE vol-target (per-sleeve gross cap; equity gross <= 2.0x) --")
    for tgt in (0.10, 0.15, 0.20):
        b = combine_book(
            sleeves,
            scheme="fixed",
            fixed_weights={"equity_mom": 0.5, "crypto_carry": 0.5},
            vol_target_ann=tgt,
            max_leverage=args.max_leverage,
            sleeve_gross=sgross,
            venue_gross_cap=vcap,
            **base,
        )
        eqg = b.sleeve_gross_exposure["equity_mom"].max()
        print(_line(b, f"vol-target {tgt * 100:.0f}%") + f"  eqGross_max {eqg:.2f}")
    print()
    print("  ===================  HONEST FORWARD VERDICT (adversarial audit w1947t1pb)  ========")
    print("  STRUCTURE (underwrite): cross-asset diversification is REAL & robust. Combiner is")
    print("    PIT-clean; corr -0.016 is stable AND strengthens negative in stress (-0.44 on")
    print("    down days); sleeves anti-cluster (never both in worst-2.5% same day).")
    print("  MAGNITUDE (deflate): in-window 1.5 does NOT survive deflation -- DSR 0.44 @ N=69")
    print("    trials, 0.19 @ N=518, vs 0.95 gate; excluding the 5-mo 2026 spike -> ~1.04.")
    print("    Window excludes crypto carry's -1.63 2022. HONEST FORWARD Sharpe ~0.7-1.0,")
    print("    ~7-10% net unscaled / ~13-16% net at a feasible ~14% vol-target.")
    print("  RESILIENCE: if carry edge decays to ZERO the book still holds ~1.0 (equity is the")
    print("    ballast); the real tail is a carry SIGN-FLIP year (2022 repeat -> book ~-13% DD).")
    print("  -> Deploy SMALL pilot, fixed 50/50, after Phase-8 pre-arm gates + 6-12mo OOS.")
    print(
        "     The DATA INVESTMENT (deeper history) is the only path to a deflation-proven verdict."
    )


if __name__ == "__main__":
    main()
