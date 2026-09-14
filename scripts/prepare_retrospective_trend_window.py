"""Stage reviewed historical inputs only; never compute strategy signals or returns."""

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from alphaforge.validation.trend_dividend_settlement import DividendPayment
from alphaforge.validation.trend_price_bridge import Action, ActionSnapshot
from alphaforge.validation.trend_runner_bundle import TrendRunnerBundle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-retrospective-execution-20260912"


def main():
    for name in ["alphatrend-reviewed-panel-20260912", "alphatrend-efa-event-review-20260912"]:
        seal = json.loads((ROOT / "evidence" / name / "closure.json").read_text())
        for path, digest in seal["files"].items():
            if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest:
                raise ValueError(f"Sealed input changed: {path}")
    start = int(pd.Timestamp("2012-01-01", tz="UTC").value // 10**6)
    source = ROOT / "evidence/alphatrend-efa-event-review-20260912"
    events_path = source / "revised_actions_v3.parquet"
    events = pd.read_parquet(events_path).query("session_ms >= @start").copy()
    coverage = pd.read_parquet(source / "coverage_v5.parquet").query("session_ms >= @start")
    paired = (
        pd.read_parquet(
            ROOT / "evidence/alphatrend-reviewed-panel-20260912/quality_tagged_panel.parquet"
        )
        .query("session_ms >= @start")
        .copy()
    )
    fields = ["open", "high", "low", "close"]
    event_map = {(s, int(t)): g for (s, t), g in events.groupby(["symbol", "session_ms"])}
    applied = set()
    max_error = 0.0
    # Re-anchor at raw prices. Never import pre-2012 synthetic levels or IC state.
    for symbol, group in paired.groupby("symbol"):
        previous_raw = previous_signal = None
        shares = 1.0
        for row in group.sort_values("session_ms").itertuples():
            acts = event_map.get((symbol, int(row.session_ms)))
            split, cash = 1.0, 0.0
            if acts is not None:
                if previous_raw is None or len(acts) != 1:
                    raise ValueError("Unresolved anchor or simultaneous action basis")
                event = acts.iloc[0]
                if event.kind == "split":
                    split = float(event.raw_value)
                elif event.kind == "dividend":
                    cash = float(event.raw_value)
                else:
                    raise ValueError("Unknown action")
                applied.add(event.event_id)
            if previous_raw is None:
                values = [getattr(row, "raw_" + f) for f in fields]
            else:
                values = [
                    previous_signal * (split * getattr(row, "raw_" + f) + cash) / previous_raw
                    for f in fields
                ]
            paired.loc[row.Index, ["signal_" + f for f in fields]] = values
            shares = shares * split + shares * cash / row.raw_close
            max_error = max(max_error, abs(values[-1] / (shares * row.raw_close) - 1))
            previous_raw, previous_signal = row.raw_close, values[-1]
    if applied != set(events.event_id) or max_error > 1e-11:
        raise ValueError("Action application or independent reinvestment check failed")
    end = int(paired.session_ms.max()) + 86400000
    observed = int(
        datetime.fromisoformat(
            json.loads((source / "closure.json").read_text())["created_at"]
        ).timestamp()
        * 1000
    )
    vintage = int(datetime.now(UTC).timestamp() * 1000)
    digest = hashlib.sha256(events_path.read_bytes()).hexdigest()
    mapping = {f"XUSE:CASH:{s}USD": s for s in sorted(paired.symbol.unique())}
    snapshots = {
        s: ActionSnapshot(
            s,
            start,
            end,
            max(observed, int(events.observed_ms.max())),
            digest,
            True,
            tuple(
                Action(str(e.event_id), s, int(e.session_ms), e.kind, float(e.raw_value))
                for e in events.loc[events.symbol == s].itertuples()
            ),
        )
        for s in mapping.values()
    }
    dates = coverage.set_index(["symbol", "session_ms"]).adjudicated_pay_date
    payments = []
    for e in events.loc[events.kind == "dividend"].itertuples():
        date = dates.loc[(e.symbol, e.session_ms)]
        if pd.isna(date):
            raise ValueError("Missing payment date")
        payments.append(
            DividendPayment(
                str(e.event_id),
                f"XUSE:CASH:{e.symbol}USD",
                int(e.session_ms),
                int(pd.Timestamp(date, tz="UTC").value // 10**6),
                max(observed, int(e.observed_ms)),
                Decimal(str(e.raw_value)),
            )
        )
    bundle = TrendRunnerBundle(
        paired,
        instrument_symbols=mapping,
        snapshots=snapshots,
        payments=payments,
        mode="DIAGNOSTIC_CURRENT_VINTAGE",
        retrospective_vintage_ms=vintage,
    )
    OUT.mkdir(exist_ok=False)
    paired.to_parquet(OUT / "paired_prices.parquet", index=False)
    bundle.prepare(OUT / "runner")
    bundle.verify()
    payload = {
        "snapshots": {s: asdict(a) for s, a in snapshots.items()},
        "payments": [{**asdict(e), "cash_per_share": str(e.cash_per_share)} for e in payments],
        "instrument_symbols": mapping,
        "retrospective_vintage_ms": vintage,
    }
    (OUT / "schedule.json").write_text(json.dumps(payload, indent=2) + "\n")
    result = {
        "status": "HISTORICAL_INPUTS_STAGED_NO_STRATEGY_COMPUTE",
        "rows": len(paired),
        "actions": len(applied),
        "payments": len(payments),
        "independent_signal_close_max_relative_error": max_error,
        "runner_binding": bundle.binding,
        "new_strategy_trials": 0,
        "hypothesis_union": 238,
        "registration": "pending frozen comparison configuration",
        "staged_files": bundle._staged_hashes,
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "staged_files"}, indent=2))


if __name__ == "__main__":
    main()
