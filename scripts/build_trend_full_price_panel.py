"""Build a current-vintage research panel; no strategy or execution activation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from alphaforge.validation.trend_observation import session_window
from alphaforge.validation.trend_ohlc_bridge import advance_bar
from alphaforge.validation.trend_price_bridge import Action, ActionSnapshot, PriceState

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-full-price-panel-20260912"
RAW = ROOT / "evidence/alphatrend-sharadar-direct-20260912/imputed_raw_ohlcv_v2.parquet"
EVENTS = ROOT / "evidence/alphatrend-action-validation-20260912/normalized_actions.parquet"
FIELDS = ["open", "high", "low", "close"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def main():
    OUT.mkdir(exist_ok=False)
    bound = [
        RAW,
        EVENTS,
        Path(__file__),
        *[
            ROOT / "src/alphaforge/validation" / name
            for name in ["trend_ohlc_bridge.py", "trend_price_bridge.py", "trend_observation.py"]
        ],
    ]
    bindings = {str(p.relative_to(ROOT)): sha(p) for p in bound}
    save(
        "protocol.json",
        {
            "mode": "DIAGNOSTIC_CURRENT_VINTAGE",
            "bindings": bindings,
            "anchor": "first available session close, raw OHLC identity on anchor",
            "signal": "I_prev * (split * raw_price + cash) / raw_close_prev",
            "validation": "bridge: all events + every 100th row; shares book: every close",
            "quality_review": "flag gaps >20%, intraday ranges >20%, zero volume",
            "quality_thresholds": "triage only; no data replacement or strategy filtering",
            "new_hypotheses": 0,
            "union_hypotheses": 238,
        },
    )
    raw = pd.read_parquet(RAW).sort_values(["symbol", "session_ms"]).reset_index(drop=True)
    actions = pd.read_parquet(EVENTS)
    assert not raw.duplicated(["symbol", "session_ms"]).any()
    assert not actions.duplicated(["symbol", "session_ms"]).any()
    assert raw.ohlc_valid.all()
    cal = xcals.get_calendar("XNYS", start="2000-01-01", end="2030-12-31")
    output, checks, anchors = [], [], []
    book_error = 0.0
    used = 0
    for symbol, group in raw.groupby("symbol", sort=True):
        group = group.reset_index(drop=True)
        stamps = group.session_ms.to_numpy(dtype=np.int64)
        expected = cal.sessions_in_range(
            pd.Timestamp(int(stamps[0]), unit="ms"), pd.Timestamp(int(stamps[-1]), unit="ms")
        )
        assert np.array_equal(stamps, expected.as_unit("ms").asi8)
        events = actions[actions.symbol == symbol].set_index("session_ms")
        assert set(events.index).issubset(set(stamps[1:])), "Events outside post-anchor history"
        anchors.append({"symbol": symbol, "session_ms": int(stamps[0]), "rows": len(group)})
        values = group[FIELDS].to_numpy(dtype=float)
        assert np.isfinite(values).all() and (values > 0).all()
        signal = np.empty_like(values)
        signal[0] = values[0]
        ratio, cash = np.ones(len(group)), np.zeros(len(group))
        for i in range(1, len(group)):
            if stamps[i] in events.index:
                event = events.loc[stamps[i]]
                if event.kind == "split":
                    ratio[i] = float(event.raw_value)
                else:
                    cash[i] = float(event.raw_value)
                used += 1
            signal[i] = signal[i - 1, 3] * (ratio[i] * values[i] + cash[i]) / values[i - 1, 3]
        # Independent close accounting: split existing shares, accrue cash on old
        # shares, then reinvest at ex-close. This is an index, not spendable cash.
        shares = 1.0
        for i in range(1, len(group)):
            receivable = shares * cash[i]
            shares *= ratio[i]
            shares += receivable / values[i, 3]
            error = abs(shares * values[i, 3] / signal[i, 3] - 1)
            book_error = max(book_error, error)
            assert error < 1e-11
        sample = sorted(
            set(range(1, len(group), 100))
            | {i for i in range(1, len(group)) if stamps[i] in events.index}
        )
        for i in sample:
            effective = ()
            if stamps[i] in events.index:
                event = events.loc[stamps[i]]
                effective = (
                    Action(
                        event.event_id, symbol, int(stamps[i]), event.kind, float(event.raw_value)
                    ),
                )
            snap = ActionSnapshot(
                symbol,
                int(stamps[i]),
                int(stamps[i]) + 86400000,
                int(actions.observed_ms.max()),
                sha(EVENTS),
                True,
                effective,
            )
            previous = PriceState(
                symbol, int(stamps[i - 1]), float(values[i - 1, 3]), float(signal[i - 1, 3])
            )
            args = {
                "session_ms": int(stamps[i]),
                "raw_open": float(values[i, 0]),
                "raw_high": float(values[i, 1]),
                "raw_low": float(values[i, 2]),
                "raw_close": float(values[i, 3]),
                "snapshot": snap,
                "decision_ms": session_window(int(stamps[i]))[0],
                "mode": "DIAGNOSTIC_CURRENT_VINTAGE",
            }
            bar = advance_bar(previous, **args)
            actual = np.array([bar.open, bar.high, bar.low, bar.close])
            assert np.array_equal(actual, signal[i]), "Step bridge differs"
            # Perturb current close within bounds: open/H/L must stay unchanged.
            args["raw_close"] = args["raw_low"]
            perturbed = advance_bar(previous, **args)
            assert (bar.open, bar.high, bar.low) == (perturbed.open, perturbed.high, perturbed.low)
            checks.append(
                {
                    "symbol": symbol,
                    "session_ms": int(stamps[i]),
                    "action": bool(effective),
                    "exact_ohlc": True,
                    "open_independent": True,
                }
            )
        paired = group[["symbol", "session_ms"]].copy()
        for j, field in enumerate(FIELDS):
            paired["raw_" + field] = values[:, j]
            paired["signal_" + field] = signal[:, j]
        paired["raw_volume"] = group.volume
        paired["zero_volume"] = group.volume == 0
        paired["split_ratio"] = ratio
        paired["dividend_raw"] = cash
        gap = np.full(len(group), np.nan)
        gap[1:] = (ratio[1:] * values[1:, 0] + cash[1:]) / values[:-1, 3] - 1
        paired["action_adjusted_open_gap"] = gap
        paired["intraday_range_fraction"] = values[:, 1] / values[:, 2] - 1
        paired["quality_review"] = (
            paired.zero_volume | (abs(gap) > 0.20) | (paired.intraday_range_fraction > 0.20)
        )
        assert np.isfinite(signal).all() and (signal > 0).all()
        assert (signal[:, 2] <= signal[:, [0, 3]].min(axis=1)).all()
        assert (signal[:, 1] >= signal[:, [0, 3]].max(axis=1)).all()
        output.append(paired)
    frame = pd.concat(output, ignore_index=True)
    assert used == len(actions)
    for field in FIELDS:
        assert np.array_equal(frame["raw_" + field], raw[field])
    assert np.array_equal(frame.raw_volume, raw.volume)
    frame.to_parquet(OUT / "paired_prices.parquet", index=False)
    frame[frame.quality_review].to_parquet(OUT / "quality_review.parquet", index=False)
    pd.DataFrame(checks).to_parquet(OUT / "bridge_checks.parquet", index=False)
    for name, digest in bindings.items():
        assert sha(ROOT / name) == digest
    save(
        "result.json",
        {
            "rows": len(frame),
            "symbols": len(anchors),
            "anchors": anchors,
            "actions_applied_once": used,
            "step_checks": len(checks),
            "independent_book_max_relative_error": book_error,
            "raw_prices_and_volume_unchanged": True,
            "zero_volume_rows": int(frame.zero_volume.sum()),
            "quality_review_rows": int(frame.quality_review.sum()),
            "quality_review_by_symbol": frame[frame.quality_review]
            .groupby("symbol")
            .size()
            .to_dict(),
            "engine_integrated": False,
            "historical_availability_proven": False,
            "new_hypotheses": 0,
            "union_hypotheses": 238,
        },
    )
    print((OUT / "result.json").read_text())


if __name__ == "__main__":
    main()
