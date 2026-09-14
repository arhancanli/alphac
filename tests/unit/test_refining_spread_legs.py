import pytest

from alphaforge.validation.refining_spread_legs import exposure, latest_legs


def rows():
    base = {
        "recv_ns": 100,
        "event_ns": 90,
        "publisher_id": 1,
        "instrument_id": 50,
        "raw_symbol": "CRACK",
        "leg_count": 2,
        "action": "A",
        "numerator": 1,
        "denominator": 1,
    }
    return [
        dict(base, leg_index=0, leg_instrument_id=10, leg_side="A"),
        dict(base, leg_index=1, leg_instrument_id=20, leg_side="B"),
    ]


def test_two_records_retained_and_signed():
    legs = latest_legs(rows(), 100)
    assert exposure(legs) == {(1, 10): -1, (1, 20): 1}


def test_no_symbol_inference_for_same_side_anomaly():
    legs = rows()
    legs[1]["leg_side"] = "A"
    assert exposure(legs) != {(1, 10): -1, (1, 20): 1}


def test_partial_latest_snapshot_cannot_borrow_old_leg():
    partial = dict(rows()[0], recv_ns=110)
    with pytest.raises(ValueError, match="incomplete"):
        latest_legs([*rows(), partial], 110)
    assert len(latest_legs([*rows(), partial], 109)) == 2


@pytest.mark.parametrize(
    "change", [{"leg_side": "N"}, {"denominator": 0}, {"numerator": -1}, {"numerator": True}]
)
def test_bad_ratio_or_side(change):
    legs = rows()
    legs[0].update(change)
    with pytest.raises(ValueError):
        exposure(legs)


def test_deleted_snapshot_refused():
    legs = [dict(r, recv_ns=110, action="D") for r in rows()]
    with pytest.raises(ValueError, match="deleted"):
        latest_legs([*rows(), *legs], 110)


def test_duplicate_leg_refused():
    with pytest.raises(ValueError, match="incomplete"):
        latest_legs([rows()[0], rows()[0]], 100)
