"""Pre-trade checks — every order passes through here in backtest AND live
(execDesign §7.1; one code path, so the simulator can never be more permissive
than the real loop).

Verdict policy — REJECT, never resize:
    A failing order is DROPPED with explicit reasons, never silently shrunk to
    fit. Silent resizing would hide upstream sizing bugs (an optimizer that
    keeps emitting 20%-of-equity orders should be fixed, not quietly clipped)
    and would make live behaviour diverge from what the backtest measured.

Checks per order, all reasons collected (not first-failure) for diagnosability:

1. inputs known: instrument, close, ADV, sigma present and positive/finite.
2. price collar: ``|decision_price - close| <= price_collar_frac * close`` —
   the market moved since the signal was computed => the signal is stale.
   Applies to EVERY order, including reduce-only: de-risking at a price 5%
   away from what the decision assumed is still a fat-finger guard.
3. position cap: post-trade ``|qty_i| * close_i <= max_position_frac * E``.
4. book caps: post-trade gross ``<= max_gross * E`` and ``|net| <= max_net * E``,
   evaluated sequentially against a working book (earlier accepted orders in
   the batch are applied before later ones are judged — deterministic in
   batch order).
5. ADV participation: order notional ``<= max_order_adv_frac * ADV``. The 1%
   default is what keeps the square-root impact law valid (the law is only
   trustworthy for participation <~ 1%); the cost model's 5%
   ``CostModelMisuse`` tripwire is the backstop that fires only if THIS guard
   is broken — it is never the operating limit.
6. reduce-only integrity: a ``reduce_only`` order must strictly shrink the
   working position toward zero without flipping sign, else the exemption
   below would be a leverage loophole.

``reduce_only`` orders are EXEMPT from checks 3-5 (you must always be able to
de-risk, even when the book is already over its caps) but never from the
collar (2) or integrity (6).

Systemic breach => :class:`RiskLimitError` (raise, not reject): if the book
with ALL opening orders dropped — i.e. current positions plus only the
accepted reduce-only orders — would STILL violate the gross cap, rejection
cannot fix anything; the books themselves are wrong (accounting/marking bug
upstream) and the loop must halt loudly rather than keep trading on corrupt
state.

All math is pure float64 on the supplied marks; the checker holds no state
between calls and is fully deterministic.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from alphaforge.core.errors import RiskLimitError
from alphaforge.core.instruments import Instrument
from alphaforge.core.types import OrderRequest
from alphaforge.costs import TransactionCostModel
from alphaforge.risk.crowding import (
    CrowdingObservation,
    CrowdingPolicy,
    CrowdingStatus,
    assess_crowding,
)
from alphaforge.risk.limits import RiskLimits

__all__ = ["CheckReport", "OrderVerdict", "PreTradeChecker"]


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderVerdict:
    """One order's pre-trade outcome.

    ``reasons`` is empty iff ``accepted``. ``est_cost_frac`` is the cost
    model's one-way cost fraction for the order (taker), NaN when rejected or
    when cost inputs were the reason for rejection — carried for risk-event
    logging and slippage attribution, never used to gate.
    """

    order: OrderRequest
    accepted: bool
    reasons: tuple[str, ...]
    est_cost_frac: float

    def __post_init__(self) -> None:
        if self.accepted != (len(self.reasons) == 0):
            raise ValueError("OrderVerdict.accepted must agree with empty reasons")


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckReport:
    """Batch verdict: one :class:`OrderVerdict` per input order, input order
    preserved. ``accepted`` is the pass-through list the executor consumes."""

    verdicts: tuple[OrderVerdict, ...]

    @property
    def accepted(self) -> tuple[OrderRequest, ...]:
        """Orders that passed every check, in input order."""
        return tuple(v.order for v in self.verdicts if v.accepted)

    @property
    def rejected(self) -> tuple[OrderVerdict, ...]:
        """Verdicts for dropped orders (with reasons), in input order."""
        return tuple(v for v in self.verdicts if not v.accepted)

    @property
    def n_accepted(self) -> int:
        """Count of accepted orders."""
        return len(self.accepted)

    @property
    def n_rejected(self) -> int:
        """Count of rejected orders."""
        return len(self.rejected)


def _positive_finite(value: float) -> bool:
    return math.isfinite(value) and value > 0.0


class PreTradeChecker:
    """Stateless pre-trade gate over a batch of orders (execDesign §7.1).

    Construction wires the shared :class:`RiskLimits` and the ONE
    :class:`TransactionCostModel` (used to annotate verdicts with the
    estimated one-way cost fraction; pricing authority stays in the cost
    model, gating authority stays here).
    """

    __slots__ = ("_cost_model", "_crowding_policy", "_limits")

    def __init__(
        self,
        limits: RiskLimits,
        cost_model: TransactionCostModel,
        crowding_policy: CrowdingPolicy | None = None,
    ) -> None:
        self._limits = limits
        self._cost_model = cost_model
        self._crowding_policy = crowding_policy

    @property
    def limits(self) -> RiskLimits:
        """The hard limits this checker enforces."""
        return self._limits

    def check(
        self,
        orders: Sequence[OrderRequest],
        *,
        equity: float,
        positions: Mapping[str, float],
        closes: Mapping[str, float],
        adv_quote: Mapping[str, float],
        sigma_daily: Mapping[str, float],
        instruments: Mapping[str, Instrument],
        crowding: Mapping[str, CrowdingObservation] | None = None,
    ) -> CheckReport:
        """Judge ``orders`` against the book.

        ``positions`` are SIGNED base-unit quantities; ``closes`` are the
        decision-bar closes used as the single mark for all notionals (the
        collar bounds |decision_price - close| so the mark choice cannot
        drift far); ``adv_quote``/``sigma_daily`` are the PIT cost inputs.

        Raises :class:`RiskLimitError` on systemic breach (see module
        docstring) or non-positive/non-finite ``equity``.
        """
        if not _positive_finite(equity):
            raise RiskLimitError(
                f"pre-trade check requires finite positive equity, got {equity!r} — "
                "accounting bug upstream"
            )
        limits = self._limits
        working: dict[str, float] = dict(positions)
        # Book with ALL opening orders dropped (positions + accepted reduce-onlys),
        # used for the systemic-breach gross check at the end.
        reduced_book: dict[str, float] = dict(positions)
        verdicts: list[OrderVerdict] = []

        for order in orders:
            iid = order.instrument_id
            reasons: list[str] = []

            close = closes.get(iid, math.nan)
            adv = adv_quote.get(iid, math.nan)
            sigma = sigma_daily.get(iid, math.nan)
            if iid not in instruments:
                reasons.append(f"unknown_instrument: {iid} not in instruments")
            if not _positive_finite(close):
                reasons.append(f"missing_close: no positive finite close for {iid}")
            if not _positive_finite(adv):
                reasons.append(f"missing_adv: no positive finite adv_quote for {iid}")
            if not _positive_finite(sigma):
                reasons.append(f"missing_sigma: no positive finite sigma_daily for {iid}")
            if reasons:
                verdicts.append(
                    OrderVerdict(
                        order=order, accepted=False, reasons=tuple(reasons), est_cost_frac=math.nan
                    )
                )
                continue

            signed_qty = order.side.sign * order.qty
            current_qty = working.get(iid, 0.0)
            resulting_qty = current_qty + signed_qty
            order_notional = order.qty * close

            if self._crowding_policy is not None and not order.reduce_only:
                observation = None if crowding is None else crowding.get(iid)
                if observation is None:
                    reasons.append("crowding_unassessable: missing PIT observation")
                elif observation.instrument_id != iid:
                    reasons.append("crowding_unassessable: instrument identity mismatch")
                else:
                    assessment = assess_crowding(
                        observation,
                        self._crowding_policy,
                        decision_ts=order.decision_ts,
                        resulting_signed_notional=resulting_qty * close,
                        adv_quote=adv,
                    )
                    if assessment.status is not CrowdingStatus.PASS:
                        reasons.extend(
                            f"crowding_{assessment.status.value}: {reason}"
                            for reason in assessment.reasons
                        )

            # 2. price collar — applies to ALL orders, reduce-only included.
            if abs(order.decision_price - close) > limits.price_collar_frac * close:
                reasons.append(
                    f"price_collar: |decision_price {order.decision_price!r} - close "
                    f"{close!r}| > {limits.price_collar_frac} * close"
                )

            if order.reduce_only:
                # 6. integrity: must shrink toward zero, never flip or grow.
                if (
                    current_qty == 0.0
                    or signed_qty * current_qty > 0.0
                    or abs(resulting_qty) > abs(current_qty)
                    or resulting_qty * current_qty < 0.0
                ):
                    reasons.append(
                        f"reduce_only_not_reducing: position {current_qty!r} + order "
                        f"{signed_qty!r} does not shrink toward zero"
                    )
            else:
                # 3. per-position cap.
                if abs(resulting_qty) * close > limits.max_position_frac * equity:
                    reasons.append(
                        f"position_cap: post-trade |notional| {abs(resulting_qty) * close!r} > "
                        f"{limits.max_position_frac} * equity"
                    )
                # 4. post-trade book gross/net on the working book.
                gross = 0.0
                net = 0.0
                for book_iid, qty in {**working, iid: resulting_qty}.items():
                    if qty == 0.0:
                        continue
                    mark = closes.get(book_iid, math.nan)
                    if not _positive_finite(mark):
                        raise RiskLimitError(
                            f"no positive finite close to mark held position {book_iid} — "
                            "marking bug upstream"
                        )
                    notional = qty * mark
                    gross += abs(notional)
                    net += notional
                if gross > limits.max_gross * equity:
                    reasons.append(
                        f"gross_cap: post-trade gross {gross!r} > {limits.max_gross} * equity"
                    )
                if abs(net) > limits.max_net * equity:
                    reasons.append(
                        f"net_cap: post-trade |net| {abs(net)!r} > {limits.max_net} * equity"
                    )
                # 5. ADV participation — the sqrt-impact validity guard.
                if order_notional > limits.max_order_adv_frac * adv:
                    reasons.append(
                        f"adv_participation: order notional {order_notional!r} > "
                        f"{limits.max_order_adv_frac} * ADV {adv!r}"
                    )

            if reasons:
                verdicts.append(
                    OrderVerdict(
                        order=order, accepted=False, reasons=tuple(reasons), est_cost_frac=math.nan
                    )
                )
                continue

            # Accepted: annotate cost, apply to the working book.
            est_cost = self._cost_model.oneway_cost_frac(
                instruments[iid], order_notional, adv, sigma
            )
            verdicts.append(
                OrderVerdict(order=order, accepted=True, reasons=(), est_cost_frac=est_cost)
            )
            working[iid] = resulting_qty
            if order.reduce_only:
                reduced_book[iid] = reduced_book.get(iid, 0.0) + signed_qty

        # Systemic breach: even with every opening order dropped, the book
        # still violates gross => the positions themselves are wrong.
        reduced_gross = 0.0
        for book_iid, qty in reduced_book.items():
            if qty == 0.0:
                continue
            mark = closes.get(book_iid, math.nan)
            if not _positive_finite(mark):
                raise RiskLimitError(
                    f"no positive finite close to mark held position {book_iid} — "
                    "marking bug upstream"
                )
            reduced_gross += abs(qty) * mark
        if reduced_gross > limits.max_gross * equity:
            raise RiskLimitError(
                f"systemic gross breach: book gross {reduced_gross!r} with all opening "
                f"orders dropped still exceeds {limits.max_gross} * equity {equity!r} — "
                "accounting bug upstream, halting"
            )

        return CheckReport(verdicts=tuple(verdicts))
