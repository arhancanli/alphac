"""Fill models — how queued orders become executions (execDesign.md §4.2).

THE no-lookahead contract (execDesign.md §4.1; leakageCritique.md findings 4/5):
a decision taken at the close of bar ``t`` fills at the **open of bar t+1**,
never inside bar ``t``. A fill model therefore receives *only* the next bar; it
mechanically verifies ``next_bar.ts_open >= order.decision_ts`` and raises
:class:`~alphaforge.core.errors.LookaheadError` otherwise (the decision bar's
open is strictly before the decision close, so any attempt to fill on the
decision bar — or any earlier bar — trips the guard).

Pricing is delegated entirely to the ONE :class:`TransactionCostModel`
instance (buildabilityCritique.md §3.7 — costs are never reimplemented here)::

    P_fill = open_{t+1} * (1 + s * (half_spread + impact + latency)),  s = side.sign
    fee    = fee_frac(taker) * qty * P_fill                            # quote units

The fee is charged on the *executed* notional (``qty * P_fill``) and travels on
the :class:`~alphaforge.core.types.Fill` as ``fee_quote`` — the ledger debits
it as a separate cash line so commissions and price slippage stay separately
attributable in artifacts.

v1 scope notes (documented, deliberate):

* All fills are TAKER (market orders at next open — matches live execution
  timing; maker/limit fills are an execution-layer concern, Phase 8+).
* The §4.2 volume-participation guard (partial fill above 10% of the next
  bar's quote volume) is deferred to the ``VWAPParticipationFill`` model of a
  later phase; meanwhile the cost model's hard 5%-of-ADV tripwire
  (:class:`~alphaforge.core.errors.CostModelMisuse`) bounds order size to the
  sqrt-impact law's valid regime, so a silent under-costed mega-fill is
  structurally impossible.

All money is float64 in quote units, full precision internally — rounding is a
report-rendering concern only. Timestamps are epoch-ms UTC (:data:`Ms`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from alphaforge.core.errors import LookaheadError
from alphaforge.core.instruments import Instrument
from alphaforge.core.time import Ms
from alphaforge.core.types import Fill, Liquidity, OrderRequest
from alphaforge.costs import TransactionCostModel

__all__ = ["BarView", "FillModel", "NextOpenFill"]


@dataclass(frozen=True, slots=True, kw_only=True)
class BarView:
    """A read-only view of one OHLCV bar handed to a fill model.

    ``ts_open`` is the bar's open time (epoch-ms UTC; the bar covers
    ``[ts_open, ts_open + Δ)``). Prices are quote units; ``volume`` is base
    units; ``quote_volume`` is quote units and may be NaN for sources that
    lack it. The engine constructs these from PIT-read lake rows — a fill
    model never touches the reader and therefore can never widen its window.
    """

    ts_open: Ms
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float

    def __post_init__(self) -> None:
        for name in ("open", "high", "low", "close"):
            value: float = getattr(self, name)
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"BarView.{name} must be finite and > 0, got {value!r}")
        if not math.isfinite(self.volume) or self.volume < 0.0:
            raise ValueError(f"BarView.volume must be finite and >= 0, got {self.volume!r}")


class FillModel(Protocol):
    """Protocol for turning a queued order plus the next bar into a fill.

    Implementations MUST raise :class:`LookaheadError` when ``next_bar`` is not
    strictly after the decision (``next_bar.ts_open < order.decision_ts``) —
    the engine relies on this as the last line of the no-lookahead contract.
    ``adv_quote`` / ``sigma_daily`` are the cost-model inputs computed from PIT
    data through the decision bar (never the fill bar).
    """

    def fill(
        self,
        order: OrderRequest,
        inst: Instrument,
        next_bar: BarView,
        *,
        adv_quote: float,
        sigma_daily: float,
    ) -> Fill:
        """Execute ``order`` against ``next_bar``; returns the resulting fill."""
        ...


class NextOpenFill:
    """Default fill model: market order at the next bar's open (execDesign.md §4.2).

    Matches live execution timing — the live loop wakes after a bar closes,
    computes, and submits market orders that land around the next open.
    Pricing and fees come exclusively from the shared
    :class:`TransactionCostModel` (the sole cost authority): the latency
    add-on lives inside ``cost_model.fill_price`` and only there, so it shifts
    the recorded fill price without being double-counted in any optimizer
    penalty (see ``TransactionCostModel.oneway_cost_frac``).
    """

    __slots__ = ("_cost_model",)

    def __init__(self, cost_model: TransactionCostModel) -> None:
        self._cost_model = cost_model

    @property
    def cost_model(self) -> TransactionCostModel:
        """The shared cost authority this model prices with (read-only)."""
        return self._cost_model

    def fill(
        self,
        order: OrderRequest,
        inst: Instrument,
        next_bar: BarView,
        *,
        adv_quote: float,
        sigma_daily: float,
    ) -> Fill:
        """Fill ``order`` at the open of ``next_bar`` with full cost treatment.

        Exact arithmetic (full float64, no rounding)::

            ref      = next_bar.open
            notional = order.qty * ref                      # impact sizing input
            P_fill   = cost_model.fill_price(inst, side, ref, notional, adv, sigma)
                     = ref * (1 + s*(half_spread + impact + latency)),  s = side.sign
            fee      = cost_model.fee_frac(inst, TAKER) * order.qty * P_fill

        ``Fill.ts = next_bar.ts_open`` — the execution prints at the bar open,
        which is exactly the decision close for a contiguous grid.

        Raises:
            LookaheadError: if ``next_bar.ts_open < order.decision_ts`` — the
                bar opened before the decision existed, i.e. a same-bar (or
                earlier) fill was attempted. ``ts_open == decision_ts`` is the
                legal contiguous case.
            CostModelMisuse: propagated from the cost model on out-of-regime
                inputs (notional > 5% ADV, non-finite adv/sigma) — never
                swallowed; the engine decides whether to drop or halt.
        """
        if next_bar.ts_open < order.decision_ts:
            raise LookaheadError(
                f"fill bar opening at {next_bar.ts_open} precedes the decision at "
                f"{order.decision_ts} for {order.instrument_id!r} "
                f"(order {order.client_order_id!r}): decisions at the close of bar t "
                "fill at the open of bar t+1, never the same bar"
            )
        if inst.instrument_id != order.instrument_id:
            raise ValueError(
                f"instrument mismatch: order is for {order.instrument_id!r} but "
                f"fill was offered {inst.instrument_id!r}"
            )
        ref = next_bar.open
        notional = order.qty * ref
        price = self._cost_model.fill_price(
            inst,
            order.side,
            ref,
            notional,
            adv_quote,
            sigma_daily,
        )
        fee = self._cost_model.fee_frac(inst, Liquidity.TAKER) * order.qty * price
        return Fill(
            client_order_id=order.client_order_id,
            instrument_id=order.instrument_id,
            side=order.side,
            qty=order.qty,
            price=price,
            fee_quote=fee,
            liquidity=Liquidity.TAKER,
            ts=next_bar.ts_open,
        )
