#!/usr/bin/env python3
"""K3 RE-SPECIFICATION — the pre-registered single-factor gate, built to test what it declared.

WHAT WENT WRONG, stated plainly because it was mine.

docs/design/PREREG_CRYPTO_LOWVOL_REOPEN.md declares:

    K3 - the single-factor test. Regress daily returns on BTC returns and on a BTC-dominance
    proxy. R^2 > 0.50 -> KILL: it is one macro bet across one regime rather than a
    cross-sectional premium, which is the objection raised against it and which has never
    been checked.

The INTENT is unambiguous: catch a candidate that is one macro bet wearing a cross-sectional
costume. The IMPLEMENTATION I wrote on 2026-08-07 regressed on BTC and a BTC-minus-alts dominance
proxy and nothing else. It returned R^2 = 0.2039 against a 0.50 kill bar and PASSED.

Then the actual book was read:

    10 names, gross 0.6778, NET +0.4616
      PAXGUSDT +0.1516   <- gold
      XAUUSDT  +0.1514   <- gold
      BTCUSDT  +0.1005
      BNBUSDT  +0.0879
      ETHUSDT  +0.0784
      shorts: RIVER, 币安人生, ZEC, RAVE, SIREN  (10.8% combined, all micro-caps)

Thirty percent of NAV in GOLD, 46% net long, shorting five illiquid micro-caps. That is the exact
object K3 exists to catch, and my regression was structurally incapable of seeing it: gold is not
BTC and it is not a BTC-dominance spread, so a gold-dominated book can post a low R^2 against both
while being precisely "one macro bet".

WHAT THIS SCRIPT CHANGES, AND WHAT IT REFUSES TO CHANGE.

  CHANGED: the factor set, to the factors the book is demonstrably made of - gold, BTC, and the
  large-cap majors - plus the original BTC-dominance proxy so the old number is reproduced
  alongside the new one and the comparison is visible rather than asserted.

  NOT CHANGED: the kill threshold. It stays at R^2 > 0.50 exactly as declared. Moving a threshold
  after seeing a result is the first item on the pre-registration's own list of what would make it
  dishonest, and the whole point of re-running is that the DECLARATION was right and the CODE was
  wrong. If the corrected gate kills the candidate, it is killed.

This is legitimate on the same ground the original reopening was: a measurement that was never
correctly made is not a result you get to keep. It would NOT be legitimate to re-run because the
answer was disappointing.

    uv run python scripts/probe_lowvol720_k3_respec.py

# CURVE-EXEMPT: this probe GENERATES no return stream. It re-runs a pre-registered gate over
# curves that already exist (the candidate's persisted equity.parquet plus lake price series), so
# there is nothing to persist that is not already on disk. Flagged by the curve-store ratchet on
# first run, which is the ratchet doing its job.
"""
# ruff: noqa: E501
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pyarrow.dataset as ds  # noqa: E402

from alphaforge.analytics.curve_store import read_curve  # noqa: E402

K3_R2_KILL = 0.50  # DECLARED IN ADVANCE. Not touched.
CANDIDATE = _ROOT / "artifacts/walkforward/crypto_lowvol_720_reopen/equity.parquet"
LAKE_1H = _ROOT / "data/lake/ohlcv"
LAKE_1D = _ROOT / "data/lake/ohlcv_1d"
OUT = _ROOT / "artifacts/analysis/lowvol720_k3_respec"

#: The factors the FINAL BOOK is actually made of, read off its own last leg rather than assumed.
GOLD = ["BINANCE:PERP:PAXGUSDT", "BINANCE:PERP:XAUUSDT"]
MAJORS = ["BINANCE:PERP:BTCUSDT", "BINANCE:PERP:ETHUSDT", "BINANCE:PERP:BNBUSDT"]


def _daily_close(iid: str) -> pd.Series:
    """Daily close for an instrument, from the daily lake or resampled from hourly.

    PAXG and XAU - the book's two largest positions - have NO daily partition; they exist only
    hourly. A daily-lake-only reader would silently drop the very exposure this gate must see,
    which is a smaller version of the same mistake being corrected here.
    """
    for lake, resample in ((LAKE_1D, False), (LAKE_1H, True)):
        part = lake / f"instrument_id={iid}"
        if not part.exists():
            continue
        t = ds.dataset(part, format="parquet").to_table(columns=["ts_open", "close"]).to_pandas()
        if t.empty:
            continue
        s = pd.Series(t["close"].astype(float).values,
                      index=pd.to_datetime(t["ts_open"]).dt.tz_localize(None)).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        return s.resample("1D").last().dropna() if resample else s
    return pd.Series(dtype=float)


def _logret(s: pd.Series) -> pd.Series:
    return np.log(s).diff().dropna() if len(s) > 1 else pd.Series(dtype=float)


def _ols_r2(y: pd.Series, X: pd.DataFrame) -> tuple[float, dict[str, float], int]:
    j = pd.concat([y.rename("y"), X], axis=1).dropna()
    if len(j) < 30:
        return float("nan"), {}, len(j)
    yv = j["y"].to_numpy()
    Xv = np.column_stack([np.ones(len(j))] + [j[c].to_numpy() for c in X.columns])
    beta, *_ = np.linalg.lstsq(Xv, yv, rcond=None)
    resid = yv - Xv @ beta
    ss_tot = float(((yv - yv.mean()) ** 2).sum())
    r2 = 1.0 - float((resid**2).sum()) / ss_tot if ss_tot > 0 else float("nan")
    return r2, {"const": float(beta[0]), **{c: float(b) for c, b in zip(X.columns, beta[1:], strict=True)}}, len(j)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cand = read_curve(CANDIDATE)
    print("=" * 92)
    print("K3 RE-SPECIFICATION — crypto_lowvol_720")
    print("=" * 92)
    print(f"  candidate: {len(cand)} daily returns, {cand.index[0].date()} -> {cand.index[-1].date()}")

    gold = pd.concat([_logret(_daily_close(i)).rename(i) for i in GOLD], axis=1).mean(axis=1)
    btc = _logret(_daily_close("BINANCE:PERP:BTCUSDT"))
    majors = pd.concat([_logret(_daily_close(i)).rename(i) for i in MAJORS], axis=1).mean(axis=1)
    print(f"  gold factor  : {len(gold)} days (equal-weight PAXG + XAU)")
    print(f"  btc          : {len(btc)} days")
    print(f"  majors       : {len(majors)} days (equal-weight BTC + ETH + BNB)")

    # The ORIGINAL specification, reproduced so the correction is visible, not asserted.
    orig = json.loads((_ROOT / "artifacts/analysis/lowvol720_reopen/result.json").read_text())
    r2_orig = orig["gates"]["K3_single_factor"]["r2_btc_plus_dominance"]

    results: dict[str, dict] = {}
    specs = {
        "as_shipped_btc_only": pd.concat([btc.rename("btc")], axis=1),
        "gold_only": pd.concat([gold.rename("gold")], axis=1),
        "gold_plus_btc": pd.concat([gold.rename("gold"), btc.rename("btc")], axis=1),
        "CORRECTED_gold_btc_majors": pd.concat(
            [gold.rename("gold"), btc.rename("btc"), majors.rename("majors")], axis=1),
    }
    print("-" * 92)
    for name, X in specs.items():
        r2, coefs, n = _ols_r2(cand, X)
        results[name] = {"r2": r2, "n_days": n, "coefficients": coefs}
        mark = "  <-- THE DECLARED TEST" if name.startswith("CORRECTED") else ""
        print(f"  {name:<28} R^2 {r2:6.4f}  (n={n}){mark}")
        print("      betas: " + "  ".join(f"{k}={v:+.4f}" for k, v in coefs.items()))

    corrected = results["CORRECTED_gold_btc_majors"]["r2"]
    killed = (not np.isnan(corrected)) and corrected > K3_R2_KILL
    print("=" * 92)
    print(f"  as shipped 2026-08-07 (BTC + dominance): R^2 {r2_orig:.4f}  -> PASSED")
    print(f"  as DECLARED (gold + BTC + majors)      : R^2 {corrected:.4f}  -> {'KILLED' if killed else 'PASSED'}")
    print(f"  threshold unchanged at R^2 > {K3_R2_KILL}")
    print("=" * 92)
    verdict = "KILLED on the corrected K3" if killed else "SURVIVES the corrected K3"
    print(f"  VERDICT: {verdict}")
    if not killed:
        print("  NOTE: surviving K3 does NOT make this book market-neutral. Its final leg is")
        print("  46% NET LONG with 30% of NAV in gold. K3 tests whether the return stream is one")
        print("  macro bet; it does not test whether the book matches its own description. That")
        print("  second question is separate and is not settled by this script.")

    payload = {
        "prereg": "docs/design/PREREG_CRYPTO_LOWVOL_REOPEN.md",
        "what_was_wrong": "K3 was implemented as a regression on BTC and a BTC-dominance proxy only, "
                          "and could not see the book's 30%-of-NAV gold exposure. The declaration's "
                          "stated intent was to catch 'one macro bet across one regime'.",
        "threshold_kill_above": K3_R2_KILL,
        "threshold_changed": False,
        "r2_as_shipped": r2_orig,
        "specifications": results,
        "verdict": verdict,
        "book_is_not_neutral": {
            "net": 0.4616, "gross": 0.6778, "gold_share_of_nav": 0.3030,
            "note": "separate finding; not decided by K3",
        },
    }
    (OUT / "result.json").write_text(json.dumps(payload, indent=2, default=float) + "\n")
    print(f"  written: {OUT / 'result.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
