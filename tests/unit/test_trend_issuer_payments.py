import copy

import pytest

from alphaforge.validation.trend_issuer_payments import parse_invesco_distributions
from alphaforge.validation.trend_observation import ObservationError


def sample():
    return {
        "cusip": "46138K103",
        "currencyCode": "USD",
        "distributions": [
            {
                "exDate": "2006-01-03",
                "recordDate": "2006-01-04",
                "payDate": "2006-01-10",
                "distributionAmountPerUnit": 0.12672,
                "ordinaryIncomeDistribution": None,
            }
        ],
    }


def test_pay_date_is_explicit_and_components_preserved():
    payload = sample()
    before = copy.deepcopy(payload)
    (row,) = parse_invesco_distributions(payload, cusip="46138K103")
    assert row["payDate"] == "2006-01-10"
    assert row["raw_cash"] == "0.12672"
    assert row["ordinaryIncomeDistribution"] is None
    assert payload == before


@pytest.mark.parametrize(
    "change",
    [
        {"payDate": "2006-01-03"},
        {"payDate": None},
        {"distributionAmountPerUnit": None},
        {"distributionAmountPerUnit": float("inf")},
        {"distributionAmountPerUnit": -0.1},
    ],
)
def test_invalid_distribution_rejected(change):
    payload = sample()
    payload["distributions"][0].update(change)
    with pytest.raises(ObservationError):
        parse_invesco_distributions(payload, cusip="46138K103")


def test_duplicate_dates_rejected_instead_of_summed():
    payload = sample()
    payload["distributions"] *= 2
    with pytest.raises(ObservationError):
        parse_invesco_distributions(payload, cusip="46138K103")


@pytest.mark.parametrize("field,value", [("cusip", "WRONG"), ("currencyCode", "EUR")])
def test_identity_and_currency_required(field, value):
    payload = sample()
    payload[field] = value
    with pytest.raises(ObservationError):
        parse_invesco_distributions(payload, cusip="46138K103")
