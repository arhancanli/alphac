"""Independently reconcile saved crypto control; computes no new strategy paths."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/analysis/crypto_terminal_comparison_20260913_attempt2"
ARM = OUT / "original_close_control"
HOUR = 3600000


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    meta = json.loads((ARM / "run/walkforward.json").read_text())
    residuals = []
    initial = 100000.0
    for leg in meta["legs"]:
        directory = ARM / f"run/legs/leg_{leg['leg']:02d}"
        equity = pd.read_parquet(directory / "equity.parquet").set_index("ts").equity
        fills = pd.read_parquet(directory / "fills.parquet")
        funding = pd.read_parquet(directory / "funding.parquet")
        positions = pd.read_parquet(directory / "positions.parquet")
        expected_grid = np.arange(leg["test_start"] + HOUR, leg["test_end"] + 1, HOUR)
        np.testing.assert_array_equal(equity.index.to_numpy(), expected_grid)
        # Ordinary fills at next-bar open enter the following close snapshot.
        fill_cash = (fills.realized_pnl_quote - fills.fee).groupby(fills.ts + HOUR).sum()
        funding_close = ((funding.ts_funding + HOUR - 1) // HOUR) * HOUR
        funding_cash = funding.payment_quote.groupby(funding_close).sum()
        realized = fill_cash.reindex(equity.index, fill_value=0).cumsum()
        funded = funding_cash.reindex(equity.index, fill_value=0).cumsum()
        unrealized = positions.groupby("ts").unreal_pnl.sum().reindex(equity.index, fill_value=0)
        reconstructed = initial + realized + funded + unrealized
        residual = float((equity - reconstructed).abs().max())
        assert residual < 1e-6, residual
        residuals.append(
            {"leg": leg["leg"], "snapshots": len(equity), "max_abs_residual": residual}
        )
        initial = float(equity.iloc[-1])
    curve = pd.read_parquet(ARM / "run/equity.parquet").set_index("ts").equity
    daily = curve.groupby(curve.index // (24 * HOUR)).last()
    returns = daily.pct_change().dropna()
    observed = float(returns.mean() / returns.std(ddof=1) * np.sqrt(365))
    assert abs(observed - meta["summary"]["sharpe"]) < 1e-12
    dd = float((1 - daily / daily.cummax()).max())
    assert abs(dd - meta["summary"]["max_dd"]) < 1e-12
    report = {
        "status": "SAVED_CONTROL_RECONCILED",
        "legs": residuals,
        "daily_raw_sharpe": observed,
        "daily_max_drawdown": dd,
        "final_equity": initial,
        "net_excess_sharpe": None,
        "net_excess_limitation": "Benchmark adjustment pending; raw Sharpe not excess Sharpe.",
        "source_sha256": {
            str(p.relative_to(ROOT)): sha(p) for p in sorted((ARM / "run").rglob("*.parquet"))
        },
        "qualified": False,
    }
    (ARM / "independent_audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "source_sha256"}))


if __name__ == "__main__":
    main()
