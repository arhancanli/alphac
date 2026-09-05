from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "audit_operating_margin_unresolved_split_exposure.py"


def _module():
    spec = importlib.util.spec_from_file_location("operating_margin_split_exposure_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exposure_classification_is_fail_closed() -> None:
    classify = _module().classify_exposure
    assert classify(held=True, queued=True, in_window=True) == "OBSERVED_HELD_PRE_BOUNDARY"
    assert classify(held=False, queued=True, in_window=True) == "OBSERVED_QUEUED_PRE_BOUNDARY"
    assert (
        classify(held=False, queued=False, in_window=True)
        == "NO_OBSERVED_PRE_BOUNDARY_EXPOSURE"
    )
    assert (
        classify(held=True, queued=True, in_window=False) == "EVENT_OUTSIDE_SEALED_REPLAY_WINDOW"
    )
