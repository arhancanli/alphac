"""Replay the existing 119-label accounting packet through the new provider."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from check_trend_price_bridge import snapshot

from alphaforge.validation.trend_observation import session_window
from alphaforge.validation.trend_raw_label_provider import RawHoldingLabelProvider

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-raw-label-service-20260912"


def main():
    OUT.mkdir(exist_ok=False)
    history = ROOT / "evidence/alphatrend-history-bridge-20260912/raw_history.parquet"
    reference = (
        ROOT / "evidence/alphatrend-holding-labels-20260912_completed/label_comparison.parquet"
    )
    bindings = [history, reference, Path(__file__), ROOT / "scripts/check_trend_price_bridge.py"]
    bindings += [
        ROOT / "src/alphaforge" / p
        for p in [
            "signals/raw_label_trend.py",
            "validation/trend_raw_label_provider.py",
            "validation/trend_input_routes_v2.py",
            "validation/trend_holding_label_v2.py",
            "validation/trend_holding_label.py",
        ]
    ]
    bindings += list((ROOT / "evidence/alphatrend-action-capture-20260912").glob("*.json"))
    bindings += list((ROOT / "evidence/alphatrend-action-capture-20260912").glob("*.bin"))
    digests = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in bindings
    }
    (OUT / "protocol.json").write_text(
        json.dumps(
            {
                "scope": "existing raw label replay, no strategy forecasts/IC/performance",
                "mode": "DIAGNOSTIC_CURRENT_VINTAGE",
                "horizon": 21,
                "bindings": digests,
                "signal_columns": (
                    "identity placeholders unused by raw label provider; "
                    "no feature calculation"
                ),
                "new_hypotheses": 0,
                "union_hypotheses": 238,
            },
            indent=2,
        )
        + "\n"
    )
    raw = pd.read_parquet(history)
    paired = raw[["symbol", "session_ms"]].copy()
    for field in ["open", "high", "low", "close"]:
        paired["raw_" + field] = raw[field]
        paired["signal_" + field] = raw[field]
    paired["raw_volume"] = raw.volume
    paired["price_disputed"] = False
    symbols = sorted(raw.symbol.unique())
    provider = RawHoldingLabelProvider(
        paired,
        instrument_symbols={s: s for s in symbols},
        snapshots={s: snapshot(s) for s in symbols},
        mode="DIAGNOSTIC_CURRENT_VINTAGE",
    )
    expected = pd.read_parquet(reference).set_index(["decision_ms", "symbol"]).sort_index()
    expected.index.names = ["ts_open", "instrument_id"]
    labels = provider.labels(
        expected.index, horizon=21, as_of_ms=session_window(int(raw.session_ms.max()))[0]
    )
    assert len(labels) == 119
    assert np.array_equal(labels.to_numpy(), expected.raw_holding_label.to_numpy())
    labels.rename("provider_label").to_frame().to_parquet(OUT / "label_replay.parquet")
    result = {
        "replayed_labels": len(labels),
        "exact_reference_match": True,
        "provider_binding": provider.binding,
        "signal_service_unit_integrated": True,
        "full_strategy_engine_integrated": False,
        "new_hypotheses": 0,
        "union_hypotheses": 238,
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
