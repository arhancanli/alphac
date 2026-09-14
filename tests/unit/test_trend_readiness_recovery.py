import importlib.util
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


readiness = load("check_trend_observation_readiness")
recovery = load("audit_alphamax_reference_recovery")


def test_completed_session_bar_is_valid():
    bar = {"t": "2026-09-11T04:00:00Z", "o": 100.0, "h": 102.0, "l": 99.0, "c": 101.0, "v": 1000}
    assert readiness.valid_bar(bar, "2026-09-11")


@pytest.mark.parametrize(
    "patch",
    [{"t": "2026-09-10T04:00:00Z"}, {"c": float("nan")}, {"l": 103.0}, {"v": 0}, {"o": True}],
)
def test_stale_or_malformed_bars_fail(patch):
    bar = {"t": "2026-09-11T04:00:00Z", "o": 100.0, "h": 102.0, "l": 99.0, "c": 101.0, "v": 1000}
    assert not readiness.valid_bar({**bar, **patch}, "2026-09-11")


def test_exact_leg_recovery_and_rejection_of_drift():
    root = pd.DataFrame({"ts": [1, 2, 3, 4], "equity": [100.0, 102.0, 102.0, 101.0]})
    legs = [root.iloc[:2], root.iloc[2:]]
    assert recovery.check_stitch(root, legs) == {
        "leg_count": 2,
        "equity_rows": 4,
        "frame_exact": True,
    }
    changed = root.copy()
    changed.loc[2, "equity"] += 0.001
    with pytest.raises(ValueError, match="does not reproduce"):
        recovery.check_stitch(root, [changed.iloc[:2], changed.iloc[2:]])
    with pytest.raises(ValueError, match="strictly ordered"):
        recovery.check_stitch(root, legs[::-1])
    with pytest.raises(ValueError, match="strictly ordered"):
        recovery.check_stitch(root, [root.iloc[:3], root.iloc[2:]])
