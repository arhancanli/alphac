"""Point-in-time dated-futures lifecycle, roll, limit, and settlement primitives.

This module deliberately does not manufacture a continuous futures price series.
It answers the narrower institutional questions that must be settled first:

* which dated contract metadata was knowable at a decision timestamp;
* when a position must leave a contract before first notice or last trade;
* whether a volume-led roll persisted for the registered number of observations;
* whether a locked exchange price limit makes an order non-executable; and
* how daily variation margin changes cash for a linear futures position.

Contract observations and metadata carry explicit availability timestamps. Any
future-known input raises rather than being silently admitted. ETF proxy sleeves do
not become futures sleeves merely because these primitives exist.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from enum import StrEnum

from alphaforge.core.errors import LookaheadError
from alphaforge.core.symbols import SymbolMapper
from alphaforge.core.time import Ms
from alphaforge.core.types import MarketType, Side

__all__ = [
    "ContractLiquidity",
    "FuturesChain",
    "FuturesContract",
    "FuturesExecutionBlocked",
    "FuturesPriceLimit",
    "RollAction",
    "RollDecision",
    "RollPolicy",
    "RollSnapshot",
    "select_roll",
    "variation_margin",
]


def _positive_finite(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and > 0, got {value!r}")


def _nonnegative_finite(name: str, value: float) -> None:
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be finite and >= 0, got {value!r}")


@dataclass(frozen=True, slots=True, kw_only=True)
class FuturesContract:
    """One dated linear futures contract and its point-in-time lifecycle metadata."""

    instrument_id: str
    root_symbol: str
    contract_month: str
    listed_ts: Ms
    metadata_available_at: Ms
    first_notice_ts: Ms | None
    last_trade_ts: Ms
    contract_multiplier: float
    tick_size: float

    def __post_init__(self) -> None:
        _, market_type, symbol = SymbolMapper.parse_instrument_id(self.instrument_id)
        if market_type is not MarketType.FUTURE:
            raise ValueError(
                f"futures contract requires MarketType.FUTURE, got {market_type.value!r}"
            )
        if not self.root_symbol or self.root_symbol != self.root_symbol.upper():
            raise ValueError("root_symbol must be non-empty uppercase text")
        if len(self.contract_month) != 7 or self.contract_month[4] != "-":
            raise ValueError("contract_month must be YYYY-MM")
        try:
            year = int(self.contract_month[:4])
            month = int(self.contract_month[5:])
        except ValueError as exc:
            raise ValueError("contract_month must be YYYY-MM") from exc
        if year < 1900 or month not in range(1, 13):
            raise ValueError("contract_month must contain a valid YYYY-MM")
        if not symbol.startswith(self.root_symbol):
            raise ValueError(
                f"future symbol {symbol!r} must begin with root {self.root_symbol!r}"
            )
        if self.listed_ts >= self.last_trade_ts:
            raise ValueError("listed_ts must precede last_trade_ts")
        if self.metadata_available_at > self.last_trade_ts:
            raise ValueError("metadata_available_at cannot follow last_trade_ts")
        if self.first_notice_ts is not None:
            if self.first_notice_ts <= self.listed_ts:
                raise ValueError("first_notice_ts must follow listed_ts")
            if self.first_notice_ts > self.last_trade_ts:
                raise ValueError("first_notice_ts cannot follow last_trade_ts")
        _positive_finite("contract_multiplier", self.contract_multiplier)
        _positive_finite("tick_size", self.tick_size)

    def known_at(self, decision_ts: Ms) -> bool:
        """Whether the contract and lifecycle metadata were known by ``decision_ts``."""
        return self.listed_ts <= decision_ts and self.metadata_available_at <= decision_ts


@dataclass(frozen=True, slots=True, kw_only=True)
class RollPolicy:
    """Locked roll rule expressed in exchange sessions, never calendar-day guesses."""

    first_notice_buffer_sessions: int = 5
    last_trade_buffer_sessions: int = 3
    volume_confirmation_sessions: int = 3
    next_volume_ratio: float = 1.0

    def __post_init__(self) -> None:
        if self.first_notice_buffer_sessions < 0 or self.last_trade_buffer_sessions < 0:
            raise ValueError("roll buffers must be >= 0 sessions")
        if self.volume_confirmation_sessions <= 0:
            raise ValueError("volume_confirmation_sessions must be > 0")
        _positive_finite("next_volume_ratio", self.next_volume_ratio)


@dataclass(frozen=True, slots=True, kw_only=True)
class ContractLiquidity:
    """A PIT volume/open-interest observation for one dated contract."""

    instrument_id: str
    available_at: Ms
    volume: float
    open_interest: float

    def __post_init__(self) -> None:
        _nonnegative_finite("volume", self.volume)
        _nonnegative_finite("open_interest", self.open_interest)


@dataclass(frozen=True, slots=True, kw_only=True)
class RollSnapshot:
    """All contract liquidity observations available at one roll decision time."""

    decision_ts: Ms
    observations: tuple[ContractLiquidity, ...]

    def __post_init__(self) -> None:
        ids: set[str] = set()
        for observation in self.observations:
            if observation.instrument_id in ids:
                raise ValueError(
                    f"duplicate liquidity observation for {observation.instrument_id!r}"
                )
            ids.add(observation.instrument_id)
            if observation.available_at > self.decision_ts:
                raise LookaheadError(
                    f"liquidity for {observation.instrument_id!r} available at "
                    f"{observation.available_at} exceeds decision {self.decision_ts}"
                )

    def by_id(self) -> dict[str, ContractLiquidity]:
        return {row.instrument_id: row for row in self.observations}


@dataclass(frozen=True, slots=True, kw_only=True)
class FuturesChain:
    """A root's dated contracts plus the exact exchange-session index used for deadlines."""

    root_symbol: str
    contracts: tuple[FuturesContract, ...]
    session_opens: tuple[Ms, ...]

    def __post_init__(self) -> None:
        if not self.contracts:
            raise ValueError("futures chain requires at least one contract")
        if any(c.root_symbol != self.root_symbol for c in self.contracts):
            raise ValueError("all contracts must share the chain root_symbol")
        ids = [c.instrument_id for c in self.contracts]
        if len(set(ids)) != len(ids):
            raise ValueError("futures chain contract ids must be unique")
        expiries = [c.last_trade_ts for c in self.contracts]
        if expiries != sorted(expiries) or len(set(expiries)) != len(expiries):
            raise ValueError("contracts must be strictly ordered by last_trade_ts")
        if not self.session_opens:
            raise ValueError("session_opens cannot be empty")
        if list(self.session_opens) != sorted(set(self.session_opens)):
            raise ValueError("session_opens must be strictly increasing and unique")

    def contract(self, instrument_id: str) -> FuturesContract:
        for contract in self.contracts:
            if contract.instrument_id == instrument_id:
                return contract
        raise KeyError(f"contract {instrument_id!r} is not in {self.root_symbol!r} chain")

    def exit_deadline(self, contract: FuturesContract, policy: RollPolicy) -> Ms:
        """Earliest session at which the contract is no longer eligible to hold."""
        deadlines: list[Ms] = []
        events = (
            (contract.first_notice_ts, policy.first_notice_buffer_sessions),
            (contract.last_trade_ts, policy.last_trade_buffer_sessions),
        )
        for event_ts, buffer_sessions in events:
            if event_ts is None:
                continue
            event_idx = bisect.bisect_left(self.session_opens, event_ts)
            deadline_idx = event_idx - buffer_sessions
            if deadline_idx < 0 or deadline_idx >= len(self.session_opens):
                raise ValueError(
                    f"session index does not cover the {buffer_sessions}-session buffer for "
                    f"{contract.instrument_id!r} event {event_ts}"
                )
            deadlines.append(self.session_opens[deadline_idx])
        return min(deadlines)

    def next_eligible(
        self, current: FuturesContract, *, decision_ts: Ms, policy: RollPolicy
    ) -> FuturesContract | None:
        """Immediate next expiry when known and safely before its own exit deadline.

        A missing or unsafe immediate successor fails closed. The selector never
        leaps farther down the curve because doing so would hide a lineage gap and
        materially change the registered roll exposure.
        """
        current_idx = self.contracts.index(current)
        if current_idx + 1 >= len(self.contracts):
            return None
        candidate = self.contracts[current_idx + 1]
        safely_live = decision_ts < self.exit_deadline(candidate, policy)
        return candidate if candidate.known_at(decision_ts) and safely_live else None


class RollAction(StrEnum):
    HOLD = "hold"
    ROLL = "roll"
    FLATTEN = "flatten"


@dataclass(frozen=True, slots=True, kw_only=True)
class RollDecision:
    """Deterministic lifecycle instruction emitted at the latest snapshot time."""

    action: RollAction
    decision_ts: Ms
    from_instrument_id: str
    to_instrument_id: str | None
    reason: str


def select_roll(
    chain: FuturesChain,
    current_instrument_id: str,
    snapshots: tuple[RollSnapshot, ...],
    policy: RollPolicy,
) -> RollDecision:
    """Select HOLD/ROLL/FLATTEN using only metadata and observations known at decision time."""
    if not snapshots:
        raise ValueError("at least one roll snapshot is required")
    times = [snapshot.decision_ts for snapshot in snapshots]
    if times != sorted(set(times)):
        raise ValueError("roll snapshots must be strictly increasing and unique")
    decision_ts = snapshots[-1].decision_ts
    current = chain.contract(current_instrument_id)
    if not current.known_at(decision_ts):
        raise LookaheadError(
            f"current contract metadata for {current.instrument_id!r} was not known at "
            f"decision {decision_ts}"
        )
    next_contract = chain.next_eligible(current, decision_ts=decision_ts, policy=policy)
    mandatory = decision_ts >= chain.exit_deadline(current, policy)
    if mandatory:
        if next_contract is None:
            return RollDecision(
                action=RollAction.FLATTEN,
                decision_ts=decision_ts,
                from_instrument_id=current.instrument_id,
                to_instrument_id=None,
                reason="mandatory_exit_no_eligible_later_contract",
            )
        return RollDecision(
            action=RollAction.ROLL,
            decision_ts=decision_ts,
            from_instrument_id=current.instrument_id,
            to_instrument_id=next_contract.instrument_id,
            reason="mandatory_first_notice_or_last_trade_buffer",
        )
    if next_contract is None or len(snapshots) < policy.volume_confirmation_sessions:
        return RollDecision(
            action=RollAction.HOLD,
            decision_ts=decision_ts,
            from_instrument_id=current.instrument_id,
            to_instrument_id=None,
            reason="no_confirmed_next_contract",
        )
    confirmation = snapshots[-policy.volume_confirmation_sessions :]
    confirmed = True
    for snapshot in confirmation:
        rows = snapshot.by_id()
        front = rows.get(current.instrument_id)
        nxt = rows.get(next_contract.instrument_id)
        if front is None or nxt is None or nxt.volume < front.volume * policy.next_volume_ratio:
            confirmed = False
            break
    if confirmed:
        return RollDecision(
            action=RollAction.ROLL,
            decision_ts=decision_ts,
            from_instrument_id=current.instrument_id,
            to_instrument_id=next_contract.instrument_id,
            reason="next_contract_volume_confirmed",
        )
    return RollDecision(
        action=RollAction.HOLD,
        decision_ts=decision_ts,
        from_instrument_id=current.instrument_id,
        to_instrument_id=None,
        reason="volume_confirmation_not_met",
    )


class FuturesExecutionBlocked(RuntimeError):
    """An order cannot execute under the effective exchange-limit state."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True, kw_only=True)
class FuturesPriceLimit:
    """One PIT daily price band with an explicit effective interval."""

    instrument_id: str
    limit_down: float
    limit_up: float
    effective_from: Ms
    effective_until: Ms
    available_at: Ms

    def __post_init__(self) -> None:
        _positive_finite("limit_down", self.limit_down)
        _positive_finite("limit_up", self.limit_up)
        if self.limit_down >= self.limit_up:
            raise ValueError("limit_down must be below limit_up")
        if self.effective_from >= self.effective_until:
            raise ValueError("effective_from must precede effective_until")
        if self.available_at > self.effective_until:
            raise ValueError("price-limit metadata cannot arrive after its effective interval")

    def require_executable(
        self,
        *,
        side: Side,
        decision_ts: Ms,
        last_price: float,
        executable_qty: float,
    ) -> None:
        """Fail closed when no liquidity exists, distinguishing locked limit states."""
        if self.available_at > decision_ts:
            raise LookaheadError(
                f"price limit for {self.instrument_id!r} available at {self.available_at} "
                f"exceeds decision {decision_ts}"
            )
        if not self.effective_from <= decision_ts < self.effective_until:
            raise FuturesExecutionBlocked("price_limit_not_effective")
        _positive_finite("last_price", last_price)
        _nonnegative_finite("executable_qty", executable_qty)
        if executable_qty > 0.0:
            return
        tolerance = max(abs(last_price), abs(self.limit_up), abs(self.limit_down)) * 1e-12
        if side is Side.BUY and last_price >= self.limit_up - tolerance:
            raise FuturesExecutionBlocked("locked_limit_up")
        if side is Side.SELL and last_price <= self.limit_down + tolerance:
            raise FuturesExecutionBlocked("locked_limit_down")
        raise FuturesExecutionBlocked("no_executable_liquidity")


def variation_margin(
    *,
    signed_contracts: float,
    previous_settlement: float,
    current_settlement: float,
    contract_multiplier: float,
) -> float:
    """Daily linear-futures cashflow; positive credits cash and negative debits it."""
    if not math.isfinite(signed_contracts):
        raise ValueError("signed_contracts must be finite")
    _positive_finite("previous_settlement", previous_settlement)
    _positive_finite("current_settlement", current_settlement)
    _positive_finite("contract_multiplier", contract_multiplier)
    return signed_contracts * contract_multiplier * (current_settlement - previous_settlement)
