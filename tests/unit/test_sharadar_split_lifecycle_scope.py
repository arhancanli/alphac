from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "audit_sharadar_split_lifecycle_scope.py"


def _module():
    spec = importlib.util.spec_from_file_location("split_lifecycle_scope_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lifecycle_scope_distinguishes_non_executable_boundaries() -> None:
    classify = _module().classify_lifecycle
    common = {"first_price_date": "2020-01-02", "last_price_date": "2020-12-31"}
    assert (
        classify(event_date="2020-01-01", pre_close=None, **common)
        == "BEFORE_FIRST_PRICE_NON_EXECUTABLE"
    )
    assert (
        classify(event_date="2020-01-02", pre_close=None, **common)
        == "FIRST_PRICE_BOUNDARY_NO_PREEXISTING_EXPOSURE"
    )
    assert (
        classify(event_date="2021-01-01", pre_close=None, **common)
        == "AFTER_LAST_PRICE_NON_EXECUTABLE"
    )
    assert (
        classify(event_date="2020-06-01", pre_close=10.0, **common)
        == "WITHIN_PRICE_LIFECYCLE_REQUIRES_RESOLUTION"
    )
