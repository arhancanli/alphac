"""Research-only signed forecast-revision basket, with explicit availability gates."""

import math
from datetime import datetime, timedelta

CROPS = frozenset({"corn", "wheat", "soybeans"})


def research_basket(rows: list[dict], decision_at: datetime) -> dict:
    """Caller supplies independently verified availability; this is not an order router."""
    if decision_at.utcoffset() is None:
        raise ValueError("decision must be timezone-aware")
    if len(rows) != 3 or {r.get("crop") for r in rows} != CROPS:
        return {"status": "BLOCKED", "reason": "incomplete crop basket", "weights": {}}
    if (
        len({r.get("date_label") for r in rows}) != 1
        or len({r.get("report_id") for r in rows}) != 1
        or any(not r.get("date_label") or not r.get("report_id") for r in rows)
    ):
        return {"status": "BLOCKED", "reason": "mixed or missing report identity", "weights": {}}
    for row in rows:
        if row.get("status") != "REVISION_OBSERVED":
            return {"status": "BLOCKED", "reason": "no comparable original revision", "weights": {}}
        for key in ("available_at", "prior_available_at"):
            value = row.get(key)
            if not isinstance(value, datetime) or value.utcoffset() is None:
                return {"status": "BLOCKED", "reason": "unverified availability", "weights": {}}
        if row["prior_available_at"] >= row["available_at"]:
            return {"status": "BLOCKED", "reason": "invalid vintage ordering", "weights": {}}
        if row["available_at"] + timedelta(minutes=5) > decision_at:
            return {"status": "BLOCKED", "reason": "information delay not elapsed", "weights": {}}
        if decision_at - row["available_at"] > timedelta(minutes=15):
            return {"status": "BLOCKED", "reason": "stale event", "weights": {}}
        change = row.get("stocks_to_use_change")
        if (
            isinstance(change, bool)
            or not isinstance(change, (float, int))
            or not math.isfinite(change)
        ):
            return {"status": "BLOCKED", "reason": "invalid revision", "weights": {}}
    weights = {
        r["crop"]: (
            -1 / 3
            if r["stocks_to_use_change"] > 0
            else 1 / 3
            if r["stocks_to_use_change"] < 0
            else 0.0
        )
        for r in rows
    }
    return {"status": "RESEARCH_WEIGHTS_ONLY", "weights": weights, "execution_eligible": False}
