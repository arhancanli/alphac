import numpy as np
import pandas as pd
import pytest

from alphaforge.config.settings import SignalsCfg
from alphaforge.core.calendar import calendar_for
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass
from alphaforge.signals.causal_trend import CausalTrendSignalService, released_weights


def fixture_panel():
    service = object.__new__(CausalTrendSignalService)
    service._calendar = calendar_for(AssetClass.EQUITY)
    service._anchor_tf = Timeframe.D1
    service._cfg = SignalsCfg(horizon_bars=2)
    service._min_members = 5
    from types import SimpleNamespace

    service._alpha_specs = tuple(SimpleNamespace(name=n) for n in ("a", "b", "c"))
    start = int(pd.Timestamp("2026-01-12", tz="UTC").timestamp() * 1000)
    end = int(pd.Timestamp("2026-02-20", tz="UTC").timestamp() * 1000)
    sessions = service._calendar.expected_bar_opens(start, end, Timeframe.D1)
    service.history_anchor = start
    index = pd.MultiIndex.from_product(
        [sessions, list("ABCDEF")], names=["ts_open", "instrument_id"]
    )
    rng = np.random.default_rng(42)
    frame = pd.DataFrame({"open_px": 100 * np.exp(rng.normal(0, 0.1, len(index)))}, index=index)
    mask = pd.Series(True, index=index)
    zs = {n: pd.Series(rng.normal(size=len(index)), index=index) for n in service.alpha_names}
    return service, sessions, frame, mask, zs


def test_release_is_exit_session_not_prior_grid_point():
    service, sessions, frame, mask, zs = fixture_panel()
    weights = service._weights_from_panel(frame, mask, zs)
    assert weights.weights.index[0] == sessions[3]  # entry+1, h=2, exit+3
    np.testing.assert_array_equal(weights.asof(sessions[2]), [1 / 3] * 3)
    assert not np.allclose(weights.asof(sessions[3]), [1 / 3] * 3)
    assert pd.to_datetime(sessions[5], unit="ms").day == 20  # MLK holiday skipped


def test_every_prefix_matches_full_including_maturity_and_missing_prices():
    service, sessions, frame, mask, zs = fixture_panel()
    frame.loc[(sessions[3], "A"), "open_px"] = np.nan
    frame.loc[(sessions[7], slice(None)), "open_px"] = np.nan
    full = service._weights_from_panel(frame, mask, zs)
    for t in sessions:
        selected = frame.index.get_level_values(0) <= t
        prefix = service._weights_from_panel(
            frame.loc[selected], mask.loc[selected], {n: z.loc[selected] for n, z in zs.items()}
        )
        np.testing.assert_allclose(prefix.asof(t), full.asof(t), rtol=0, atol=0)


def test_future_price_perturbation_cannot_change_prior_weights():
    service, sessions, frame, mask, zs = fixture_panel()
    full = service._weights_from_panel(frame, mask, zs)
    altered = frame.copy()
    future = altered.index.get_level_values(0) > sessions[9]
    altered.loc[future, "open_px"] *= np.linspace(0.1, 10, future.sum())
    other = service._weights_from_panel(altered, mask, zs)
    for t in sessions[:10]:
        np.testing.assert_array_equal(full.asof(t), other.asof(t))


def test_truncated_history_and_missing_session_fail_instead_of_rephasing():
    service, sessions, frame, mask, zs = fixture_panel()
    for removed in (sessions[0], sessions[4]):
        selected = frame.index.get_level_values(0) != removed
        with pytest.raises(ValueError, match="complete session prefix"):
            service._weights_from_panel(
                frame.loc[selected], mask.loc[selected], {n: z.loc[selected] for n, z in zs.items()}
            )


def test_nan_ic_is_not_zero_evidence_and_cold_start_is_equal():
    ics = pd.DataFrame({"a": [np.nan, 0.8, np.nan], "b": [np.nan, -0.2, np.nan]}, index=[1, 3, 5])
    weights = released_weights(ics, pd.Index([4, 6, 8]))
    np.testing.assert_array_equal(weights.asof(4), [0.5, 0.5])
    np.testing.assert_array_equal(weights.asof(6), weights.asof(8))
    assert weights.asof(6)["a"] > 0.9
    with pytest.raises(ValueError, match="after"):
        released_weights(ics, pd.Index([1, 4, 6]))
