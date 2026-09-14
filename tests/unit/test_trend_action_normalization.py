import pandas as pd
import pytest

from alphaforge.validation.trend_action_normalization import normalize_actions
from alphaforge.validation.trend_observation import ObservationError


def actions():
    return pd.DataFrame(
        [
            {"ticker": "ABC", "date": "2026-09-10", "action": "dividend", "value": 0.25},
            {"ticker": "ABC", "date": "2026-09-11", "action": "split", "value": 2.0},
        ]
    )


def test_dividend_unadjusted_to_ex_date_share_basis():
    source = actions()
    out = normalize_actions(source, observed_ms=1800000000000)
    assert out.raw_value.tolist() == [0.5, 2.0]
    assert source.value.tolist() == [0.25, 2.0]
    assert "available_at" not in out and out.observed_ms.eq(1800000000000).all()


def test_reverse_split_and_symbol_isolation():
    source = actions()
    source.loc[1, "value"] = 0.1
    assert normalize_actions(source, observed_ms=1).raw_value.iloc[0] == 0.025
    source.loc[1, "ticker"] = "XYZ"
    assert normalize_actions(source, observed_ms=1).raw_value.iloc[0] == 0.25


def test_dividend_after_split_unchanged():
    source = actions()
    source.loc[:, "date"] = ["2026-09-11", "2026-09-10"]
    assert normalize_actions(source, observed_ms=1).raw_value.iloc[0] == 0.25


@pytest.mark.parametrize("case", ["same_day", "duplicate", "negative"])
def test_bad_actions(case):
    source = actions()
    if case == "same_day":
        source.loc[1, "date"] = source.loc[0, "date"]
    elif case == "duplicate":
        source = pd.concat([source, source.iloc[:1]])
    else:
        source.loc[0, "value"] = -1
    with pytest.raises(ObservationError):
        normalize_actions(source, observed_ms=1)
