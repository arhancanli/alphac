"""Strict assembly of multi-record spread definitions; no symbol-derived sides."""

from fractions import Fraction


def latest_legs(records, as_of_ns):
    known = [r for r in records if r["recv_ns"] <= as_of_ns]
    if not known:
        raise ValueError("no_prior_definition")
    stamp = max((r["recv_ns"], r["event_ns"]) for r in known)
    latest = [r for r in known if (r["recv_ns"], r["event_ns"]) == stamp]
    for field in ("publisher_id", "instrument_id", "raw_symbol", "leg_count", "action"):
        if len({r[field] for r in latest}) != 1:
            raise ValueError("inconsistent_definition")
    if latest[0]["action"] == "D":
        raise ValueError("deleted_definition")
    count = latest[0]["leg_count"]
    if count <= 0 or len(latest) != count or {r["leg_index"] for r in latest} != set(range(count)):
        raise ValueError("incomplete_or_duplicate_legs")
    return sorted(latest, key=lambda r: r["leg_index"])


def exposure(legs):
    result = {}
    for leg in legs:
        if leg["leg_side"] not in ("A", "B"):
            raise ValueError("undefined_leg_side")
        n, d = leg["numerator"], leg["denominator"]
        if type(n) is not int or type(d) is not int or n <= 0 or d <= 0:
            raise ValueError("invalid_leg_ratio")
        key = (leg["publisher_id"], leg["leg_instrument_id"])
        if key in result:
            raise ValueError("duplicate_leg_identity")
        result[key] = Fraction(n, d) * (1 if leg["leg_side"] == "B" else -1)
    return result
