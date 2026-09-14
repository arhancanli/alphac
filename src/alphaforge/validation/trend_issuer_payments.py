"""Strict extraction of the public Invesco distribution response."""

from datetime import date
from decimal import Decimal, InvalidOperation

from alphaforge.validation.trend_observation import ObservationError


def parse_invesco_distributions(payload: dict, *, cusip: str) -> list[dict]:
    if payload.get("cusip") != cusip or payload.get("currencyCode") != "USD":
        raise ObservationError("Issuer identity or currency mismatch")
    rows = payload.get("distributions")
    if not isinstance(rows, list) or not rows:
        raise ObservationError("Nonempty explicit distribution list required")
    output = []
    seen = set()
    for row in rows:
        try:
            dates = [date.fromisoformat(row[k]) for k in ("exDate", "recordDate", "payDate")]
            cash = Decimal(str(row["distributionAmountPerUnit"]))
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ObservationError("Invalid issuer distribution fields") from exc
        if not dates[0] <= dates[1] <= dates[2]:
            raise ObservationError("Issuer payment date order invalid")
        if not cash.is_finite() or cash < 0:
            raise ObservationError("Finite nonnegative issuer total required")
        if dates[0] in seen:
            raise ObservationError("Ambiguous duplicate issuer ex-date")
        seen.add(dates[0])
        output.append({**row, "raw_cash": str(cash)})
    return output
