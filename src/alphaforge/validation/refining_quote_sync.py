"""Conservative three-leg quote indications, not fill or portfolio-return simulation."""

import re
from bisect import bisect_right
from dataclasses import dataclass

from databento_dbn import F_BAD_TS_RECV, F_LAST, F_MAYBE_BAD_BOOK, F_SNAPSHOT

SCALE = 1_000_000_000
UNDEFINED_PRICE = 2**63 - 1
MONTHS = "FGHJKMNQUVXZ"
ROOTS = ("CL", "RB", "HO")
MULTIPLIERS = {"CL": 1000, "RB": 42000, "HO": 42000}
RATIOS = {"CL": 3, "RB": 2, "HO": 1}


@dataclass(frozen=True)
class Contract:
    root: str
    raw_symbol: str
    publisher_id: int
    instrument_id: int
    year: int
    month: int
    observed_ns: int
    activation_ns: int
    expiration_ns: int
    currency: str
    unit: str
    size: int
    tick_fixed: int

    def validate(self, *, as_of_ns, expiry_buffer_ns):
        match = re.fullmatch(r"(CL|RB|HO)([FGHJKMNQUVXZ])([0-9]{1,4})", self.raw_symbol)
        numbers = (
            self.publisher_id,
            self.instrument_id,
            self.year,
            self.month,
            self.observed_ns,
            self.activation_ns,
            self.expiration_ns,
            self.size,
            self.tick_fixed,
            as_of_ns,
            expiry_buffer_ns,
        )
        if any(type(n) is not int or n < 0 for n in numbers):
            raise ValueError("Nonnegative integer identity, timing and unit fields required")
        if not match or self.root != match[1] or not 2000 <= self.year <= 2100:
            raise ValueError("Supported outright contract and full maturity year required")
        if self.month != MONTHS.index(match[2]) + 1 or self.year % (10 ** len(match[3])) != int(
            match[3]
        ):
            raise ValueError("Symbol and full maturity disagree")
        if self.observed_ns > as_of_ns or self.activation_ns > as_of_ns:
            raise ValueError("Definition or contract not yet available")
        if self.expiration_ns <= as_of_ns + expiry_buffer_ns:
            raise ValueError("Expiry buffer violated")
        if (
            self.currency != "USD"
            or self.unit != ("BBL" if self.root == "CL" else "GAL")
            or self.size != MULTIPLIERS[self.root]
            or self.tick_fixed <= 0
        ):
            raise ValueError("Contract cash units not verified")


def select_month(contracts, *, as_of_ns, expiry_buffer_ns):
    """Earliest unambiguous full delivery month; selection never reads quote prices."""
    months = {}
    for contract in contracts:
        try:
            contract.validate(as_of_ns=as_of_ns, expiry_buffer_ns=expiry_buffer_ns)
        except ValueError:
            continue
        group = months.setdefault((contract.year, contract.month), {})
        group.setdefault(contract.root, []).append(contract)
    for month in sorted(months):
        group = months[month]
        if set(group) != set(ROOTS):
            continue
        if any(len(group[root]) != 1 for root in ROOTS):
            raise ValueError("Ambiguous contract mapping for earliest complete delivery month")
        selected = {root: group[root][0] for root in ROOTS}
        if len({(c.publisher_id, c.instrument_id) for c in selected.values()}) != 3:
            raise ValueError("Distinct instrument identities required")
        return selected
    raise ValueError("No complete eligible delivery month")


@dataclass(frozen=True)
class Quote:
    publisher_id: int
    instrument_id: int
    recv_ns: int
    event_ns: int
    flags: int
    bid_fixed: int
    ask_fixed: int
    bid_size: int
    ask_size: int


def quote_indication(contracts, quotes, *, decision_ns, max_age_ns, max_skew_ns):
    """Use latest raw states supplied by caller; never revive an older valid quote.

    Fixed-point dollar prices are already normalized. Do not apply display_factor.
    Rejecting partial/bad/empty last states avoids stale last-good-book substitution.
    """
    if any(type(n) is not int or n < 0 for n in (decision_ns, max_age_ns, max_skew_ns)):
        raise ValueError("Nonnegative integer timing controls required")
    if set(contracts) != set(ROOTS) or set(quotes) != set(ROOTS):
        raise ValueError("Exactly three product legs required")
    if len({(c.year, c.month) for c in contracts.values()}) != 1:
        raise ValueError("Mixed delivery months")
    times = []
    sizes = []
    buy_fixed = sell_fixed = 0
    for root in ROOTS:
        c, q = contracts[root], quotes[root]
        if c.root != root:
            raise ValueError("Contract root mismatch")
        c.validate(as_of_ns=decision_ns, expiry_buffer_ns=0)
        if q is None:
            return {"valid": False, "reason": f"{root}:no_prior_quote"}
        if any(
            type(n) is not int
            for n in (
                q.publisher_id,
                q.instrument_id,
                q.recv_ns,
                q.event_ns,
                q.flags,
                q.bid_fixed,
                q.ask_fixed,
                q.bid_size,
                q.ask_size,
            )
        ):
            raise ValueError("Integer raw quote fields required")
        if (q.publisher_id, q.instrument_id) != (c.publisher_id, c.instrument_id):
            raise ValueError("Quote/contract identity mismatch")
        if not 0 <= q.recv_ns <= decision_ns or not 0 <= q.event_ns <= q.recv_ns:
            return {"valid": False, "reason": f"{root}:invalid_clock"}
        if decision_ns - q.recv_ns > max_age_ns or decision_ns - q.event_ns > max_age_ns:
            return {"valid": False, "reason": f"{root}:stale"}
        if not q.flags & F_LAST or q.flags & (F_BAD_TS_RECV | F_MAYBE_BAD_BOOK | F_SNAPSHOT):
            return {"valid": False, "reason": f"{root}:feed_state"}
        if (
            q.bid_fixed == UNDEFINED_PRICE
            or q.ask_fixed == UNDEFINED_PRICE
            or q.bid_fixed > q.ask_fixed
            or q.bid_size <= 0
            or q.ask_size <= 0
        ):
            return {"valid": False, "reason": f"{root}:invalid_book"}
        if q.bid_fixed % c.tick_fixed or q.ask_fixed % c.tick_fixed:
            return {"valid": False, "reason": f"{root}:off_tick"}
        times.append(q.recv_ns)
        sizes.append(min(q.bid_size, q.ask_size) // RATIOS[root])
        coefficient = RATIOS[root] * MULTIPLIERS[root]
        if root == "CL":
            buy_fixed -= coefficient * q.bid_fixed
            sell_fixed -= coefficient * q.ask_fixed
        else:
            buy_fixed += coefficient * q.ask_fixed
            sell_fixed += coefficient * q.bid_fixed
    if max(times) - min(times) > max_skew_ns:
        return {"valid": False, "reason": "cross_leg_skew"}
    if min(sizes) < 1:
        return {"valid": False, "reason": "insufficient_recipe_size"}
    return {
        "valid": True,
        "reason": "accepted",
        "buy_recipe_fixed_usd": buy_fixed,
        "sell_recipe_fixed_usd": sell_fixed,
        "roundtrip_width_fixed_usd": buy_fixed - sell_fixed,
        "displayed_two_way_recipes": min(sizes),
        "max_age_ns": decision_ns - min(times),
        "cross_leg_skew_ns": max(times) - min(times),
    }


class QuoteTimeline:
    """Preserve feed order at equal receive timestamps; invalid states stay visible."""

    def __init__(self, quotes):
        self._quotes = tuple(quotes)
        self._times = tuple(q.recv_ns for q in self._quotes)
        if any(type(t) is not int or t < 0 for t in self._times):
            raise ValueError("Integer receive timestamps required")
        if any(a > b for a, b in zip(self._times, self._times[1:], strict=False)):
            raise ValueError("Nonmonotonic receive stream")

    def at(self, decision_ns):
        if type(decision_ns) is not int or decision_ns < 0:
            raise ValueError("Integer decision timestamp required")
        index = bisect_right(self._times, decision_ns) - 1
        return self._quotes[index] if index >= 0 else None
