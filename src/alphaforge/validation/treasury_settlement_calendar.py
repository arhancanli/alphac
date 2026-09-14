"""Combine supplied service and market calendars without inferring missing days."""

from datetime import date, timedelta


def regular_settlement_date(trade_date, fedwire_open, market_good, *, lag=1):
    """Count jointly eligible dates. Caller must bind lag and both calendars to sources."""
    if type(trade_date) is not date or type(lag) is not int or lag < 1:
        raise ValueError("explicit date and positive integer lag required")
    current = trade_date
    remaining = lag
    while remaining:
        current += timedelta(days=1)
        # Even a weekend must be represented; absent evidence is not a holiday rule.
        if current not in fedwire_open or current not in market_good:
            raise ValueError(f"unverified calendar date: {current}")
        if type(fedwire_open[current]) is not bool or type(market_good[current]) is not bool:
            raise ValueError("calendar states must be explicit booleans")
        if fedwire_open[current] and market_good[current]:
            remaining -= 1
    return current
