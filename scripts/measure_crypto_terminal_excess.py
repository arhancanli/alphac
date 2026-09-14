"""Benchmark saved curves with the previously fixed lagged DFF diagnostic policy."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/analysis/crypto_terminal_comparison_20260913_attempt2"
SOURCE = ROOT / "evidence/alphac-capital-budget-20260913/DFF.parquet"
SPEC = SOURCE.parent / "EXPERIMENT_SPEC.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    spec = json.loads(SPEC.read_text())
    expected = "f591aa86f5058cb75d319a2b64d83983fc82b78a22c28c3f33d72e5dc971aa27"
    assert sha(SOURCE) == expected
    rates = pd.read_parquet(SOURCE).sort_values(["publication_date", "obs_date"])
    rates = rates.drop_duplicates("publication_date", keep="last")
    summaries = []
    for completion in sorted(OUT.glob("*/execution_complete.json")):
        arm = completion.parent
        target = arm / "excess_benchmark_audit.json"
        if target.exists():
            continue
        path = arm / "run/equity.parquet"
        equity = pd.read_parquet(path).set_index("ts").equity
        dates = pd.to_datetime(equity.index, unit="ms").normalize()
        daily = equity.groupby(dates).last()
        returns = daily.pct_change().dropna()
        aligned = pd.merge_asof(
            pd.DataFrame({"day": returns.index}),
            rates,
            left_on="day",
            right_on="publication_date",
            direction="backward",
            allow_exact_matches=False,
        )
        ages = (aligned.day - aligned.obs_date).dt.days
        assert aligned.value.notna().all() and ages.between(0, 7).all()
        rf = aligned.value.to_numpy() / 100 / 360
        excess = returns.to_numpy() - rf
        metric = float(excess.mean() / excess.std(ddof=1) * np.sqrt(365))
        report = {
            "arm": arm.name,
            "daily_observations": len(excess),
            "net_excess_sharpe_DFF_proxy": metric,
            "benchmark_rule": spec["benchmark_rule"],
            "equity_sha256": sha(path),
            "benchmark_sha256": sha(SOURCE),
            "policy_sha256": sha(SPEC),
            "qualification": False,
            "limitations": ("Current-vintage DFF, modeled publication dates and USD benchmark "
                            "on USDT-denominated crypto accounting; no verified collateral yield, "
                            "financing or USDT/USD conversion."),
        }
        with target.open("x") as f:
            json.dump(report, f, indent=2)
            f.write("\n")
        pd.DataFrame(
            {"day": returns.index, "total": returns.to_numpy(), "benchmark": rf, "excess": excess}
        ).to_csv(arm / "excess_benchmark_days.csv", index=False)
        summaries.append({"arm": arm.name, "net_excess_sharpe_DFF_proxy": metric})
    print(json.dumps(summaries))


if __name__ == "__main__":
    main()
