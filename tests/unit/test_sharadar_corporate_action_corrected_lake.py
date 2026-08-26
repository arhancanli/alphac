from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "build_sharadar_corporate_action_corrected_lake.py"


def _module():
    spec = importlib.util.spec_from_file_location("ca_corrected_lake_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_future_split_lookup_includes_same_day_market_split() -> None:
    raw = pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "action": "split",
                "date_value": pd.Timestamp("2020-01-01").date(),
                "value": 0.5,
            },
            {
                "ticker": "TEST",
                "action": "split",
                "date_value": pd.Timestamp("2021-01-01").date(),
                "value": 0.2,
            },
            {
                "ticker": "TEST",
                "action": "adrratiosplit",
                "date_value": pd.Timestamp("2021-01-01").date(),
                "value": 5.0,
            },
        ]
    )
    module = _module()
    lookup = module._future_market_split_products(raw)
    assert module._product_at_or_after(
        lookup, "TEST", pd.Timestamp("2019-01-01").date()
    ) == 0.1
    assert module._product_at_or_after(
        lookup, "TEST", pd.Timestamp("2020-01-01").date()
    ) == 0.1
    assert module._product_at_or_after(
        lookup, "TEST", pd.Timestamp("2020-01-02").date()
    ) == 0.2
