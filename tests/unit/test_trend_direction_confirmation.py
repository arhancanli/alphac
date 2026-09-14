from types import SimpleNamespace

import pytest

from alphaforge.portfolio.paired_price_strategy import PairedPriceBlendStrategy
from alphaforge.portfolio.trend_direction_confirmation import (
    ConfirmedDirectionStrategy,
    DirectionState,
    proposal,
)


def test_reversal_requires_two_consecutive_observations_and_resets():
    state = {}
    signs = []
    for value in [1.0, -0.1, 0.2, -0.3, -0.4, 0.0, 0.1]:
        state, mu = proposal(state, {"a": value})
        signs.append((mu["a"] > 0) - (mu["a"] < 0))
    assert signs == [1, 1, 1, 1, -1, 0, 1]


def test_identity_order_missing_and_rejected_input_do_not_corrupt_state():
    state = {"a": DirectionState(1, -1), "b": DirectionState(-1)}
    next_state, mu = proposal(state, {"b": -2.0, "a": -0.5})
    assert mu == {"b": -2.0, "a": -0.5}
    assert state["a"] == DirectionState(1, -1)
    missing, _ = proposal(next_state, {"b": -2.0})
    restored, mu = proposal(missing, {"a": 0.1, "b": -2.0})
    assert restored["a"] == DirectionState(1)
    with pytest.raises(ValueError):
        proposal(state, {"a": float("nan")})
    assert state["a"] == DirectionState(1, -1)


def test_cold_start_does_not_count_as_confirmation_and_parent_mask_survives(monkeypatch):
    strategy = object.__new__(ConfirmedDirectionStrategy)
    strategy._direction_states = {"a": DirectionState(1)}
    strategy.direction_audit = []
    ctx = SimpleNamespace(ts=100)
    monkeypatch.setattr(PairedPriceBlendStrategy, "_rebalance", lambda *args: None)
    assert strategy._rebalance(ctx, {"a": -0.1}) is None
    assert strategy._direction_states == {"a": DirectionState(1)}
    assert strategy.direction_audit == []
    seen = []

    def parent(self, ctx, mu):
        seen.append(mu["a"])
        return {"a": 0.0}  # e.g. parent's nonshortable or risk mask

    monkeypatch.setattr(PairedPriceBlendStrategy, "_rebalance", parent)
    assert strategy._rebalance(ctx, {"a": -0.1}) == {"a": 0.0}
    assert strategy._direction_states["a"] == DirectionState(1, -1)
    ctx.ts = 200
    assert strategy._rebalance(ctx, {"a": -0.1}) == {"a": 0.0}
    assert seen == [0.1, -0.1]
    assert strategy._direction_states["a"] == DirectionState(-1)


def test_parent_still_owns_daily_cadence_and_risk_dispatch():
    assert ConfirmedDirectionStrategy.on_bar_close is PairedPriceBlendStrategy.on_bar_close
