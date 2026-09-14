"""Outcome-free inventory of a later current-vintage research window."""

import hashlib
import json
from pathlib import Path

import exchange_calendars as xcals
import pandas as pd

from alphaforge.validation.trend_input_routes_v2 import TrendInputRoutesV2

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-later-window-20260912"


def main():
    inputs = {}
    for name in ["alphatrend-reviewed-panel-20260912", "alphatrend-efa-event-review-20260912"]:
        seal = ROOT / "evidence" / name / "closure.json"
        record = json.loads(seal.read_text())
        for relative, expected in record["files"].items():
            actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"Sealed input changed: {relative}")
        inputs[str(seal.relative_to(ROOT))] = hashlib.sha256(seal.read_bytes()).hexdigest()
    panel = pd.read_parquet(
        ROOT / "evidence/alphatrend-reviewed-panel-20260912/quality_tagged_panel.parquet"
    )
    coverage = pd.read_parquet(
        ROOT / "evidence/alphatrend-efa-event-review-20260912/coverage_v5.parquet"
    )
    actions = pd.read_parquet(
        ROOT / "evidence/alphatrend-efa-event-review-20260912/revised_actions_v3.parquet"
    )
    bad_dates = list(panel.loc[panel.price_disputed, "session_ms"]) + list(
        coverage.loc[coverage.adjudicated_pay_date.isna(), "session_ms"]
    )
    # First full calendar year after the last unresolved event; no outcomes read.
    year = pd.to_datetime(max(bad_dates), unit="ms", utc=True).year + 1
    start = pd.Timestamp(f"{year}-01-01", tz="UTC")
    start_ms = start.value // 10**6
    selected = panel.loc[panel.session_ms >= start_ms].copy()
    payments = coverage.loc[coverage.session_ms >= start_ms]
    events = actions.loc[actions.session_ms >= start_ms]
    end = pd.to_datetime(int(selected.session_ms.max()), unit="ms", utc=True)
    cal = xcals.get_calendar("XNYS", start=start.tz_localize(None), end=end.tz_localize(None))
    sessions = cal.sessions
    expected = set(sessions.as_unit("ms").asi8)
    counts = {}
    for symbol, rows in selected.groupby("symbol"):
        if set(rows.session_ms) != expected or rows.session_ms.duplicated().any():
            raise ValueError(f"Calendar coverage mismatch: {symbol}")
        counts[symbol] = len(rows)
    routed = TrendInputRoutesV2(selected).feature_bars(
        through_session=int(selected.session_ms.max())
    )
    if payments.adjudicated_pay_date.isna().any() or len(routed) != len(selected):
        raise ValueError("Window still contains unresolved records")
    divs = events.loc[events.kind == "dividend"]
    if set(zip(divs.symbol, divs.session_ms, strict=True)) != set(
        zip(payments.symbol, payments.session_ms, strict=True)
    ):
        raise ValueError("Dividend reference coverage mismatch")
    report = {
        "status": "DATA_WINDOW_AUDITED_RUNNER_BLOCKED",
        "selection_rule": "first full calendar year after last unresolved price/payment ex-date",
        "history_start": str(start.date()),
        "history_end": str(end.date()),
        "rows": len(selected),
        "sessions_per_symbol": counts,
        "actions": len(events),
        "dividends": len(divs),
        "price_disputes": int(selected.price_disputed.sum()),
        "missing_payment_dates": int(payments.adjudicated_pay_date.isna().sum()),
        "zero_volume_rows": int((selected.raw_volume == 0).sum()),
        "actions_observed_after_ex_date": int((events.observed_ms > events.session_ms).sum()),
        "warmup_rule_draft": "2012-2014 inclusive; evaluate from first XNYS session of 2015",
        "old_ic_anchor_reusable": False,
        "signal_levels_require_rebuild_from_window_raw_anchor": True,
        "current_vintage_only": True,
        "point_in_time_proven": False,
        "costs": "retain parent modeled base costs; separate registered doubled-cost decision path",
        "registration_status": "NOT_REGISTERED; freeze complete executable configuration first",
        "real_strategy_trials": 0,
        "hypothesis_union": 238,
        "bindings": inputs,
    }
    OUT.mkdir(exist_ok=False)
    (OUT / "audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
