"""Describe saved exposures and correlations; do not create a new strategy path."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-positive-exposure-20260913"
SOURCE = ROOT / "artifacts/analysis/alphatrend_positive_targets_20260913"
GROUPS = {
    "equity_ETFs": ["SPY", "QQQ", "IWM", "EFA", "EEM"],
    "Treasury_ETFs": ["SHY", "IEF", "TLT"],
    "commodity_ETFs": ["DBA", "DBC", "GLD", "SLV", "UNG", "USO"],
    "currency_ETFs": ["FXE", "FXY", "UUP"],
}
PERIODS = {
    "full": ("2015-01-01", "2026-09-12"),
    "covid_Q1": ("2020-01-01", "2020-03-31"),
    "year2022": ("2022-01-01", "2022-12-31"),
    "combined_window": ("2023-07-07", "2026-06-01"),
}


def main():
    hashes = {}

    def bind(path):
        hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()

    bind(Path(__file__))
    bind(OUT / "protocol.json")
    component_path = (
        ROOT / "evidence/alphac-algorithm-contributions-20260913/baseline_components.csv"
    )
    bind(component_path)
    components = pd.read_csv(component_path, index_col=0, parse_dates=True)
    group_rows, instrument_rows, correlations, variance = [], [], [], []
    for arm in ["baseline", "candidate", "baseline_stress", "candidate_stress"]:
        base = SOURCE / arm / "run"
        for name in ["equity", "positions"]:
            bind(base / f"{name}.parquet")
        equity = pd.read_parquet(base / "equity.parquet")
        positions = pd.read_parquet(base / "positions.parquet")
        assert not positions.duplicated(["ts", "instrument_id"]).any()
        weights = positions.pivot(index="ts", columns="instrument_id", values="weight")
        ids = ["XUSE:CASH:" + symbol + "USD" for symbols in GROUPS.values() for symbol in symbols]
        assert set(positions.instrument_id) <= set(ids)
        weights = weights.reindex(index=equity.ts, columns=ids).fillna(0)
        weights.index = pd.to_datetime(weights.index, unit="ms")
        for period, (start, end) in PERIODS.items():
            selected = weights.loc[start:end]
            assert len(selected) > 0
            for group, symbols in GROUPS.items():
                block = selected[["XUSE:CASH:" + symbol + "USD" for symbol in symbols]]
                group_rows.append(
                    {
                        "arm": arm,
                        "period": period,
                        "group": group,
                        "dates": len(block),
                        "mean_long": float(block.clip(lower=0).sum(axis=1).mean()),
                        "mean_short": float(-block.clip(upper=0).sum(axis=1).mean()),
                        "mean_net": float(block.sum(axis=1).mean()),
                    }
                )
            for iid in ids:
                instrument_rows.append(
                    {
                        "arm": arm,
                        "period": period,
                        "instrument": iid,
                        "mean_net": float(selected[iid].mean()),
                        "mean_gross": float(selected[iid].abs().mean()),
                    }
                )
        series = pd.Series(equity.equity.to_numpy(), index=pd.to_datetime(equity.ts, unit="ms"))
        daily = series.reindex(pd.date_range(series.index.min(), series.index.max())).ffill()
        trend = daily.pct_change().reindex(components.index)
        assert trend.notna().all()
        book = components.drop(columns="managed_futures").copy()
        for col in book:
            if col != "strategic_overlay":
                book[col] *= 0.9
        book["trend"] = 0.225 * trend
        for col in book.columns.drop("trend"):
            correlations.append(
                {
                    "arm": arm,
                    "component": col,
                    "observations": len(book),
                    "pearson_calendar": float(book.trend.corr(book[col])),
                    "pearson_sessions": float(
                        book.loc[series.index.intersection(book.index), "trend"].corr(
                            book.loc[series.index.intersection(book.index), col]
                        )
                    ),
                }
            )
        total = book.sum(axis=1)
        retained_path = (
            ROOT
            / "artifacts/analysis/alphac_positive_targets_20260913_attempt2"
            / arm
            / "daily.csv"
        )
        bind(retained_path)
        retained = pd.read_csv(retained_path, index_col=0, parse_dates=True)
        assert np.max(np.abs(total - retained.total)) < 1e-12
        shares = []
        for col in book:
            share = float(book[col].cov(total) / total.var(ddof=1))
            shares.append(share)
            variance.append(
                {
                    "arm": arm,
                    "component": col,
                    "covariance_share": share,
                    "mean_daily_contribution": float(book[col].mean()),
                }
            )
        assert abs(sum(shares) - 1) < 1e-12
    for name, rows in [
        ("group_exposures", group_rows),
        ("instrument_exposures", instrument_rows),
        ("correlations", correlations),
        ("variance_contributions", variance),
    ]:
        pd.DataFrame(rows).to_csv(OUT / f"{name}.csv", index=False)
    (OUT / "verification.json").write_text(
        json.dumps(
            {
                "source_sha256": hashes,
                "combined_paths_reconciled": True,
                "covariance_shares_sum_to_one": True,
                "new_strategy_returns": False,
                "limits": "Descriptive in-sample exposures, not causal factors, "
                "independent sleeves or OOS proof. "
                "Zero-filled nonsessions reported alongside session-only correlations. "
                "No combined COVID/2022 history available.",
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
