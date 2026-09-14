"""Economic split conservation and causal boundaries on synthetic prices only."""

import numpy as np
import pandas as pd
import pytest
from alphamax_share_ratio_features import share_ratio_close, share_ratio_sigma

from alphaforge.core.time import Timeframe
from alphaforge.features.library.equity_price import adjusted_close
from alphaforge.features.library.momentum import xs_momentum
from alphaforge.features.library.vol import ewma_vol


def world(ratio=4.0):
    index = np.arange(600, dtype=np.int64) * Timeframe.D1.ms
    economic = pd.DataFrame({"SYNTH": 100 * np.exp(np.arange(600) * 0.001)}, index=index)
    raw = economic.copy()
    raw.loc[index[300] :] /= ratio
    actions = pd.DataFrame(
        [
            {
                "instrument_id": "SYNTH",
                "action_type": "split",
                "ex_date": index[300],
                "available_at": index[300],
                "ratio": ratio,
                "cash_amount": np.nan,
            }
        ]
    )
    return economic, raw, actions


@pytest.mark.parametrize("ratio", [2.0, 4.0, 20.0, 0.125])
def test_forward_and_reverse_split_preserve_economic_returns(ratio):
    economic, raw, actions = world(ratio)
    corrected = share_ratio_close(raw, actions)
    np.testing.assert_allclose(
        np.log(corrected).diff(), np.log(economic).diff(), atol=2e-15, equal_nan=True
    )
    np.testing.assert_allclose(
        share_ratio_sigma(raw, actions), ewma_vol(economic), atol=2e-15, equal_nan=True
    )
    np.testing.assert_allclose(
        xs_momentum(corrected, lookback=252, skip=21),
        xs_momentum(economic, lookback=252, skip=21),
        atol=2e-15,
        equal_nan=True,
    )
    # Verify split conservation independently: old quantity1 becomes ratio,
    # new price economic/ratio; total marked capital is unchanged.
    assert ratio * raw.iloc[300, 0] == pytest.approx(economic.iloc[300, 0])


def test_legacy_factor_inverts_share_units_and_raw_sigma_spikes():
    economic, raw, actions = world()
    legacy = adjusted_close(raw, actions, tf_ms=Timeframe.D1.ms, include_dividends=False)
    observed = np.log(legacy).diff().iloc[300, 0]
    assert observed == pytest.approx(0.001 - 2 * np.log(4))
    assert ewma_vol(raw).iloc[300, 0] > 100 * ewma_vol(economic).iloc[300, 0]


def test_future_split_does_not_change_prior_feature_outputs():
    _, raw, actions = world()
    prefix = raw.iloc[:300]
    np.testing.assert_allclose(
        share_ratio_sigma(prefix, actions), ewma_vol(prefix), atol=2e-15, equal_nan=True
    )
    full = share_ratio_sigma(raw, actions)
    np.testing.assert_allclose(
        full.iloc[:300], share_ratio_sigma(prefix, actions), atol=2e-15, equal_nan=True
    )


def test_late_information_rejected_and_missing_prices_not_filled():
    _, raw, actions = world()
    late = actions.assign(available_at=actions.ex_date + 2 * Timeframe.D1.ms)
    with pytest.raises(ValueError, match="late split"):
        share_ratio_sigma(raw, late)
    raw.iloc[299] = np.nan
    adjusted = share_ratio_close(raw, actions)
    assert adjusted.iloc[299].isna().all()
    assert np.log(adjusted).diff().iloc[300].isna().all()


def test_no_action_parity_and_inputs_unchanged():
    _, raw, actions = world()
    r, a = raw.copy(deep=True), actions.copy(deep=True)
    np.testing.assert_allclose(
        share_ratio_sigma(raw, actions.iloc[:0]), ewma_vol(raw), atol=0, equal_nan=True
    )
    share_ratio_sigma(raw, actions)
    pd.testing.assert_frame_equal(raw, r)
    pd.testing.assert_frame_equal(actions, a)
