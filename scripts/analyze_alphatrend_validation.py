"""Frozen exposure and uncertainty diagnostics for the retained parent trial."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "artifacts/analysis/alphatrend_directional_20260912_attempt2"
OUT = ROOT / "artifacts/analysis/alphatrend_directional_validation_20260912"


def hac_ols(y, factors, lags=21):
    """OLS with Bartlett Newey-West sandwich, n/(n-k) finite-sample adjustment."""
    y, factors = np.asarray(y, dtype=float), np.asarray(factors, dtype=float)
    x = np.column_stack([np.ones(len(y)), factors])
    n, k = x.shape
    if n <= k + lags or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Invalid regression sample")
    if np.linalg.matrix_rank(x) != k:
        raise ValueError("Rank-deficient regression")
    coef = np.linalg.lstsq(x, y, rcond=None)[0]
    residual = y - x @ coef
    score = x * residual[:, None]
    meat = score.T @ score
    for lag in range(1, lags + 1):
        cross = score[lag:].T @ score[:-lag]
        meat += (1 - lag / (lags + 1)) * (cross + cross.T)
    bread = np.linalg.inv(x.T @ x)
    covariance = (bread @ meat @ bread) * (n / (n - k))
    se = np.sqrt(np.maximum(np.diag(covariance), 0))
    return {
        "coefficients": coef.tolist(),
        "standard_errors": se.tolist(),
        "intercept_annualized_arithmetic": float(252 * coef[0]),
        "intercept_95_interval_annualized": (
            252 * (coef[0] + np.array([-1, 1]) * 1.96 * se[0])
        ).tolist(),
        "r_squared": float(1 - residual @ residual / np.sum((y - y.mean()) ** 2)),
        "observations": n,
    }


def paired_interval(returns, draws=2000):
    arr = np.asarray(returns, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 2 or len(arr) < 126 or not np.isfinite(arr).all():
        raise ValueError("Need paired finite baseline/candidate returns")
    rng = np.random.default_rng(20260912)
    n = len(arr)
    differences = []
    for _ in range(draws):
        starts = rng.integers(0, n, size=int(np.ceil(n / 63)))
        indices = ((starts[:, None] + np.arange(63)) % n).ravel()[:n]
        sample = arr[indices]
        sr = np.sqrt(252) * sample.mean(axis=0) / sample.std(axis=0, ddof=1)
        differences.append(float(sr[1] - sr[0]))
    return np.quantile(differences, [0.025, 0.975]).tolist()


def align_factors(bars):
    """Actual close at bar t is marked in engine equity at t + one UTC day."""
    if bars.duplicated(["ts_open", "instrument_id"]).any():
        raise ValueError("Duplicate factor prices")
    panel = bars.pivot(index="ts_open", columns="instrument_id", values="close").sort_index()
    returns = panel.pct_change(fill_method=None)
    returns.index = returns.index + 86400000
    return returns


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    for arm, row in protocol["input_bindings"].items():
        assert (
            hashlib.sha256((PARENT / arm / "equity.parquet").read_bytes()).hexdigest()
            == row["equity"]
        )
    frames = {}
    for arm in ["baseline", "candidate"]:
        eq = pd.read_parquet(PARENT / arm / "equity.parquet").set_index("ts").equity
        if eq.index.has_duplicates or not eq.index.is_monotonic_increasing:
            raise ValueError("Invalid equity timestamps")
        frames[arm] = eq.pct_change(fill_method=None)
    returns = pd.DataFrame(frames).dropna()
    factors = ["SPY", "IEF", "GLD", "UUP"]
    pieces = []
    raw = PARENT / "candidate/input_snapshot/raw_partitions/ohlcv_1d"
    for ticker in factors:
        for p in sorted((raw / f"instrument_id=XUSE:CASH:{ticker}USD").rglob("*.parquet")):
            pieces.append(pd.read_parquet(p)[["instrument_id", "ts_open", "close"]])
    bars = pd.concat(pieces, ignore_index=True)
    bars["ts_open"] = bars.ts_open.dt.as_unit("ms").astype("int64")
    bars = bars.loc[bars.ts_open < 1787529600000]
    f = align_factors(bars)
    f.columns = [c.split(":")[-1][:-3] for c in f.columns]
    joined = returns.join(f[factors]).dropna()
    joined["difference"] = joined.candidate - joined.baseline
    regression = {
        name: hac_ols(joined[name], joined[factors])
        for name in ["baseline", "candidate", "difference"]
    }
    for item in regression.values():
        item["coefficient_names"] = ["intercept", *factors]
    eras = []
    years = pd.to_datetime(returns.index, unit="ms", utc=True).year
    for start, end in [(2006, 2012), (2013, 2019), (2020, 2026)]:
        group = returns.loc[(years >= start) & (years <= end)]
        row = {"era": f"{start}-{end}", "observations": len(group)}
        for arm in ["baseline", "candidate"]:
            r = group[arm]
            row[arm] = {
                "sharpe": float(np.sqrt(252) * r.mean() / r.std(ddof=1)),
                "annualized_geometric_return_252": float(np.expm1(np.log1p(r).mean() * 252)),
                "total_return": float(np.expm1(np.log1p(r).sum())),
            }
        eras.append(row)
    result = {
        "parent_sharpe_difference_95_block_interval": paired_interval(returns),
        "parent_return_observations": len(returns),
        "regression": regression,
        "regression_first_date": str(pd.to_datetime(joined.index.min(), unit="ms").date()),
        "regression_last_date": str(pd.to_datetime(joined.index.max(), unit="ms").date()),
        "regression_dropped_for_incomplete_factors": len(returns) - len(joined),
        "eras": eras,
        "limits": "Same inspected development data; no multiple-testing-adjusted significance. "
        "OLS is descriptive exposure association, not causal attribution or tradable hedging. "
        "Raw-return intercept is not excess alpha. UUP inception restricts complete cases.",
    }
    joined.to_parquet(OUT / "exposure_observations.parquet")
    with (OUT / "exposure_results.json").open("x") as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
