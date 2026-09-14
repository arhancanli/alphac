"""Reconcile saved instrument P&L including modeled borrow; no strategy variants."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/analysis/alphatrend_positive_targets_20260913"
OUT = ROOT / "evidence/alphatrend-positive-attribution-20260913"


def main():
    OUT.mkdir(exist_ok=False)
    hashes = {}
    results, rows = {}, []
    for arm in ["baseline", "candidate", "baseline_stress", "candidate_stress"]:
        directory = SOURCE / arm

        def read(name, directory=directory):
            path = directory / "run" / (name + ".parquet")
            hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
            return pd.read_parquet(path)

        equity, positions, fills, actions = [
            read(n) for n in ["equity", "positions", "fills", "corporate_actions"]
        ]
        meta_path = directory / "run/run_meta.json"
        res_path = directory / "reservation.json"
        for path in [meta_path, res_path]:
            hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        config = json.loads(meta_path.read_text())["config"]
        costs = json.loads(res_path.read_text())["trial_config"]["resolved_settings"]["costs"]
        ts = equity.ts.to_numpy()
        ids = sorted(positions.instrument_id.unique())
        assert set(fills.reason) == {"target_weight"}
        assert not positions.duplicated(["ts", "instrument_id"]).any()

        def panel(frame, value, time, ts=ts, ids=ids):
            return (
                frame.pivot_table(index=time, columns="instrument_id", values=value, aggfunc="sum")
                .reindex(index=ts, columns=ids)
                .fillna(0)
            )

        unreal = panel(positions, "unreal_pnl", "ts")
        from alphaforge.core.calendar import XNYSCalendar
        from alphaforge.core.time import Timeframe

        cal = XNYSCalendar()
        previous = np.array([cal.floor_bar(int(t) - 1, Timeframe.D1) for t in ts])
        price_path = (
            ROOT / "evidence/alphatrend-retrospective-execution-20260912/paired_prices.parquet"
        )
        hashes[str(price_path.relative_to(ROOT))] = hashlib.sha256(
            price_path.read_bytes()
        ).hexdigest()
        raw = pd.read_parquet(price_path).pivot(
            index="session_ms", columns="symbol", values="raw_open"
        )
        raw.columns = ["XUSE:CASH:" + symbol + "USD" for symbol in raw.columns]
        opens = raw.reindex(index=previous, columns=ids)
        opens.index = ts
        quantity = panel(positions, "qty", "ts")
        assert not (opens.isna() & (quantity != 0)).any().any()
        gaps = pd.Series((ts - previous) / 86400000, index=ts)
        borrow = quantity.clip(upper=0).mul(opens.fillna(0)).mul(gaps, axis=0)
        borrow *= costs["equity_borrow_bps_annual"] * 1e-4 / 365
        assert abs(float(borrow.to_numpy().sum()) - config["borrow_total"]) < 1e-6
        # Queued target fills at bar-open are first included in the NEXT equity snapshot.
        indices = np.searchsorted(ts, fills.ts.to_numpy(), side="right")
        assert (indices < len(ts)).all()
        fills["snapshot_ts"] = ts[indices]
        realized = panel(fills, "realized_pnl_quote", "snapshot_ts")
        fees = panel(fills, "fee", "snapshot_ts")
        indices = np.searchsorted(ts, actions.action_ts.to_numpy(), side="right")
        assert (indices < len(ts)).all()
        actions["snapshot_ts"] = ts[indices]
        dividends = panel(actions, "cashflow_quote", "snapshot_ts")
        cumulative = (realized - fees + dividends + borrow).cumsum() + unreal
        residual = cumulative.sum(axis=1).to_numpy() - (
            equity.equity.to_numpy() - config["initial_cash"]
        )
        error = float(np.abs(residual).max())
        assert error < 1e-6, (arm, error, int(ts[np.argmax(np.abs(residual))]))
        delta = cumulative.diff().fillna(cumulative.iloc[0])
        dates = pd.to_datetime(ts, unit="ms")
        for period, start, end in [
            ("full", "2015-01-01", "2026-09-12"),
            ("covid_Q1", "2020-01-01", "2020-03-31"),
            ("year2022", "2022-01-01", "2022-12-31"),
            ("combined_window", "2023-07-07", "2026-06-01"),
        ]:
            mask = (dates >= start) & (dates <= end)
            for iid in ids:
                rows.append(
                    {
                        "arm": arm,
                        "period": period,
                        "instrument": iid,
                        "net_pnl": float(delta.loc[mask, iid].sum()),
                        "borrow": float(borrow.loc[mask, iid].sum()),
                        "fees": float(fees.loc[mask, iid].sum()),
                        "action_cashflow": float(dividends.loc[mask, iid].sum()),
                    }
                )
        cumulative.to_parquet(OUT / f"{arm}_cumulative_pnl.parquet")
        borrow.to_parquet(OUT / f"{arm}_borrow.parquet")
        results[arm] = {
            "max_daily_equity_residual": error,
            "borrow_total": float(borrow.to_numpy().sum()),
            "equity_gain": float(cumulative.iloc[-1].sum()),
        }
    pd.DataFrame(rows).to_csv(OUT / "instrument_pnl.csv", index=False)
    for path in [
        Path(__file__),
        ROOT / "src/alphaforge/backtest/payable_engine.py",
        ROOT / "src/alphaforge/costs/model.py",
    ]:
        hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (OUT / "verification.json").write_text(
        json.dumps(
            {"arms": results, "source_sha256": hashes, "new_strategy_returns": False}, indent=2
        )
        + "\n"
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
