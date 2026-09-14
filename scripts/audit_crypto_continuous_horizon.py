"""Verify complete calendar-year2022 returns from saved corrected replay observations."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from alphaforge.validation.research_horizon import require_horizon

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/analysis/crypto_continuous_account_20260913"
DFF = ROOT / "evidence/alphac-capital-budget-20260913/DFF.parquet"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("arm")
    directory = OUT / parser.parse_args().arm
    path = directory / "run/equity.parquet"
    equity = pd.read_parquet(path).set_index("ts").equity
    dates = pd.date_range("2023-01-02 00:00", "2026-06-02 00:00", freq="D", tz="UTC")
    expected = [int(t.timestamp() * 1000) for t in dates]
    predecessor = int(pd.Timestamp("2023-01-01 00:00", tz="UTC").timestamp() * 1000)
    # Explicit initial cash deposit, not a fictitious observed predecessor mark.
    wf=json.loads((directory/'run/walkforward.json').read_text())
    assert wf['legs'][0]['test_start']==predecessor
    assert wf['legs'][0]['summary']['initial_equity']==22500.0
    assert equity.index.min()==predecessor+3600000 and predecessor not in equity.index
    assert set(expected).issubset(equity.index)
    year_curve=pd.concat([pd.Series([22500.0],index=[predecessor]),equity.loc[expected]])
    returns = year_curve.pct_change().dropna()
    assert len(returns) == 1248
    assert sha(DFF) == "f591aa86f5058cb75d319a2b64d83983fc82b78a22c28c3f33d72e5dc971aa27"
    rates = (
        pd.read_parquet(DFF)
        .sort_values(["publication_date", "obs_date"])
        .drop_duplicates("publication_date", keep="last")
    )
    days = pd.DataFrame({"day": dates.tz_localize(None).normalize() - pd.Timedelta(days=1)})
    days["day"] = days["day"].astype("datetime64[ms]")
    rates["publication_date"] = rates["publication_date"].astype("datetime64[ms]")
    aligned = pd.merge_asof(
        days,
        rates,
        left_on="day",
        right_on="publication_date",
        direction="backward",
        allow_exact_matches=False,
    )
    assert (
        aligned.value.notna().all() and (aligned.day - aligned.obs_date).dt.days.between(0, 7).all()
    )
    benchmark = aligned.value.to_numpy() / 100 / 360
    excess = returns.to_numpy() - benchmark
    before = float(year_curve.iloc[0])
    after = float(year_curve.iloc[-1])
    frame = pd.DataFrame(
        {
            "day": days.day,
            "equity": year_curve.iloc[1:].to_numpy(),
            "return": returns.to_numpy(),
            "benchmark": benchmark,
            "excess": excess,
        }
    )
    frame.to_csv(directory / "calendar2023_2026.csv", index=False)
    result = {
        "status": "COMPLETE_FULL_UTC_DAYS_WITH_ACTUAL_INITIAL_CASH_DEPOSIT",
        "observations": 1248,
        "coverage_complete": True,
        "predecessor_ts": predecessor,
        "initial_cash_deposit": before,
        "final_equity": after,
        "total_return": after / before - 1,
        "CAGR_365day": (after / before)**(365/len(returns)) - 1,
        "raw_sharpe": float(returns.mean() / returns.std(ddof=1) * np.sqrt(365)),
        "net_excess_sharpe_DFF_proxy": float(excess.mean() / excess.std(ddof=1) * np.sqrt(365)),
        "max_drawdown": float((1 - year_curve / year_curve.cummax()).max()),
        "equity_sha256": sha(path),
        "benchmark_sha256": sha(DFF),
        "daily_csv_sha256": sha(directory / "calendar2023_2026.csv"),
        "qualification": False,
        "limitations": ("Current-vintage USD DFF against USDT accounting; modeled publication, "
                            "metadata applicability, funding marks, settlement and notice timing. "
                            "Engine whole-run summaries use their own day grouping; this funded report includes all1248calendar returns from the explicit22500deposit. Independent quantity/impact audit remains required."),
    }
    with (directory / "calendar2023_2026_audit.json").open("x") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
