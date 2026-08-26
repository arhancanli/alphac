from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).parents[2]


def _module():
    path = REPO / "scripts" / "sharadar_load.py"
    spec = importlib.util.spec_from_file_location("sharadar_load_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rows(*values: object) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2025-06-26"] * len(values),
            "action": ["dividend"] * len(values),
            "ticker": ["HDB"] * len(values),
            "value": list(values),
        }
    )


def test_positive_action_values_pass_unchanged() -> None:
    values = _module()._require_positive_action_values(_rows(0.42, 2.0))
    assert values.tolist() == [0.42, 2.0]


@pytest.mark.parametrize("value", [0.0, -0.1, float("nan"), "not-a-number"])
def test_nonpositive_or_nonfinite_action_values_fail_closed(value: object) -> None:
    with pytest.raises(ValueError, match="finite and > 0"):
        _module()._require_positive_action_values(_rows(value))
