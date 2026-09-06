"""The realized-volatility leg is structurally dead under a per-cycle process unless seeded.

BlendStrategy keeps _equity_hist and _scale_hist in memory and _realized_vol_ann returns 0.0
with fewer than two equity points. Production runs one process per hourly cycle, so live the
fast regime detector never bound (0.02% of days measured in artifacts/analysis/frontier_14).
seed_history(...) restores both histories and the last scale from the durable equity curve,
with the exact index alignment the de-lever needs: the scale in force while the return INTO
equity[t] was earned is the scale recorded at cycle t-1.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from alphaforge.config.settings import Settings
from alphaforge.portfolio.strategy import BlendStrategy


def _strategy() -> BlendStrategy:
    return BlendStrategy(
        Settings(), mu_provider=lambda ts: {}, rebalance_bars=168, rebalance_anchor="epoch"
    )


def test_a_fresh_strategy_has_a_dead_realized_leg() -> None:
    """The live defect, stated as a test: no history means the leg reports 0.0."""
    assert _strategy()._realized_vol_ann(8760.0) == 0.0


def test_seed_history_restores_both_histories_with_the_documented_alignment() -> None:
    s = _strategy()
    rng = np.random.default_rng(7)
    equities = list(100_000.0 * np.cumprod(1.0 + rng.normal(0.0, 0.004, size=300)))
    scales = [0.8] * 100 + [1.1] * 200
    assert s.seed_history(list(zip(equities, scales, strict=True))) is True
    assert s._equity_hist == equities
    # scale in force during the return into equity[t] is the scale recorded at t-1; index 0 is NaN
    assert math.isnan(s._scale_hist[0])
    assert s._scale_hist[1:] == scales[:-1]
    assert s.last_scale == 1.1
    assert s._realized_vol_ann(8760.0) > 0.0


def test_recorded_nan_scales_are_carried_as_nan_and_the_last_known_scale_survives() -> None:
    """Rows written before the column existed have no scale. They must not poison the leg
    (the de-lever masks non-finite scales) and must not overwrite a finite last scale."""
    s = _strategy()
    history = [
        (100_000.0, math.nan), (100_100.0, math.nan), (100_050.0, 0.9), (100_200.0, math.nan),
    ]
    assert s.seed_history(history) is True
    assert math.isnan(s._scale_hist[1]) and s._scale_hist[3] == 0.9
    assert s.last_scale == 0.9
    assert math.isfinite(s._realized_vol_ann(8760.0))


def test_seeding_is_refused_once_the_strategy_has_its_own_history() -> None:
    """A long-lived --forever process carries the true history; a seed must not replace it."""
    s = _strategy()
    s._equity_hist.append(100_000.0)
    s._scale_hist.append(math.nan)
    assert s.seed_history([(1.0, 1.0), (2.0, 1.0)]) is False
    assert s._equity_hist == [100_000.0]


def test_seed_history_refuses_garbage() -> None:
    s = _strategy()
    with pytest.raises(ValueError):
        s.seed_history([(0.0, 1.0)])
    with pytest.raises(ValueError):
        s.seed_history([(math.nan, 1.0), (1.0, 1.0)])
