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

    static = combine_book(sleeves, scheme="static", **base)
    pit = combine_book(sleeves, scheme="equal_risk", **base)

    print("=" * 84)
    print("UNIFIED CROSS-ASSET BOOK  (equity momentum + crypto funding-carry)")
    print("=" * 84)
    print(
        f"  common window {static.n_days} days ({static.window[0]}..{static.window[1]} epoch-day)"
    )
    corr_key = ("crypto_carry", "equity_mom")
    print(
        f"  correlation crypto_carry vs equity_mom: {static.corr[corr_key]:+.3f}  "
        f"(diversification ratio {pit.diversification_ratio:.2f})"
    )
    print(f"  theory ceiling sqrt(Sum Sharpe^2) = {static.sharpe_theory_uncorr:.2f}")
    print()
    print("  -- unscaled (1x) --")
    print(_line(static, "static full-sample*"))
    print(_line(pit, "PIT trailing-vol (DEPLOY)"))
    print("  * static uses full-sample vol for weights = mild hindsight; the PIT line is honest.")
    print()
    print(f"  -- PIT + book-level vol-target (max-leverage {args.max_leverage:g}x) --")
    for tgt in (0.10, 0.15, 0.20, 0.25):
        b = combine_book(
            sleeves,
            scheme="equal_risk",
            vol_target_ann=tgt,
            max_leverage=args.max_leverage,
            **base,
        )
        print(_line(b, f"vol-target {tgt * 100:.0f}%"))
    print()
    print("  HONESTY: window is crypto-carry's FAVOURABLE era (excludes the 2022 funding-")
    print("  inversion bear, Sharpe -1.6 there). Carry is structurally DECAYING (funding")
    print("  dispersion 82%->18%/yr). Leverage for 20-25% is real (~2.5x) with real tail")
    print("  risk. Forward expectation: conservative (~1.0-1.2 Sharpe). Deeper history (the")
    print("  data investment) is what converts this from strong-in-sample to deflation-proven.")


if __name__ == "__main__":
    main()
