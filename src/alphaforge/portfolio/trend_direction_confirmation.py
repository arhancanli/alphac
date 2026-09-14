"""Opt-in research direction persistence; no production default changes."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from alphaforge.portfolio.paired_price_strategy import PairedPriceBlendStrategy


@dataclass(frozen=True)
class DirectionState:
    admitted: int
    pending: int = 0


def proposal(
    states: Mapping[str, DirectionState], forecasts: Mapping[str, float]
) -> tuple[dict[str, DirectionState], dict[str, float]]:
    """Propose state for one successful rebalance, without mutating input state.

    First nonzero direction enters immediately. An opposite direction must occur
    on two consecutive successful rebalances. Zero flattens and resets; missing
    instruments are removed. Retain magnitude, though the trend allocator uses sign.
    """
    next_states = {}
    filtered = {}
    for iid, value in forecasts.items():
        if not math.isfinite(value):
            raise ValueError("Confirmation requires finite forecasts")
        direction = int(value > 0) - int(value < 0)
        old = states.get(iid, DirectionState(0))
        if (
            direction == 0
            or old.admitted == 0
            or direction == old.admitted
            or direction == old.pending
        ):
            state = DirectionState(direction)
        else:
            state = DirectionState(old.admitted, direction)
        next_states[iid] = state
        filtered[iid] = abs(value) * state.admitted
    return next_states, filtered


class ConfirmedDirectionStrategy(PairedPriceBlendStrategy):
    """Advance memory only after a successful parent allocation.

    The inherited on_bar_close owns cadence, stale-signal holds, and the daily
    drawdown ladder. The parent allocator still owns shortability and sizing.
    This state is process-local and research-only; restart continuity is not certified.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._direction_states: dict[str, DirectionState] = {}
        self.direction_audit: list[dict] = []

    def _rebalance(self, ctx, mu_map):
        states, filtered = proposal(self._direction_states, mu_map)
        targets = super()._rebalance(ctx, filtered)
        if targets is not None:
            self._direction_states = states
            self.direction_audit.append(
                {
                    "ts": ctx.ts,
                    "input_mu": dict(mu_map),
                    "filtered_mu": filtered,
                    "pending": {iid: s.pending for iid, s in states.items()},
                    "targets": dict(targets),
                }
            )
        return targets
