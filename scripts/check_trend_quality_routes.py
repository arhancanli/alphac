"""Exercise full-history quality routing without executing a strategy."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from alphaforge.validation.trend_input_routes_v2 import TrendInputRoutesV2
from alphaforge.validation.trend_observation import ObservationError

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-quality-routing-20260912"
PANEL = ROOT / "evidence/alphatrend-full-price-panel-20260912/paired_prices.parquet"
REVIEW = ROOT / "evidence/alphatrend-full-price-panel-20260912/extreme_cross_source_review.parquet"


def main():
    bindings = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [
            PANEL,
            REVIEW,
            Path(__file__),
            ROOT / "src/alphaforge/validation/trend_input_routes_v2.py",
        ]
    }
    (OUT / "protocol.json").write_text(
        json.dumps(
            {
                "bindings": bindings,
                "policy": "retain all sessions; zero volume cannot execute",
                "price_disputes": "three >10bp flagged cross-source disagreements, unresolved",
                "scope": "diagnostic routing, no engine activation or strategy returns",
            },
            indent=2,
        )
        + "\n"
    )
    data = pd.read_parquet(PANEL)
    review = pd.read_parquet(REVIEW)
    bad = review[review.review_class == "CROSS_SOURCE_DISAGREEMENT"].copy()
    bad["session_ms"] = pd.to_datetime(bad.date).dt.as_unit("ms").astype("int64")
    disputed = set(zip(bad.symbol, bad.session_ms, strict=True))
    data["price_disputed"] = [
        (s, t) in disputed for s, t in zip(data.symbol, data.session_ms, strict=True)
    ]
    route = TrendInputRoutesV2(data)
    last = int(data.session_ms.max())
    execution = route.execution_bars(through_session=last)
    assert len(execution) == len(data)
    assert np.array_equal(execution.volume, data.raw_volume)
    for field in ["open", "high", "low", "close"]:
        assert np.array_equal(execution[field], data["raw_" + field])
    excluded = execution[~execution.execution_eligible]
    assert len(excluded) == 4
    try:
        route.feature_bars(through_session=last)
    except ObservationError:
        full_features_blocked = True
    else:
        raise AssertionError("Disputed prices passed feature gate")
    # Clean symbols are checked separately for routing parity, never used as a
    # substitute strategy universe or as a performance selection.
    checked = 0
    for _, group in data.groupby("symbol"):
        if group.price_disputed.any():
            continue
        features = TrendInputRoutesV2(group).feature_bars(through_session=last)
        for field in ["open", "high", "low", "close"]:
            assert np.array_equal(features[field], group["signal_" + field])
        checked += len(group)
    data.to_parquet(OUT / "quality_tagged_panel.parquet", index=False)
    excluded.to_parquet(OUT / "execution_ineligible_rows.parquet", index=False)
    result = {
        "rows_preserved": len(data),
        "execution_ineligible_rows": len(excluded),
        "zero_volume_rows": int((execution.volume == 0).sum()),
        "disputed_rows": int(data.price_disputed.sum()),
        "clean_symbol_feature_rows_checked": checked,
        "full_feature_history_blocked": full_features_blocked,
        "raw_prices_volume_exact": True,
        "engine_integrated": False,
        "new_hypotheses": 0,
        "union_hypotheses": 238,
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
