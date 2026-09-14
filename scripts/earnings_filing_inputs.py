"""Isolated fiscal filing inputs; no forecasts, returns, or historical lake mutation.

Availability is modeled at midnight America/New_York two calendar dates after
filing date (one complete intervening day). This is not observed vendor delivery.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import re
from typing import Mapping, Iterable
from zoneinfo import ZoneInfo

@dataclass(frozen=True)
class Filing:
    security_id: str
    ticker: str
    datekey: date
    reportperiod: date
    fiscal_year: int
    fiscal_quarter: int
    available_at: datetime
    common_income: Decimal
    assets: Decimal


def prepare(row: Mapping[str, str], security_map: Mapping[str, str]) -> Filing:
    if row['dimension'] != 'ARQ':
        raise ValueError('Only as-reported quarterly inputs allowed')
    ticker = row['ticker']
    security = security_map.get(ticker)
    if not security:
        raise ValueError('Unmapped security; no ticker normalization fallback')
    dk, rp = date.fromisoformat(row['datekey']), date.fromisoformat(row['reportperiod'])
    if rp > dk:
        raise ValueError('Report period after filing date')
    match = re.fullmatch(r'(\d{4})-Q([1-4])', row['fiscalperiod'])
    if not match:
        raise ValueError('Unsupported fiscal period')
    income, assets = Decimal(row['netinccmn']), Decimal(row['assets'])
    if not income.is_finite() or not assets.is_finite() or assets <= 0:
        raise ValueError('Nonfinite income or nonpositive assets')
    available = datetime.combine(dk + timedelta(days=2), time(), ZoneInfo('America/New_York'))
    return Filing(security,ticker,dk,rp,int(match[1]),int(match[2]),available.astimezone(timezone.utc),income,assets)


def seasonal_pair(filings: Iterable[Filing], security_id: str, decision: datetime):
    """Return latest fiscal quarter + prior fiscal year's same quarter, or None.

    Later filings cannot change an earlier decision. Different report periods
    bearing the same fiscal label are ambiguous and excluded, not merged.
    Multiple versions of one report period select the latest known filing.
    """
    if decision.tzinfo is None or decision.utcoffset() is None:
        raise ValueError('Decision must be timezone aware')
    eligible=[f for f in filings if f.security_id==security_id and f.available_at<=decision]
    if not eligible:
        return None
    key=max((f.fiscal_year,f.fiscal_quarter) for f in eligible)
    result=[]
    for fiscal in (key,(key[0]-1,key[1])):
        group=[f for f in eligible if (f.fiscal_year,f.fiscal_quarter)==fiscal]
        if not group or len({f.reportperiod for f in group})!=1:
            return None
        latest=max(f.datekey for f in group)
        versions=set(f for f in group if f.datekey==latest)
        if len(versions)!=1:
            return None
        result.append(next(iter(versions)))
    # Reject fiscal-calendar changes masquerading as one-year comparisons.
    if not 330 <= (result[0].reportperiod-result[1].reportperiod).days <= 400:
        return None
    return tuple(result)
