"""Direction-preserving blend must retain timing, missingness and membership semantics."""

import numpy as np
import pandas as pd
import pytest

from alphaforge.signals.blending import BlendWeights, blend


def test_direction_survives_centering_and_nonmembers_cannot_change_scale():
    index = pd.MultiIndex.from_product([[10], list("abcdef")], names=["ts_open", "instrument_id"])
    a = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 1e9], index=index)
    mask = pd.Series([True] * 5 + [False], index=index)
    weights = BlendWeights.equal(("a",))
    baseline = blend({"a": a}, weights, mask)
    observed = blend({"a": a}, weights, mask, normalization="directional_rms")
    assert baseline.iloc[0] < 0
    assert (observed.iloc[:5] > 0).all()
    np.testing.assert_allclose(observed.iloc[:5], np.arange(1, 6) / np.sqrt(11))
    assert np.isnan(observed.iloc[-1])
    a.iloc[-1] = -1e20
    pd.testing.assert_series_equal(
        observed, blend({"a": a}, weights, mask, normalization="directional_rms")
    )


@pytest.mark.parametrize("value", [-2.0, 2.0, 0.0])
def test_unanimous_direction_and_zero_rms(value):
    index = pd.MultiIndex.from_product([[10], list("abcde")])
    a = pd.Series(value, index=index)
    result = blend(
        {"a": a},
        BlendWeights.equal(("a",)),
        pd.Series(True, index=index),
        normalization="directional_rms",
    )
    if value == 0:
        assert result.isna().all()
    else:
        assert (result == np.sign(value)).all()


def test_missing_factor_drops_member_without_partial_reweighting():
    index = pd.MultiIndex.from_product([[10], list("abcde")])
    a = pd.Series(1.0, index=index)
    b = pd.Series([np.nan, 2.0, 3.0, 4.0, 5.0], index=index)
    result = blend(
        {"a": a, "b": b},
        BlendWeights.equal(("a", "b")),
        pd.Series(True, index=index),
        normalization="directional_rms",
    )
    assert result.isna().all()  # four complete members is below the unchanged floor


def test_future_weight_cannot_change_present_direction():
    index = pd.MultiIndex.from_product([[10, 20], list("abcde")])
    a, b = pd.Series(1.0, index=index), pd.Series(-1.0, index=index)
    grid = pd.Index([20], name="ts_open")
    w = pd.DataFrame([[0.9, 0.1]], index=grid, columns=["a", "b"])
    weights = BlendWeights(alpha_names=("a", "b"), weights=w, smoothed_ic=w.copy())
    result = blend(
        {"a": a, "b": b}, weights, pd.Series(True, index=index), normalization="directional_rms"
    )
    assert result.loc[10].isna().all()  # equal cold-start blend cancels to zero
    assert (result.loc[20] == 1.0).all()


def test_invalid_normalization_rejected():
    with pytest.raises(ValueError, match="normalization"):
        blend({}, BlendWeights.equal(("a",)), pd.Series(dtype=bool), normalization="typo")


def test_signal_service_opt_in_is_scoped_and_shared_emitter_preserves_direction():
    from alphaforge.config.settings import SignalsCfg
    from alphaforge.config.sleeve import sleeve_for
    from alphaforge.core.types import AssetClass
    from alphaforge.features.registry import default_registry
    from alphaforge.research import zoo
    from alphaforge.signals.service import SIGMA_COLUMN, SignalService

    zoo.register_all()
    kwargs = {
        "engine": None,
        "universe": None,
        "registry": default_registry(),
        "cfg": SignalsCfg(horizon_bars=21),
        "alpha_names": ["mf_trend_63", "mf_trend_126", "mf_trend_252"],
        "blend_normalization": "directional_rms",
    }
    with pytest.raises(ValueError, match="restricted"):
        SignalService(**kwargs)  # default crypto sleeve is not eligible
    service = SignalService(**kwargs, sleeve=sleeve_for(AssetClass.EQUITY))
    assert service.trial_binding == {"trend_blend_normalization": "directional_rms"}
    kwargs["blend_normalization"] = "cross_sectional_zscore"
    baseline = SignalService(**kwargs, sleeve=sleeve_for(AssetClass.EQUITY))
    assert baseline.trial_binding == {}
    index = pd.MultiIndex.from_product([[10], list("abcde")], names=["ts_open", "instrument_id"])
    frame = pd.DataFrame({SIGMA_COLUMN: 0.01}, index=index)
    zs = {name: pd.Series(np.arange(1.0, 6.0), index=index) for name in service.alpha_names}
    weights = BlendWeights.equal(service.alpha_names)
    mask = pd.Series(True, index=index)
    candidate = service._emit(frame, mask, zs, weights)
    previous = baseline._emit(frame, mask, zs, weights)
    assert (candidate.mu_ann > 0).all()
    assert previous.mu_ann.iloc[0] < 0
    expected_mu = 0.02 * 0.01 * np.sqrt(21) * (np.arange(1, 6) / np.sqrt(11)) * 252 / 21
    np.testing.assert_allclose(candidate.mu_ann, expected_mu)
