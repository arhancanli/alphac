"""The backtest Ledger: positions, cash, fees, funding, equity (execDesign.md §4.3).

This is the accounting truth of the event-driven backtester. Cash and positions are
the only stored state; equity is always *derived* (``cash + Σ qty·mark``), never
stored independently, so it cannot drift from the book.

Accounting model (linear contracts, quote-settled)
--------------------------------------------------

Fills move cash by full notional plus fee::

    cash -= side.sign * qty * price        # buy spends, sell receives
    cash -= fee_quote                      # fees always reduce cash

and the marked equity adds the position back at the close::

    equity(t) = cash + Σ_i qty_i * close_i(t)

With this scheme the fundamental identity holds at every instant and is asserted
continuously by the test suite::

    equity == initial_cash + realized_pnl + unrealized_pnl - fees + funding

where ``unrealized_i = qty_i * (close_i - avg_entry_i)`` (perp linear PnL).

Position lifecycle on :meth:`Ledger.apply_fill`:

* **open / add** (flat, or fill sign == position sign): ``avg_entry_price`` is the
  quantity-weighted VWAP of the constituent fills — invariant under permutation of
  same-direction adds.
* **reduce** (opposite sign, |fill| < |position|): realized PnL is booked as
  ``qty_closed * (price - avg_entry) * sign(position)``; ``avg_entry_price`` is
  unchanged (FIFO == VWAP for a netted linear position).
* **close** (|fill| == |position|): realize as above, position is removed.
* **flip** (|fill| > |position|, qty crosses zero): the old position is realized
  *in full* at the fill price, then a fresh position opens for the residual with
  ``avg_entry_price = fill.price`` and ``opened_ts = fill.ts``. A flip is exactly
  "close everything, then open the remainder" in one print.

Funding sign convention (:meth:`Ledger.apply_funding`) — Binance USDT-M::

    payment = -position_qty * mark_price * rate

``qty > 0`` and ``rate > 0`` ⇒ ``payment < 0``: **longs pay shorts** when the rate
is positive (Binance convention). The engine — not this class — iterates the
*stored* funding-events table per instrument between consecutive bar closes
(8h/4h/1h interval aware; leakageCritique.md finding 6: never a hard-coded clock)
and passes the bar close as the mark-price proxy (documented approximation,
execDesign.md §4.3).

Numerics & rounding policy
--------------------------

All money is float64 in quote units (USDT). Internally **no rounding ever** — full
double precision end to end; rounding happens only in reports/tearsheets at render
time. Any NaN/inf reaching cash or equity is a programming error and raises
``ValueError`` immediately (fail loud, never propagate poison). There is no
negative-equity guard in v1: gross exposure ≤ 1 is enforced upstream by the
portfolio constraints (buildabilityCritique.md §6).

All timestamps are :data:`~alphaforge.core.time.Ms` (epoch milliseconds, UTC).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Final

import pandas as pd

from alphaforge.core.instruments import Instrument
from alphaforge.core.time import Ms
from alphaforge.core.types import AccountState, Fill, MarketType, Position

__all__ = ["Ledger"]

_FILL_LOG_COLUMNS: Final[tuple[str, ...]] = (
    "ts",
    "instrument_id",
    "side",
    "qty",
    "price",
    "fee_quote",
    "liquidity",
    "realized_pnl_quote",
    "client_order_id",
)

_FUNDING_LOG_COLUMNS: Final[tuple[str, ...]] = (
    "ts_funding",
    "instrument_id",
    "rate",
    "mark_price",
    "position_qty",
    "payment_quote",
)


def _require_finite(name: str, value: float) -> None:
    """Raise ``ValueError`` unless ``value`` is a finite float (no NaN/inf, fail loud)."""
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")


class Ledger:
    """Double-entry-ish book of cash + positions; equity is derived, never stored.

    One instance per backtest run. The ledger is *passive*: it records fills and
    funding cashflows handed to it by the engine and never decides anything —
    reduce-only semantics, lookahead enforcement, and funding-event iteration are
    all upstream responsibilities.

    Args:
        initial_cash: Starting cash in quote units; must be finite and > 0.
        instruments: ``instrument_id`` → :class:`Instrument` for every instrument
            this run may touch. Fills/funding for unknown ids raise ``KeyError``.
    """

    __slots__ = (
        "_cash",
        "_equity_ts",
        "_equity_values",
        "_fill_records",
        "_funding_records",
        "_funding_total",
        "_initial_cash",
        "_instruments",
        "_positions",
        "_realized",
        "_total_fees",
    )

    def __init__(self, initial_cash: float, instruments: Mapping[str, Instrument]) -> None:
        _require_finite("initial_cash", initial_cash)
        if initial_cash <= 0.0:
            raise ValueError(f"initial_cash must be > 0, got {initial_cash!r}")
        self._initial_cash: float = initial_cash
        self._cash: float = initial_cash
        self._instruments: dict[str, Instrument] = dict(instruments)
        self._positions: dict[str, Position] = {}
        self._realized: dict[str, float] = {}
        self._total_fees: float = 0.0
        self._funding_total: float = 0.0
        self._fill_records: list[dict[str, object]] = []
        self._funding_records: list[dict[str, object]] = []
        self._equity_ts: list[Ms] = []
        self._equity_values: list[float] = []

    # ------------------------------------------------------------------ events

    def apply_fill(self, fill: Fill) -> None:
        """Book an execution: update cash, position (VWAP/realize/flip), fees.

        Cash effect (always, regardless of position case)::

            cash -= fill.side.sign * fill.qty * fill.price   # notional
            cash -= fill.fee_quote                           # fee

        Position effect — let ``q0`` be the current signed qty and
        ``qf = side.sign * qty`` the signed fill qty:

        * ``q0 == 0`` or ``sign(qf) == sign(q0)``: VWAP add,
          ``avg' = (|q0|·avg + |qf|·price) / (|q0| + |qf|)``.
        * opposite sign, ``|qf| < |q0|``: reduce; book
          ``realized += |qf| * (price - avg) * sign(q0)``; ``avg`` unchanged.
        * ``|qf| == |q0|``: close; realize on ``|q0|``; position removed.
        * ``|qf| > |q0|`` (**flip**, qty crosses zero): realize the *entire* old
          position at ``fill.price``, then restart with qty ``q0 + qf``,
          ``avg_entry = fill.price``, ``opened_ts = fill.ts``.

        Raises:
            KeyError: if ``fill.instrument_id`` is not in this ledger's universe.
            ValueError: if the resulting cash is non-finite (fail loud).
        """
        if fill.instrument_id not in self._instruments:
            raise KeyError(
                f"fill references unknown instrument {fill.instrument_id!r}; "
                "the ledger universe is fixed at construction"
            )

        signed_qty = fill.side.sign * fill.qty
        new_cash = self._cash - signed_qty * fill.price - fill.fee_quote
        _require_finite(f"cash after fill {fill.client_order_id!r}", new_cash)

        realized_this_fill = 0.0
        pos = self._positions.get(fill.instrument_id)
        if pos is None or pos.qty * signed_qty > 0.0:
            # Open or same-direction add: quantity-weighted VWAP entry.
            old_qty = 0.0 if pos is None else pos.qty
            old_avg = 0.0 if pos is None else pos.avg_entry_price
            new_qty = old_qty + signed_qty
            new_avg = (abs(old_qty) * old_avg + abs(signed_qty) * fill.price) / abs(new_qty)
            self._positions[fill.instrument_id] = Position(
                instrument_id=fill.instrument_id,
                qty=new_qty,
                avg_entry_price=new_avg,
                opened_ts=fill.ts if pos is None else pos.opened_ts,
            )
        else:
            # Opposite-direction fill: reduce, close, or flip.
            pos_sign = 1.0 if pos.qty > 0.0 else -1.0
            qty_closed = min(abs(signed_qty), abs(pos.qty))
            realized_this_fill = qty_closed * (fill.price - pos.avg_entry_price) * pos_sign
            _require_finite("realized pnl", realized_this_fill)
            self._realized[fill.instrument_id] = (
                self._realized.get(fill.instrument_id, 0.0) + realized_this_fill
            )
            residual = pos.qty + signed_qty
            if abs(signed_qty) < abs(pos.qty):
                # Partial reduce: avg_entry unchanged.
                self._positions[fill.instrument_id] = Position(
                    instrument_id=fill.instrument_id,
                    qty=residual,
                    avg_entry_price=pos.avg_entry_price,
                    opened_ts=pos.opened_ts,
                )
            elif abs(signed_qty) == abs(pos.qty):
                # Exact close: flat, position removed (avg_entry resets implicitly).
                del self._positions[fill.instrument_id]
            else:
                # Flip: old side fully realized above; restart at the fill price.
                self._positions[fill.instrument_id] = Position(
                    instrument_id=fill.instrument_id,
                    qty=residual,
                    avg_entry_price=fill.price,
                    opened_ts=fill.ts,
                )

        self._cash = new_cash
        self._total_fees += fill.fee_quote
        self._fill_records.append(
            {
                "ts": fill.ts,
                "instrument_id": fill.instrument_id,
                "side": fill.side.value,
                "qty": fill.qty,
                "price": fill.price,
                "fee_quote": fill.fee_quote,
                "liquidity": fill.liquidity.value,
                "realized_pnl_quote": realized_this_fill,
                "client_order_id": fill.client_order_id,
            }
        )

    def apply_funding(
        self, instrument_id: str, ts_funding: Ms, rate: float, mark_price: float
    ) -> float:
        """Settle one funding event against the current position; return the cashflow.

        Sign convention (Binance USDT-M, THE convention)::

            payment = -position_qty * mark_price * rate

        ``qty > 0, rate > 0`` ⇒ ``payment < 0`` — **longs pay shorts** when funding
        is positive. ``qty < 0, rate > 0`` ⇒ shorts *receive*. Negative rates invert
        both. The payment is added to cash and appended to the funding log.

        The caller (engine) iterates the *stored* funding-events table for this
        instrument between consecutive bar closes — interval-aware (8h/4h/1h per
        instrument), never a hard-coded schedule (leakageCritique.md finding 6) —
        and supplies the bar close as ``mark_price`` (documented mark-price proxy
        approximation, execDesign.md §4.3).

        If the ledger holds no position in ``instrument_id`` the event is a no-op:
        returns ``0.0`` and logs nothing.

        Raises:
            KeyError: unknown instrument.
            ValueError: non-perp instrument, non-finite rate, or invalid mark price.
        """
        inst = self._instruments.get(instrument_id)
        if inst is None:
            raise KeyError(
                f"funding references unknown instrument {instrument_id!r}; "
                "the ledger universe is fixed at construction"
            )
        if inst.market_type is not MarketType.PERP:
            raise ValueError(
                f"funding applies only to perp instruments, got {instrument_id!r} "
                f"({inst.market_type.value})"
            )
        _require_finite("funding rate", rate)
        _require_finite("funding mark_price", mark_price)
        if mark_price <= 0.0:
            raise ValueError(f"funding mark_price must be > 0, got {mark_price!r}")

        pos = self._positions.get(instrument_id)
        if pos is None:
            return 0.0

        payment = -pos.qty * mark_price * rate
        new_cash = self._cash + payment
        _require_finite(f"cash after funding for {instrument_id!r}", new_cash)
        self._cash = new_cash
        self._funding_total += payment
        self._funding_records.append(
            {
                "ts_funding": ts_funding,
                "instrument_id": instrument_id,
                "rate": rate,
                "mark_price": mark_price,
                "position_qty": pos.qty,
                "payment_quote": payment,
            }
        )
        return payment

    def mark(self, closes: Mapping[str, float], ts: Ms) -> AccountState:
        """Mark the book to market and record an equity-curve point.

        ``equity = cash + Σ_i qty_i * close_i`` — linear perp marked-to-market with
        unrealized PnL included (``qty·close = qty·avg_entry + qty·(close-avg_entry)``;
        the notional leg cancels against the cash spent at entry).

        Every open position must have a finite, positive close in ``closes``
        (extra symbols are ignored). Marks must arrive with non-decreasing ``ts``;
        a re-mark at the same ``ts`` overwrites the previous point (the engine may
        legitimately re-mark a bar after funding settles).

        Returns:
            An :class:`AccountState` snapshot (positions sorted by instrument id).

        Raises:
            ValueError: missing/invalid close for an open position, non-finite
                equity, or ``ts`` earlier than the last recorded mark.
        """
        equity = self._cash
        for instrument_id, pos in self._positions.items():
            close = closes.get(instrument_id)
            if close is None:
                raise ValueError(f"mark() missing close for open position {instrument_id!r}")
            if not math.isfinite(close) or close <= 0.0:
                raise ValueError(
                    f"mark() close for {instrument_id!r} must be finite and > 0, got {close!r}"
                )
            equity += pos.qty * close
        _require_finite("equity", equity)

        if self._equity_ts and ts < self._equity_ts[-1]:
            raise ValueError(
                f"mark() ts must be non-decreasing: got {ts} after {self._equity_ts[-1]}"
            )
        if self._equity_ts and ts == self._equity_ts[-1]:
            self._equity_values[-1] = equity
        else:
            self._equity_ts.append(ts)
            self._equity_values.append(equity)

        snapshot = tuple(
            self._positions[instrument_id] for instrument_id in sorted(self._positions)
        )
        return AccountState(equity_quote=equity, cash_quote=self._cash, positions=snapshot, ts=ts)

    # ------------------------------------------------------------------- views

    @property
    def cash(self) -> float:
        """Free cash balance in quote units (full precision, never rounded)."""
        return self._cash

    @property
    def initial_cash(self) -> float:
        """Starting cash supplied at construction."""
        return self._initial_cash

    @property
    def total_fees(self) -> float:
        """Cumulative fees paid in quote units (always >= 0)."""
        return self._total_fees

    @property
    def total_funding(self) -> float:
        """Cumulative net funding received in quote units (signed)."""
        return self._funding_total

    def positions(self) -> dict[str, Position]:
        """Open positions keyed by instrument id (frozen values, fresh dict)."""
        return dict(self._positions)

    def realized_pnl(self) -> dict[str, float]:
        """Cumulative realized PnL per instrument in quote units (fresh dict)."""
        return dict(self._realized)

    def equity_curve(self) -> pd.Series:
        """Recorded equity curve as a float64 Series indexed by mark ts (epoch ms)."""
        return pd.Series(
            self._equity_values,
            index=pd.Index(self._equity_ts, dtype="int64", name="ts"),
            dtype="float64",
            name="equity",
        )

    def fills_log(self) -> pd.DataFrame:
        """All booked fills as a DataFrame (insertion order; full precision).

        Columns: ``ts, instrument_id, side, qty, price, fee_quote, liquidity,
        realized_pnl_quote, client_order_id``.
        """
        return pd.DataFrame(self._fill_records, columns=list(_FILL_LOG_COLUMNS))

    def funding_log(self) -> pd.DataFrame:
        """All settled funding events as a DataFrame (insertion order; full precision).

        Columns: ``ts_funding, instrument_id, rate, mark_price, position_qty,
        payment_quote``.
        """
        return pd.DataFrame(self._funding_records, columns=list(_FUNDING_LOG_COLUMNS))
