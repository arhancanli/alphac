"""Point-in-time securities-borrow lifecycle tests."""

from __future__ import annotations

import pytest

from alphaforge.core.errors import LookaheadError
from alphaforge.execution.borrow import (
    BorrowQuote,
    BorrowStatus,
    LocateStatus,
    RecallNotice,
    accrue_borrow_charge,
    evaluate_locate,
    incremental_short_qty,
    recall_instruction,
)

DAY = 86_400_000


def _quote(
    *,
    status: BorrowStatus = BorrowStatus.EASY,
    available_qty: float = 100.0,
    fee_bps: float = 365.0,
    available_at: int = 100,
) -> BorrowQuote:
    return BorrowQuote(
        instrument_id="XUSE:CASH:XYZUSD",
        observed_ts=90,
        available_at=available_at,
        valid_from=100,
        valid_until=100 + 10 * DAY,
        status=status,
        available_qty=available_qty,
        annual_fee_bps=fee_bps,
        utilization=0.7,
    )


def test_future_known_borrow_quote_fails_closed() -> None:
    with pytest.raises(LookaheadError, match="borrow quote"):
        evaluate_locate(_quote(available_at=101), requested_qty=10.0, decision_ts=100)


def test_unavailable_borrow_must_have_zero_quantity_and_denies_locate() -> None:
    with pytest.raises(ValueError, match="available_qty=0"):
        _quote(status=BorrowStatus.UNAVAILABLE, available_qty=1.0)
    decision = evaluate_locate(
        _quote(status=BorrowStatus.UNAVAILABLE, available_qty=0.0),
        requested_qty=10.0,
        decision_ts=100,
    )
    assert decision.status is LocateStatus.DENIED
    assert decision.granted_qty == 0.0
    assert decision.annual_fee_bps is None


def test_locate_is_quantity_bounded_and_carries_fee_and_expiry() -> None:
    quote = _quote(available_qty=7.0, fee_bps=900.0)
    decision = evaluate_locate(quote, requested_qty=10.0, decision_ts=100)
    assert decision.status is LocateStatus.PARTIAL
    assert decision.granted_qty == 7.0
    assert decision.annual_fee_bps == 900.0
    assert decision.expires_at == quote.valid_until


@pytest.mark.parametrize(
    ("current", "sell", "required"),
    [(10.0, 6.0, 0.0), (10.0, 15.0, 5.0), (0.0, 4.0, 4.0), (-3.0, 4.0, 4.0)],
)
def test_incremental_short_qty_nets_long_inventory_and_existing_short(
    current: float, sell: float, required: float
) -> None:
    assert incremental_short_qty(current_signed_qty=current, sell_qty=sell) == required


def test_borrow_charge_uses_exact_act_365_interval() -> None:
    quote = _quote(fee_bps=365.0)
    charge = accrue_borrow_charge(
        quote,
        short_qty=10.0,
        mark_price=100.0,
        start_ts=100,
        end_ts=100 + 10 * DAY,
        decision_ts=100,
    )
    assert charge == pytest.approx(1.0)


def test_borrow_charge_rejects_interval_beyond_quote_validity() -> None:
    with pytest.raises(ValueError, match="full accrual interval"):
        accrue_borrow_charge(
            _quote(),
            short_qty=10.0,
            mark_price=100.0,
            start_ts=100,
            end_ts=100 + 11 * DAY,
            decision_ts=100,
        )


def _recall(*, available_at: int = 200, deadline: int = 300) -> RecallNotice:
    return RecallNotice(
        instrument_id="XUSE:CASH:XYZUSD",
        recalled_qty=60.0,
        event_ts=190,
        available_at=available_at,
        cover_deadline=deadline,
    )


def test_future_known_recall_fails_closed() -> None:
    with pytest.raises(LookaheadError, match="recall"):
        recall_instruction(_recall(available_at=201), current_short_qty=100.0, decision_ts=200)


def test_recall_caps_cover_at_open_short_and_escalates_at_deadline() -> None:
    before = recall_instruction(_recall(), current_short_qty=40.0, decision_ts=250)
    assert before.buy_qty == 40.0
    assert before.forced_buy_in is False
    assert before.reason == "recall_cover_required"

    overdue = recall_instruction(_recall(), current_short_qty=100.0, decision_ts=300)
    assert overdue.buy_qty == 60.0
    assert overdue.forced_buy_in is True
    assert overdue.reason == "forced_buy_in_deadline_reached"


def test_recall_is_resolved_when_no_short_remains() -> None:
    instruction = recall_instruction(_recall(), current_short_qty=0.0, decision_ts=300)
    assert instruction.buy_qty == 0.0
    assert instruction.forced_buy_in is False
    assert instruction.reason == "no_short_remaining"
