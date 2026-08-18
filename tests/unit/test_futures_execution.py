"""Institutional invariants for dated-futures lifecycle and execution primitives."""

from __future__ import annotations

import math

import pytest

from alphaforge.core.errors import CostModelMisuse, LookaheadError, SchemaError
from alphaforge.core.instruments import Instrument
from alphaforge.core.symbols import SymbolMapper
from alphaforge.core.types import AssetClass, Liquidity, MarketType, Side
from alphaforge.costs import TransactionCostModel
from alphaforge.execution.futures import (
    ContractLiquidity,
    FuturesChain,
    FuturesContract,
    FuturesExecutionBlocked,
    FuturesPriceLimit,
    RollAction,
    RollPolicy,
    RollSnapshot,
    select_roll,
    variation_margin,
)

DAY = 86_400_000
T0 = 1_767_225_600_000  # 2026-01-01T00:00:00Z
SESSIONS = tuple(T0 + day * DAY for day in range(40))
FRONT = "CME:FUTURE:CLZ26USD"
NEXT = "CME:FUTURE:CLF27USD"
FAR = "CME:FUTURE:CLG27USD"


def contract(
    instrument_id: str,
    contract_month: str,
    *,
    listed_day: int,
    metadata_day: int,
    first_notice_day: int | None,
    last_trade_day: int,
) -> FuturesContract:
    return FuturesContract(
        instrument_id=instrument_id,
        root_symbol="CL",
        contract_month=contract_month,
        listed_ts=T0 + listed_day * DAY,
        metadata_available_at=T0 + metadata_day * DAY,
        first_notice_ts=None if first_notice_day is None else T0 + first_notice_day * DAY,
        last_trade_ts=T0 + last_trade_day * DAY,
        contract_multiplier=1_000.0,
        tick_size=0.01,
    )


def chain(*, next_metadata_day: int = 0) -> FuturesChain:
    return FuturesChain(
        root_symbol="CL",
        contracts=(
            contract(
                FRONT,
                "2026-12",
                listed_day=0,
                metadata_day=0,
                first_notice_day=10,
                last_trade_day=15,
            ),
            contract(
                NEXT,
                "2027-01",
                listed_day=0,
                metadata_day=next_metadata_day,
                first_notice_day=20,
                last_trade_day=25,
            ),
            contract(
                FAR,
                "2027-02",
                listed_day=0,
                metadata_day=0,
                first_notice_day=30,
                last_trade_day=35,
            ),
        ),
        session_opens=SESSIONS,
    )


def snapshot(day: int, *, front_volume: float, next_volume: float) -> RollSnapshot:
    decision = T0 + day * DAY
    return RollSnapshot(
        decision_ts=decision,
        observations=(
            ContractLiquidity(
                instrument_id=FRONT,
                available_at=decision,
                volume=front_volume,
                open_interest=10_000.0,
            ),
            ContractLiquidity(
                instrument_id=NEXT,
                available_at=decision,
                volume=next_volume,
                open_interest=12_000.0,
            ),
        ),
    )


def test_future_instrument_uses_canonical_taxonomy_but_not_ccxt() -> None:
    inst = Instrument(
        instrument_id=FRONT,
        asset_class=AssetClass.FUTURE,
        market_type=MarketType.FUTURE,
        base="CLZ26",
        quote="USD",
        tick_size=0.01,
        lot_size=1.0,
        min_qty=1.0,
        min_notional=0.0,
        contract_multiplier=1_000.0,
        can_short=True,
        maker_fee_bps=0.0,
        taker_fee_bps=0.0,
        funding_interval_hours=None,
        listed_ts=T0,
        delisted_ts=T0 + 15 * DAY,
    )

    assert inst.asset_class is AssetClass.FUTURE
    assert SymbolMapper.parse_instrument_id(FRONT)[1] is MarketType.FUTURE
    with pytest.raises(SchemaError, match="only crypto PERP/SPOT"):
        SymbolMapper.to_ccxt(FRONT)
    with pytest.raises(CostModelMisuse, match="no transaction-fee schedule"):
        TransactionCostModel().fee_frac(inst, Liquidity.TAKER)


def test_instrument_rejects_asset_market_mismatch() -> None:
    with pytest.raises(ValueError, match="requires market_type 'future'"):
        Instrument(
            instrument_id="CME:CASH:CLZ26USD",
            asset_class=AssetClass.FUTURE,
            market_type=MarketType.CASH,
            base="CLZ26",
            quote="USD",
            tick_size=0.01,
            lot_size=1.0,
            min_qty=1.0,
            min_notional=0.0,
            can_short=True,
            maker_fee_bps=0.0,
            taker_fee_bps=0.0,
            funding_interval_hours=None,
            listed_ts=T0,
            delisted_ts=T0 + DAY,
        )


def test_exit_deadline_uses_earliest_session_buffer() -> None:
    policy = RollPolicy(first_notice_buffer_sessions=3, last_trade_buffer_sessions=2)
    # First notice D10 - 3 sessions = D7; last trade D15 - 2 = D13. D7 wins.
    assert chain().exit_deadline(chain().contract(FRONT), policy) == T0 + 7 * DAY


@pytest.mark.parametrize("decision_day", [7, 8, 14])
def test_mandatory_roll_occurs_at_or_after_exit_deadline(decision_day: int) -> None:
    decision = select_roll(
        chain(),
        FRONT,
        (snapshot(decision_day, front_volume=100.0, next_volume=10.0),),
        RollPolicy(first_notice_buffer_sessions=3, last_trade_buffer_sessions=2),
    )

    assert decision.action is RollAction.ROLL
    assert decision.to_instrument_id == NEXT
    assert decision.reason == "mandatory_first_notice_or_last_trade_buffer"


def test_mandatory_exit_flattens_when_later_metadata_is_not_yet_known() -> None:
    decision = select_roll(
        chain(next_metadata_day=8),
        FRONT,
        (snapshot(7, front_volume=100.0, next_volume=500.0),),
        RollPolicy(first_notice_buffer_sessions=3, last_trade_buffer_sessions=2),
    )

    assert decision.action is RollAction.FLATTEN
    assert decision.to_instrument_id is None
    assert decision.reason == "mandatory_exit_no_eligible_later_contract"


def test_volume_roll_requires_every_locked_confirmation_snapshot() -> None:
    policy = RollPolicy(
        first_notice_buffer_sessions=3,
        last_trade_buffer_sessions=2,
        volume_confirmation_sessions=3,
        next_volume_ratio=1.10,
    )
    confirmed = (
        snapshot(3, front_volume=100.0, next_volume=120.0),
        snapshot(4, front_volume=90.0, next_volume=110.0),
        snapshot(5, front_volume=80.0, next_volume=100.0),
    )
    interrupted = (
        snapshot(3, front_volume=100.0, next_volume=120.0),
        snapshot(4, front_volume=100.0, next_volume=109.0),
        snapshot(5, front_volume=80.0, next_volume=100.0),
    )

    roll = select_roll(chain(), FRONT, confirmed, policy)
    hold = select_roll(chain(), FRONT, interrupted, policy)

    assert (roll.action, roll.reason) == (RollAction.ROLL, "next_contract_volume_confirmed")
    assert roll.to_instrument_id == NEXT
    assert (hold.action, hold.reason) == (RollAction.HOLD, "volume_confirmation_not_met")


def test_missing_confirmation_observation_fails_to_hold_not_roll() -> None:
    rows = list(snapshot(5, front_volume=100.0, next_volume=200.0).observations)
    missing_next = RollSnapshot(decision_ts=T0 + 5 * DAY, observations=(rows[0],))
    decision = select_roll(
        chain(),
        FRONT,
        (
            snapshot(3, front_volume=100.0, next_volume=200.0),
            snapshot(4, front_volume=100.0, next_volume=200.0),
            missing_next,
        ),
        RollPolicy(
            first_notice_buffer_sessions=3,
            last_trade_buffer_sessions=2,
            volume_confirmation_sessions=3,
        ),
    )
    assert decision.action is RollAction.HOLD


def test_future_available_liquidity_is_rejected_at_snapshot_construction() -> None:
    with pytest.raises(LookaheadError, match="exceeds decision"):
        RollSnapshot(
            decision_ts=T0 + 4 * DAY,
            observations=(
                ContractLiquidity(
                    instrument_id=FRONT,
                    available_at=T0 + 5 * DAY,
                    volume=1.0,
                    open_interest=1.0,
                ),
            ),
        )


def test_roll_snapshots_must_be_strictly_increasing() -> None:
    repeated = snapshot(4, front_volume=100.0, next_volume=200.0)
    with pytest.raises(ValueError, match="strictly increasing"):
        select_roll(chain(), FRONT, (repeated, repeated), RollPolicy())


@pytest.mark.parametrize(
    ("side", "last_price", "expected_reason"),
    [
        (Side.BUY, 85.0, "locked_limit_up"),
        (Side.SELL, 65.0, "locked_limit_down"),
        (Side.BUY, 75.0, "no_executable_liquidity"),
    ],
)
def test_zero_liquidity_distinguishes_locked_limit_state(
    side: Side, last_price: float, expected_reason: str
) -> None:
    band = FuturesPriceLimit(
        instrument_id=FRONT,
        limit_down=65.0,
        limit_up=85.0,
        effective_from=T0,
        effective_until=T0 + DAY,
        available_at=T0,
    )
    with pytest.raises(FuturesExecutionBlocked) as exc:
        band.require_executable(
            side=side,
            decision_ts=T0 + 1,
            last_price=last_price,
            executable_qty=0.0,
        )
    assert exc.value.reason == expected_reason


def test_price_limit_allows_actual_executable_liquidity_and_rejects_future_band() -> None:
    executable = FuturesPriceLimit(
        instrument_id=FRONT,
        limit_down=65.0,
        limit_up=85.0,
        effective_from=T0,
        effective_until=T0 + DAY,
        available_at=T0,
    )
    executable.require_executable(
        side=Side.BUY,
        decision_ts=T0 + 1,
        last_price=85.0,
        executable_qty=1.0,
    )
    future_known = FuturesPriceLimit(
        instrument_id=FRONT,
        limit_down=65.0,
        limit_up=85.0,
        effective_from=T0,
        effective_until=T0 + DAY,
        available_at=T0 + 100,
    )
    with pytest.raises(LookaheadError, match="exceeds decision"):
        future_known.require_executable(
            side=Side.BUY,
            decision_ts=T0 + 1,
            last_price=85.0,
            executable_qty=0.0,
        )


@pytest.mark.parametrize(
    ("signed_contracts", "expected"),
    [(2.0, 5_000.0), (-2.0, -5_000.0), (0.0, 0.0)],
)
def test_variation_margin_is_signed_linear_cashflow(
    signed_contracts: float, expected: float
) -> None:
    assert variation_margin(
        signed_contracts=signed_contracts,
        previous_settlement=70.0,
        current_settlement=72.5,
        contract_multiplier=1_000.0,
    ) == expected


@pytest.mark.parametrize("bad", [math.nan, math.inf, -1.0])
def test_variation_margin_rejects_invalid_settlement(bad: float) -> None:
    with pytest.raises(ValueError):
        variation_margin(
            signed_contracts=1.0,
            previous_settlement=bad,
            current_settlement=70.0,
            contract_multiplier=1_000.0,
        )
