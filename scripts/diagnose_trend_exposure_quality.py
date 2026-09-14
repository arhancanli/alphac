"""Inspect saved paths, without running signals, strategies, or new return trials."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/analysis/alphatrend_retrospective_comparison_20260912"
OUT = ROOT / "evidence/alphatrend-exposure-quality-20260913"


def main():
    hashes = {}

    def bind(path):
        hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()

    def read(path):
        bind(path)
        return pd.read_parquet(path)

    prior = json.loads(
        (
            ROOT / "evidence/alphatrend-retrospective-attribution-20260912/attribution.json"
        ).read_text()
    )
    for path, digest in prior["source_sha256"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
    bind(OUT / "protocol.json")
    bind(Path(__file__))
    bind(ROOT / "src/alphaforge/portfolio/optimizer.py")
    bind(ROOT / "src/alphaforge/portfolio/strategy.py")
    cal = XNYSCalendar()
    results = {}
    instruments = []
    for arm in ("baseline", "candidate"):
        base = SOURCE / arm
        signals = read(base / "signals.parquet").reset_index()
        pos = read(base / "run/positions.parquet")
        equity = read(base / "run/equity.parquet")
        orders = read(base / "run/orders.parquet")
        assert not signals.duplicated(["ts_open", "instrument_id"]).any()
        assert not pos.duplicated(["ts", "instrument_id"]).any()
        assert not equity.ts.duplicated().any()
        ids = sorted(signals.instrument_id.unique())
        weights = pos.pivot(index="ts", columns="instrument_id", values="weight")
        weights = weights.reindex(index=equity.ts, columns=ids).fillna(0)
        assert len(ids) == 17
        daily = pd.DataFrame(
            {
                "gross": weights.abs().sum(axis=1),
                "net": weights.sum(axis=1),
                "short": -weights.clip(upper=0).sum(axis=1),
            }
        )
        daily.to_csv(OUT / f"{arm}_exposure.csv")
        for iid in ids:
            instruments.append(
                {
                    "arm": arm,
                    "instrument": iid,
                    "mean_abs_weight": float(weights[iid].abs().mean()),
                    "mean_signed_weight": float(weights[iid].mean()),
                    "short_date_fraction": float((weights[iid] < 0).mean()),
                }
            )
        ts_map = {
            int(t): cal.floor_bar(int(t) - 1, Timeframe.D1)
            for t in set(orders.decision_ts) | set(pos.ts)
        }
        orders["ts_open"] = orders.decision_ts.map(ts_map)
        joined = orders.merge(
            signals, on=["ts_open", "instrument_id"], how="left", validate="many_to_one"
        )
        joined = joined.merge(
            equity.rename(columns={"ts": "decision_ts"}),
            on="decision_ts",
            how="left",
            validate="many_to_one",
        )
        joined["decision_notional_fraction"] = (
            joined.qty.abs() * joined.decision_price / joined.equity
        )
        assert joined.equity.notna().all()
        filled = joined.loc[joined.status == "filled"].copy()
        finite = filled.loc[np.isfinite(filled.mu_ann)].copy()
        total = float(finite.decision_notional_fraction.sum())
        pos["ts_open"] = pos.ts.map(ts_map)
        aligned = pos.merge(
            signals, on=["ts_open", "instrument_id"], how="left", validate="many_to_one"
        )
        usable = aligned.loc[np.isfinite(aligned.mu_ann) & (aligned.weight != 0)]
        mismatch = np.sign(usable.mu_ann) != np.sign(usable.weight)
        result = {
            "dates": len(equity),
            "position_rows": len(pos),
            "mean_gross": float(daily.gross.mean()),
            "mean_net": float(daily.net.mean()),
            "mean_short": float(daily.short.mean()),
            "max_gross": float(daily.gross.max()),
            "order_status_counts": joined.status.value_counts().to_dict(),
            "filled_orders_with_missing_forecast": int(len(filled) - len(finite)),
            "filled_order_decision_notional_fraction_sum": total,
            "absolute_mu_quantiles_on_filled_orders": finite.mu_ann.abs()
            .quantile([0, 0.25, 0.5, 0.75, 1])
            .to_dict(),
            "notional_fraction_below_absolute_annual_mu": {
                str(threshold): float(
                    finite.loc[finite.mu_ann.abs() < threshold, "decision_notional_fraction"].sum()
                    / total
                )
                for threshold in (0.01, 0.05, 0.1)
            },
            "nonzero_position_rows_with_finite_mu": len(usable),
            "position_signal_sign_mismatch_fraction": float(mismatch.mean()),
            "mismatched_abs_weight_fraction": float(
                usable.loc[mismatch, "weight"].abs().sum() / usable.weight.abs().sum()
            ),
        }
        results[arm] = result
        joined.to_parquet(OUT / f"{arm}_order_forecasts.parquet", index=False)
    pd.DataFrame(instruments).to_csv(OUT / "instrument_exposure.csv", index=False)
    (OUT / "result.json").write_text(
        json.dumps(
            {
                "arms": results,
                "input_sha256": hashes,
                "new_return_trials": 0,
                "qualification": False,
            },
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
