import numpy as np
import pytest

from alphaforge.portfolio.trend_direction_confirmation import ConfirmedDirectionStrategy
from alphaforge.portfolio.trend_positive_targets import PositiveTargetsStrategy


def test_mask_preserves_longs_and_does_not_redistribute_or_mutate():
    strategy = object.__new__(PositiveTargetsStrategy)
    strategy._cash_retention = None
    weights = np.array([0.25, -0.40, 0.0, 0.10])
    actual = strategy._retain_cash(weights, ["a", "b", "c", "d"], None)
    np.testing.assert_array_equal(actual, [0.25, 0.0, 0.0, 0.10])
    np.testing.assert_array_equal(weights, [0.25, -0.40, 0.0, 0.10])
    with pytest.raises(ValueError, match="finite"):
        strategy._retain_cash(np.array([np.nan]), ["a"], None)
    assert PositiveTargetsStrategy.on_bar_close is ConfirmedDirectionStrategy.on_bar_close


def test_engine_mask_reaches_saved_risk_targets_and_audit(tmp_path, monkeypatch):
    from test_trend_confirmation_engine import test_confirmation_engine_cadence_and_raw_execution

    import alphaforge.validation.trend_confirmation_bundle as module

    checked = []
    rejected = []

    class CheckedStrategy(PositiveTargetsStrategy):
        def _retain_cash(self, weights, ids, ctx):
            masked = super()._retain_cash(weights, ids, ctx)
            rejected.append(bool(np.any(weights < 0)))
            np.testing.assert_array_equal(masked[weights > 0], weights[weights > 0])
            return masked

        def _rebalance(self, ctx, mu_map):
            targets = super()._rebalance(ctx, mu_map)
            if targets is not None:
                assert all(w >= 0 for w in targets.values())
                assert all(w >= 0 for w in self._last_targets.values())
                assert self.direction_audit[-1]["targets"] == targets
                checked.append(dict(targets))
            return targets

    monkeypatch.setattr(module, "ConfirmedDirectionStrategy", CheckedStrategy)
    test_confirmation_engine_cadence_and_raw_execution(tmp_path)
    assert checked
    assert any(rejected)
