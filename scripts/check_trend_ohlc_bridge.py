"""Validate all retained continuation bars and current-close independence of opens."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from alphaforge.validation.trend_observation import session_window
from alphaforge.validation.trend_ohlc_bridge import advance_bar
from alphaforge.validation.trend_price_bridge import PriceState
from check_trend_price_bridge import snapshot

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-ohlc-bridge-20260912"
HISTORY = ROOT / "evidence/alphatrend-history-bridge-20260912"
CLOSE = ROOT / "evidence/alphatrend-price-bridge-20260912"
CAP = ROOT / "evidence/alphatrend-action-capture-20260912"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    with (OUT / name).open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def main():
    OUT.mkdir(exist_ok=False)
    files = [
        Path(__file__),
        ROOT / "scripts/check_trend_price_bridge.py",
        ROOT / "src/alphaforge/validation/trend_price_bridge.py",
        ROOT / "src/alphaforge/validation/trend_ohlc_bridge.py",
        HISTORY / "raw_history.parquet",
        HISTORY / "overlap.parquet",
        CLOSE / "diagnostic_extension.parquet",
        *sorted(CAP.glob("*.json")),
        *sorted(CAP.glob("*.bin")),
    ]
    bindings = {str(p): sha(p) for p in files}
    write(
        "protocol.json",
        {
            "mode": "DIAGNOSTIC_CURRENT_VINTAGE",
            "bridge_version": "forward_wealth_ohlc_v1",
            "new_hypotheses": 0,
            "union_hypotheses": 238,
            "strategy_return_measurements": 0,
            "bindings": bindings,
        },
    )
    raw = pd.read_parquet(HISTORY / "raw_history.parquet")
    overlap = pd.read_parquet(HISTORY / "overlap.parquet")
    rows = []
    for symbol, part in raw.groupby("symbol"):
        last = overlap[overlap.symbol == symbol].sort_values("session_ms").iloc[-1]
        state = PriceState(
            symbol, int(last.session_ms), float(last.close_sip), float(last.close_lake)
        )
        snap = snapshot(symbol)
        for r in part.sort_values("session_ms").itertuples():
            if r.session_ms <= int(last.session_ms):
                continue
            args = {
                "session_ms": int(r.session_ms),
                "raw_open": r.open,
                "raw_high": r.high,
                "raw_low": r.low,
                "raw_close": r.close,
                "snapshot": snap,
                "decision_ms": session_window(int(r.session_ms))[0] + 1,
                "mode": "DIAGNOSTIC_CURRENT_VINTAGE",
            }
            bar = advance_bar(state, **args)
            for alternate_close in [r.low, r.high]:
                altered = advance_bar(state, **{**args, "raw_close": alternate_close})
                assert (bar.open, bar.high, bar.low) == (altered.open, altered.high, altered.low)
            assert bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
            rows.append(
                {
                    "symbol": symbol,
                    "session_ms": int(r.session_ms),
                    "signal_open": bar.open,
                    "signal_high": bar.high,
                    "signal_low": bar.low,
                    "signal_close": bar.close,
                    "raw_open": r.open,
                    "raw_high": r.high,
                    "raw_low": r.low,
                    "raw_close": r.close,
                    "raw_volume": r.volume,
                }
            )
            state = bar.state
    output = pd.DataFrame(rows)
    previous = pd.read_parquet(CLOSE / "diagnostic_extension.parquet")
    joined = output.merge(
        previous,
        on=["symbol", "session_ms"],
        validate="one_to_one",
        suffixes=("_ohlc", "_previous"),
    )
    assert len(joined) == len(previous) == len(output) == 238
    assert (joined.signal_close_ohlc == joined.signal_close_previous).all()
    output.to_parquet(OUT / "diagnostic_bars.parquet", index=False)
    result = {
        "bars": len(output),
        "symbols": 17,
        "sessions": 14,
        "close_matches_previous_bridge_exactly": True,
        "open_high_low_independent_of_current_close_checks": 476,
        "ohlc_ordering_checks": 238,
        "runtime_ready": False,
        "synthetic_coordinates_are_execution_quotes": False,
        "yahoo_parity_established": False,
        "new_hypotheses": 0,
        "union_hypotheses": 238,
    }
    for path, digest in bindings.items():
        assert sha(Path(path)) == digest
    write("result.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
