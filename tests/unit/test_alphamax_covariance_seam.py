from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from alphamax_covariance_engine import install_covariance_basis

from alphaforge.core.time import Timeframe
from alphaforge.signals.blending import estimate_blend_weights


def test_covariance_hook_is_per_instance_and_stable_across_legs(monkeypatch):
    import alphamax_covariance_engine as module

    calls = []

    def panel(reader, ctx, ids, window, *, correct_splits):
        calls.append((reader, ctx, ids, window, correct_splits))
        return "panel"

    monkeypatch.setattr(module, "session_close_panel", panel)
    reader = object()
    original = lambda *args: "legacy"
    a = SimpleNamespace(_close_panel=original, _cov_window_bars=720)
    b = SimpleNamespace(_close_panel=original, _cov_window_bars=720)
    install_covariance_basis(a, reader, "sessions_splits")
    assert a._close_panel("ctx", ["SYNTH"]) == "panel"
    assert calls[-1] == (reader, "ctx", ["SYNTH"], 721, True)
    hook = a._close_panel
    install_covariance_basis(a, reader, "sessions_splits")
    assert a._close_panel is hook
    assert b._close_panel is original
    with pytest.raises(ValueError, match="cannot change"):
        install_covariance_basis(a, reader, "sessions")


def test_legacy_hook_does_not_touch_strategy():
    s = SimpleNamespace(_close_panel=object())
    before = dict(vars(s))
    install_covariance_basis(s, object(), "legacy")
    assert vars(s) == before


def test_single_alpha_label_perturbation_cannot_change_normalized_weight():
    # AlphaMax has one directional factor: normalization produces exactly1
    # for positive, negative, missing and arbitrary IC histories.
    grid = pd.Index(np.arange(40, dtype=np.int64) * 21 * Timeframe.D1.ms, name="ts_open")
    histories = [np.ones(40), -np.ones(40), np.full(40, np.nan), np.sin(np.arange(40))]
    for history in histories:
        weights = estimate_blend_weights(
            {"eq_mom_252_21": pd.Series(history, index=grid)},
            horizon_bars=21,
            timeframe=Timeframe.D1,
            contiguous=False,
        )
        np.testing.assert_array_equal(weights.weights.to_numpy(), np.ones((40, 1)))
        assert weights.asof(-1).iloc[0] == 1
