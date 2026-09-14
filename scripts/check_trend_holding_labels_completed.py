"""Fixed 21-session label accounting diagnostic; no portfolio or IC measurement."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
from check_trend_price_bridge import snapshot

from alphaforge.validation.trend_holding_label import holding_label, label_sessions
from alphaforge.validation.trend_observation import session_window
from alphaforge.validation.trend_ohlc_bridge import advance_bar
from alphaforge.validation.trend_price_bridge import PriceState

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-holding-labels-20260912_completed"
HISTORY = ROOT / "evidence/alphatrend-history-bridge-20260912"
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
        ROOT / "src/alphaforge/validation/trend_holding_label.py",
        ROOT / "src/alphaforge/validation/trend_ohlc_bridge.py",
        ROOT / "src/alphaforge/validation/trend_price_bridge.py",
        HISTORY / "raw_history.parquet",
        *sorted(CAP.glob("*.json")),
        *sorted(CAP.glob("*.bin")),
    ]
    bindings = {str(p): sha(p) for p in files}
    write(
        "protocol.json",
        {
            "mode": "DIAGNOSTIC_CURRENT_VINTAGE",
            "horizon": 21,
            "scope": "LABEL_ACCOUNTING_NOT_STRATEGY_SELECTION",
            "new_hypotheses": 0,
            "union_hypotheses": 238,
            "bindings": bindings,
        },
    )
    raw = pd.read_parquet(HISTORY / "raw_history.parquet")
    results = []
    for symbol, part in raw.groupby("symbol"):
        part = part.sort_values("session_ms").set_index("session_ms")
        first = part.iloc[0]
        state = PriceState(symbol, int(part.index[0]), float(first.close), float(first.close))
        snap = snapshot(symbol)
        synthetic = {}
        for t, r in part.iloc[1:].iterrows():
            bar = advance_bar(
                state,
                session_ms=int(t),
                raw_open=float(r.open),
                raw_high=float(r.high),
                raw_low=float(r.low),
                raw_close=float(r.close),
                snapshot=snap,
                decision_ms=session_window(int(t))[0] + 1,
                mode="DIAGNOSTIC_CURRENT_VINTAGE",
            )
            synthetic[int(t)] = bar.open
            state = bar.state
        for decision in part.index:
            entry, end = label_sessions(int(decision), 21)
            if end not in part.index:
                continue
            label = holding_label(
                symbol=symbol,
                entry_ms=entry,
                exit_ms=end,
                entry_open=float(part.loc[entry, "open"]),
                exit_open=float(part.loc[end, "open"]),
                snapshot=snap,
                as_of_ms=session_window(end)[0],
                mode="DIAGNOSTIC_CURRENT_VINTAGE",
            )
            # Independent one-dollar holdings book: fractional shares and uninvested cash.
            shares = 1 / float(part.loc[entry, "open"])
            cash = 0.0
            for action in sorted(snap.actions, key=lambda a: (a.session_ms, a.event_id)):
                if entry < action.session_ms <= end:
                    if action.kind == "split":
                        shares *= action.value
                    else:
                        cash += shares * action.value
            book_return = shares * float(part.loc[end, "open"]) + cash - 1
            assert abs(book_return - label.gross_return) < 1e-12
            synthetic_return = synthetic[end] / synthetic[entry] - 1
            results.append(
                {
                    "symbol": symbol,
                    "decision_ms": int(decision),
                    "entry_ms": entry,
                    "exit_ms": end,
                    "release_ms": label.release_ms,
                    "raw_holding_label": label.gross_return,
                    "synthetic_index_ratio_label": synthetic_return,
                    "difference_bps": (synthetic_return - label.gross_return) * 10000,
                    "independent_book_error": book_return - label.gross_return,
                }
            )
    frame = pd.DataFrame(results)
    frame.to_parquet(OUT / "label_comparison.parquet", index=False)
    result = {
        "labels": len(frame),
        "symbols": int(frame.symbol.nunique()),
        "horizon_sessions": 21,
        "independent_accounting_max_error": float(frame.independent_book_error.abs().max()),
        "max_absolute_synthetic_ratio_difference_bps": float(frame.difference_bps.abs().max()),
        "labels_differing_above_one_millionth_bp": int((frame.difference_bps.abs() > 1e-6).sum()),
        "runtime_ready": False,
        "new_hypotheses": 0,
        "union_hypotheses": 238,
    }
    for path, digest in bindings.items():
        assert sha(Path(path)) == digest
    write("result.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
