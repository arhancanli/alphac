"""Pure arithmetic and identity checks for a proposed Treasury implementation."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction


def number(value):
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("finite Decimal required")
    return Fraction(value)


def duration_hedge(target_value, durations, dirty_prices):
    """Signed market values and faces per $100 quote; no rounding or fill claim."""
    roots = {"bill_6m", "note_2y", "note_10y"}
    if set(durations) != roots or set(dirty_prices) != roots:
        raise ValueError("exact three instruments required")
    target = number(target_value)
    d = {k: number(v) for k, v in durations.items()}
    p = {k: number(v) for k, v in dirty_prices.items()}
    if not 0 < d["bill_6m"] < d["note_2y"] < d["note_10y"]:
        raise ValueError("durations must bracket target")
    if any(v <= 0 for v in p.values()) or target == 0:
        raise ValueError("positive prices and nonzero target required")
    long_value = -target * (d["note_2y"] - d["bill_6m"]) / (d["note_10y"] - d["bill_6m"])
    values = {"note_2y": target, "note_10y": long_value, "bill_6m": -target - long_value}
    faces = {k: 100 * v / p[k] for k, v in values.items()}
    assert sum(values.values()) == 0
    assert sum(values[k] * d[k] for k in roots) == 0
    return {"market_values": values, "face_values": faces}


@dataclass(frozen=True)
class ExecutionKey:
    cusip: str
    settlement_date: date
    settlement_regime: str
    venue: str
    account: str
    currency: str
    financing_id: str

    def __post_init__(self):
        if type(self.settlement_date) is not date:
            raise ValueError("explicit settlement date required")
        if len(self.cusip) != 9 or not self.cusip.isalnum():
            raise ValueError("CUSIP required")
        if self.settlement_regime not in ("regular", "when_issued", "reopening"):
            raise ValueError("explicit settlement regime required")
        if self.currency != "USD" or any(
            not isinstance(v, str) or not v.strip()
            for v in (self.venue, self.account, self.financing_id)
        ):
            raise ValueError("complete execution identity required")


def aggregate_instructions(instructions):
    """Combine one execution batch while retaining signed event attribution."""
    result = {}
    for event, key, face in instructions:
        if not isinstance(event, str) or not event or not isinstance(key, ExecutionKey):
            raise ValueError("event and execution key required")
        amount = number(face)
        entry = result.setdefault(key, {"net_face": Fraction(0), "by_event": {}})
        entry["net_face"] += amount
        entry["by_event"][event] = entry["by_event"].get(event, Fraction(0)) + amount
    return result


def validate_settlement(trade_date, settle_date, regime, first_issue, tranche_issue, open_dates):
    """Requires an externally verified calendar; never assumes weekdays mean open."""
    if any(type(v) is not date for v in (trade_date, settle_date, first_issue, tranche_issue)):
        raise ValueError("dates required")
    if settle_date < trade_date or settle_date not in open_dates:
        raise ValueError("invalid settlement session")
    if first_issue > tranche_issue:
        raise ValueError("invalid issue lineage")
    if regime == "when_issued":
        if trade_date >= first_issue or settle_date != first_issue:
            raise ValueError("when-issued requires original issuance settlement")
    elif regime == "reopening":
        if not first_issue <= trade_date < tranche_issue or settle_date != tranche_issue:
            raise ValueError("reopening requires explicit tranche settlement")
    elif regime == "regular":
        if trade_date < first_issue:
            raise ValueError("security not issued")
        future = sorted(d for d in open_dates if d > trade_date)
        if not future or settle_date != future[0]:
            raise ValueError("regular route requires next supplied settlement session")
    else:
        raise ValueError("unknown settlement regime")
