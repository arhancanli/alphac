from decimal import Decimal as D

import pytest

from alphaforge.validation.refining_spread_units import RefiningQuotes, recipe_mark_change


def test_recipe_units_and_per_barrel_reconcile():
    q = RefiningQuotes(D("75"), D("2.2"), D("2.4"))
    assert q.crack_usd_per_input_barrel == D("20.2")
    assert q.standard_recipe_mark_usd == D("60600")
    assert q.standard_recipe_mark_usd == 3000 * q.crack_usd_per_input_barrel


@pytest.mark.parametrize("field,expected", [(0, D("-3000")), (1, D("840")), (2, D("420"))])
def test_leg_moves_match_contract_multipliers(field, expected):
    before = [D("75"), D("2.2"), D("2.4")]
    after = before.copy()
    after[field] += D("1") if field == 0 else D(".01")
    assert recipe_mark_change(RefiningQuotes(*before), RefiningQuotes(*after)) == expected
    assert (
        recipe_mark_change(RefiningQuotes(*before), RefiningQuotes(*after), recipes=-2)
        == -2 * expected
    )


def test_zero_spread_and_negative_oil_do_not_use_percentage_returns():
    zero = RefiningQuotes(D("84"), D("2"), D("2"))
    assert zero.standard_recipe_mark_usd == 0
    negative = RefiningQuotes(D("-1"), D("2"), D("2"))
    assert recipe_mark_change(zero, negative) == D("255000")


@pytest.mark.parametrize("bad", [1.0, D("NaN"), D("Infinity")])
def test_untyped_or_nonfinite_quotes_rejected(bad):
    with pytest.raises(ValueError):
        RefiningQuotes(bad, D("2"), D("2"))


def test_boolean_recipe_count_rejected():
    q = RefiningQuotes(D("75"), D("2"), D("2"))
    with pytest.raises(ValueError):
        recipe_mark_change(q, q, recipes=True)
