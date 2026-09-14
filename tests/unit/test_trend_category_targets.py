import numpy as np
import pytest

from alphaforge.portfolio.trend_category_targets import CategoryTargetsStrategy
from alphaforge.portfolio.trend_direction_confirmation import ConfirmedDirectionStrategy


def test_category_mask_keeps_all_non_equity_signs_without_redistribution():
    strategy = object.__new__(CategoryTargetsStrategy)
    strategy._cash_retention = None
    ids = [f"XUSE:CASH:{s}USD" for s in ["SPY", "IEF", "UUP", "UNG", "QQQ"]]
    weights = np.array([-0.2, -0.3, -0.1, 0.15, 0.1])
    actual = strategy._retain_cash(weights, ids, None)
    np.testing.assert_array_equal(actual, [0, -0.3, -0.1, 0.15, 0.1])
    np.testing.assert_array_equal(weights, [-0.2, -0.3, -0.1, 0.15, 0.1])
    np.testing.assert_array_equal(
        strategy._retain_cash(weights[::-1], ids[::-1], None), actual[::-1]
    )
    assert CategoryTargetsStrategy.on_bar_close is ConfirmedDirectionStrategy.on_bar_close


def test_unknown_or_nonfinite_category_targets_rejected():
    strategy = object.__new__(CategoryTargetsStrategy)
    strategy._cash_retention = None
    with pytest.raises(ValueError, match="Unclassified"):
        strategy._retain_cash(np.array([-0.1]), ["unknown"], None)
    with pytest.raises(ValueError, match="finite"):
        strategy._retain_cash(np.array([np.nan]), ["XUSE:CASH:SPYUSD"], None)
