from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "audit_unresolved_split_event_context.py"


def _module():
    spec = importlib.util.spec_from_file_location("unresolved_split_context_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_context_precedence_and_weekend_classification() -> None:
    classify = _module().classify_context
    assert (
        classify(
            event_date="2020-01-04",
            nearby_actions=[{"date": "2020-01-04", "action": "listed"}],
        )
        == "SAME_DAY_LISTING_OR_DELISTING_CONTEXT"
    )
    assert (
        classify(
            event_date="2020-01-04",
            nearby_actions=[{"date": "2020-01-03", "action": "acquisitionof"}],
        )
        == "NEARBY_ACQUISITION_OR_MERGER_CONTEXT"
    )
    assert (
        classify(event_date="2020-01-04", nearby_actions=[])
        == "WEEKEND_SPLIT_WITHOUT_LIFECYCLE_CONTEXT"
    )
