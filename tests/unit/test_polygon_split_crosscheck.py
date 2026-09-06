from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "audit_polygon_split_crosscheck.py"


def _module():
    spec = importlib.util.spec_from_file_location("polygon_split_crosscheck_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_crosscheck_distinguishes_stored_reciprocal_conflict_and_missing() -> None:
    module = _module()
    failure = {
        "instrument_id": "XUSE:CASH:TESTUSD",
        "ex_date": "2020-01-02T00:00:00+00:00",
        "stored_ratio": 0.2,
        "classification": "UNEXPLAINED_PRICE_BOUNDARY",
    }
    stored = module.classify_failure(
        failure,
        [{"ticker": "OLD", "execution_date": "2020-01-02", "split_from": 5, "split_to": 1}],
        {"TEST", "OLD"},
    )
    reciprocal = module.classify_failure(
        failure,
        [{"ticker": "TEST", "execution_date": "2020-01-02", "split_from": 1, "split_to": 5}],
        {"TEST"},
    )
    conflict = module.classify_failure(
        failure,
        [{"ticker": "TEST", "execution_date": "2020-01-02", "split_from": 2, "split_to": 1}],
        {"TEST"},
    )
    missing = module.classify_failure(failure, [], {"TEST"})
    assert stored["classification"] == "INDEPENDENT_PROVIDER_CONFIRMS_STORED_RATIO"
    assert reciprocal["classification"] == "INDEPENDENT_PROVIDER_CONFIRMS_RECIPROCAL_RATIO"
    assert conflict["classification"] == "INDEPENDENT_PROVIDER_EVENT_CONFLICT"
    assert missing["classification"] == "NO_INDEPENDENT_PROVIDER_MATCH"


def test_crosscheck_accepts_provider_ratio_at_source_five_decimal_precision() -> None:
    module = _module()
    failure = {
        "instrument_id": "XUSE:CASH:TESTUSD",
        "ex_date": "2020-01-02T00:00:00+00:00",
        "stored_ratio": 0.00133,
        "classification": "MISSING_TWO_SIDED_PRICE_BOUNDARY",
    }
    result = module.classify_failure(
        failure,
        [
            {
                "ticker": "TEST",
                "execution_date": "2020-01-02",
                "split_from": 750,
                "split_to": 1,
            }
        ],
        {"TEST"},
    )
    assert result["classification"] == "INDEPENDENT_PROVIDER_CONFIRMS_STORED_RATIO"
