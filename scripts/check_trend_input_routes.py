"""Verify real captured routing without generating forecasts or portfolio returns."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
from check_trend_price_bridge import snapshot

from alphaforge.validation.trend_input_routes import TrendInputRoutes
from alphaforge.validation.trend_observation import session_window

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-input-routes-20260912"


def main():
    OUT.mkdir(exist_ok=False)
    source = ROOT / "evidence/alphatrend-ohlc-bridge-20260912/diagnostic_bars.parquet"
    frame = pd.read_parquet(source)
    routes = TrendInputRoutes(frame)
    end = int(frame.session_ms.max())
    features = routes.feature_bars(through_session=end)
    execution = routes.execution_bars(through_session=end)
    for prefix, actual in [("raw", execution), ("signal", features)]:
        expected = frame.sort_values(["symbol", "session_ms"]).reset_index(drop=True)
        for field in ["open", "high", "low", "close"]:
            assert (expected[prefix + "_" + field] == actual[field]).all()
    features.to_parquet(OUT / "feature_inputs.parquet", index=False)
    execution.to_parquet(OUT / "execution_inputs.parquet", index=False)
    # Label routing smoke check at horizon 1 only; economic 21-session checks were
    # completed separately. This is input wiring, not a tested strategy variant.
    decision = int(frame.session_ms.min())
    results = []
    for symbol in sorted(frame.symbol.unique()):
        result = routes.label(
            symbol=symbol,
            decision_session=decision,
            horizon=1,
            snapshot=snapshot(symbol),
            as_of_ms=session_window(end)[0],
            mode="DIAGNOSTIC_CURRENT_VINTAGE",
        )
        results.append({"symbol": symbol, "label": result.gross_return, "mode": result.mode})
    (OUT / "routing_smoke_labels.json").write_text(json.dumps(results, indent=2) + "\n")
    files = [
        Path(__file__),
        ROOT / "scripts/check_trend_price_bridge.py",
        source,
        ROOT / "src/alphaforge/validation/trend_input_routes.py",
        ROOT / "src/alphaforge/validation/trend_holding_label.py",
        ROOT / "src/alphaforge/validation/trend_holding_label_v2.py",
        *sorted((ROOT / "evidence/alphatrend-action-capture-20260912").glob("*.json")),
        *sorted((ROOT / "evidence/alphatrend-action-capture-20260912").glob("*.bin")),
    ]
    result = {
        "rows_per_route": len(frame),
        "exact_raw_execution": True,
        "exact_synthetic_features": True,
        "raw_label_routing_checks": len(results),
        "engine_integrated": False,
        "runtime_ready": False,
        "new_hypotheses": 0,
        "union_hypotheses": 238,
        "bindings": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "bindings"}))


if __name__ == "__main__":
    main()
