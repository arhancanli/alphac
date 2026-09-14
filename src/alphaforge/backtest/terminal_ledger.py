"""Opt-in terminal-event ledger for explicitly sourced research settlements."""

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

from alphaforge.backtest.ledger import Ledger
from alphaforge.core.types import Fill, Liquidity, Side


@dataclass(frozen=True, kw_only=True)
class TerminalEvent:
    instrument_id: str
    effective_ts: int
    price: float
    fee_fraction: float
    basis: str
    source_path: Path
    source_sha256: str

    def __post_init__(self):
        if not self.instrument_id or type(self.effective_ts) is not int or self.effective_ts < 0:
            raise ValueError("Explicit instrument and nonnegative integer boundary required")
        if not math.isfinite(self.price) or self.price <= 0:
            raise ValueError("Positive finite explicit settlement price required")
        if not math.isfinite(self.fee_fraction) or self.fee_fraction < 0:
            raise ValueError("Nonnegative finite explicit settlement fee required")
        if self.basis not in {"reported", "modeled"}:
            raise ValueError("Settlement basis must be reported or modeled")
        self.verify_source()

    def verify_source(self):
        if hashlib.sha256(self.source_path.read_bytes()).hexdigest() != self.source_sha256:
            raise ValueError("Terminal source hash mismatch")


class TerminalLedger(Ledger):
    """Settle at an exact boundary; disallow later or backdated resurrection.

    Reported is a caller's source classification, not an authenticity certificate.
    Modeled inputs require explicit opt-in. Neither mode certifies historical
    availability; the runner must separately bind its information-timing policy.
    The runner must split its clock at every event; skipped boundaries fail.
    """

    def __init__(self, initial_cash, instruments, *, events, allow_modeled=False):
        super().__init__(initial_cash, instruments)
        self._terminal = {}
        self._settled = set()
        self.terminal_records = []
        for event in events:
            if event.instrument_id not in instruments or event.instrument_id in self._terminal:
                raise ValueError("Unknown or duplicate terminal instrument")
            if event.basis == "modeled" and not allow_modeled:
                raise ValueError("Modeled settlement requires explicit opt-in")
            event.verify_source()
            self._terminal[event.instrument_id] = event

    def _require_no_due_event(self, ts):
        if any(self._terminal[iid].effective_ts > ts for iid in self._settled):
            raise ValueError("Cannot book events before an already processed terminal boundary")
        if any(
            e.effective_ts <= ts and iid not in self._settled for iid, e in self._terminal.items()
        ):
            raise ValueError("Terminal boundary must be processed before later book events")

    def apply_fill(self, fill):
        event = self._terminal.get(fill.instrument_id)
        if event and (fill.ts >= event.effective_ts or fill.instrument_id in self._settled):
            raise ValueError("Fill prohibited for terminated contract")
        self._require_no_due_event(fill.ts)
        return super().apply_fill(fill)

    def mark(self, closes, ts):
        self._require_no_due_event(ts)
        return super().mark(closes, ts)

    def apply_funding(self, instrument_id, ts_funding, rate, mark_price):
        self._require_no_due_event(ts_funding)
        return super().apply_funding(instrument_id, ts_funding, rate, mark_price)

    def apply_borrow(self, instrument_id, ts, borrow_frac_per_day, days, mark_price):
        self._require_no_due_event(ts)
        return super().apply_borrow(instrument_id, ts, borrow_frac_per_day, days, mark_price)

    def apply_financing(self, accrual):
        self._require_no_due_event(accrual.end_ts)
        if any(
            accrual.start_ts < self._terminal[iid].effective_ts < accrual.end_ts
            for iid in self._settled
        ):
            raise ValueError("Financing interval crosses a terminal cash change")
        return super().apply_financing(accrual)

    def apply_split(self, instrument_id, ts, ratio):
        self._require_no_due_event(ts)
        return super().apply_split(instrument_id, ts, ratio)

    def apply_cash_dividend(self, instrument_id, ts, cash_amount):
        self._require_no_due_event(ts)
        return super().apply_cash_dividend(instrument_id, ts, cash_amount)

    def settle_at(self, instrument_id, ts):
        event = self._terminal[instrument_id]
        if ts != event.effective_ts:
            raise ValueError("Settlement requires exact event timestamp")
        if any(
            e.effective_ts < ts and iid not in self._settled for iid, e in self._terminal.items()
        ):
            raise ValueError("Earlier terminal boundary must be processed first")
        if any(self._terminal[iid].effective_ts > ts for iid in self._settled):
            raise ValueError("Cannot settle before an already processed boundary")
        event.verify_source()
        if instrument_id in self._settled:
            return False
        position = self.positions().get(instrument_id)
        qty = position.qty if position is not None else 0.0
        fee = abs(qty) * event.price * event.fee_fraction
        if qty:
            # Administrative settlement, not an order filled against market liquidity.
            super().apply_fill(
                Fill(
                    client_order_id=f"terminal-{ts}-{instrument_id}",
                    instrument_id=instrument_id,
                    side=Side.SELL if qty > 0 else Side.BUY,
                    qty=abs(qty),
                    price=event.price,
                    fee_quote=fee,
                    liquidity=Liquidity.TAKER,
                    ts=ts,
                )
            )
        self._settled.add(instrument_id)
        self.terminal_records.append(
            {
                "instrument_id": instrument_id,
                "ts": ts,
                "qty_before": qty,
                "price": event.price,
                "fee_quote": fee,
                "basis": event.basis,
                "source_sha256": event.source_sha256,
                "classification": "administrative_settlement_not_market_fill",
            }
        )
        return True
