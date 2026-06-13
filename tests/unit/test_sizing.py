"""Unit tests for alphaforge.signals.sizing — THE mu_ann contract (finding 2).

The boundary the leakage critique called out as a silent 72x position-scaling
error: signals emit ``mu_ann = mu_h · (8760/h)`` in a column literally named
``mu_ann``; the horizon ``h`` comes from the ONE shared settings field
``SignalsCfg.horizon_bars``. These tests pin the units, the name, and the
single-constant plumbing exactly.

Offline, pure pandas/numpy; no lake, no I/O.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alphaforge.config.settings import SignalsCfg
from alphaforge.core.time import Timeframe
from alphaforge.signals.sizing import MU_ANN_COLUMN, GrinoldSizer

T0 = 1_672_531_200_000
HOUR = 3_600_000


def _panel(values: list[float]) -> pd.Series:
    iids = [f"I{k}" for k in range(len(values))]
    index = pd.MultiIndex.from_product([[T0], iids], names=("ts_open", "instrument_id"))
    return pd.Series(np.asarray(values, dtype=float), index=index)


class TestMuAnnUnits:
    def test_exact_units_sigma_001_h72(self) -> None:
        """THE finding-2 fixture: sigma_hat = 0.01/bar, h = 72, F~ = 1 =>
        mu_h = 0.02·0.01·sqrt(72) and mu_ann = mu_h·8760/72 EXACTLY."""
        cfg = SignalsCfg()
        assert cfg.horizon_bars == 72  # the ONE holding-period constant
        sizer = GrinoldSizer.from_cfg(cfg)
        alpha = _panel([1.0])
        sigma = _panel([0.01])
        out = sizer.mu_ann(alpha, sigma)
        mu_h = 0.02 * 0.01 * np.sqrt(72.0)
        expected = mu_h * (8760.0 / 72.0)
        np.testing.assert_allclose(out.to_numpy(), expected, rtol=1e-15)
        # and the magnitude band the optimizer enforces (finding 2)
        assert np.abs(out.to_numpy()).max() < 3.0

    def test_output_is_named_mu_ann(self) -> None:
        """The column name IS the contract — the optimizer keys on it."""
        assert MU_ANN_COLUMN == "mu_ann"
        out = GrinoldSizer.from_cfg(SignalsCfg()).mu_ann(_panel([1.0]), _panel([0.01]))
        assert out.name == "mu_ann"

    def test_linear_in_alpha_and_sign_preserving(self) -> None:
        sizer = GrinoldSizer.from_cfg(SignalsCfg())
        alpha = _panel([-2.0, -1.0, 0.0, 1.0, 2.0])
        sigma = _panel([0.01] * 5)
        out = sizer.mu_ann(alpha, sigma).to_numpy()
        unit = sizer.mu_ann(_panel([1.0] * 5), sigma).to_numpy()
        np.testing.assert_allclose(out, alpha.to_numpy() * unit, rtol=1e-15)
        assert out[0] < 0 < out[4]  # sizing scales, never flips

    def test_annualization_factor(self) -> None:
        sizer = GrinoldSizer(ic_target=0.02, horizon_bars=72, timeframe=Timeframe.H1)
        assert sizer.annualization == 8760.0 / 72.0

    def test_typical_magnitudes_stay_inside_the_optimizer_band(self) -> None:
        """Realistic crypto inputs (sigma_hat up to 3%/bar, |F~| <= 3) must land
        well inside |mu_ann| < 3.0 — if this fails, units drifted (finding 2)."""
        rng = np.random.default_rng(11)
        alpha = _panel(list(np.clip(rng.standard_normal(50) * 1.2, -3, 3)))
        sigma = _panel(list(rng.uniform(0.002, 0.03, 50)))
        out = GrinoldSizer.from_cfg(SignalsCfg()).mu_ann(alpha, sigma)
        assert np.abs(out.to_numpy()).max() < 3.0


class TestNaNDiscipline:
    def test_non_positive_or_missing_sigma_is_nan(self) -> None:
        sizer = GrinoldSizer.from_cfg(SignalsCfg())
        out = sizer.mu_ann(_panel([1.0, 1.0, 1.0]), _panel([0.0, -0.01, float("nan")]))
        assert np.isnan(out.to_numpy()).all()  # no vol estimate => no mu, never zero

    def test_nan_alpha_is_nan(self) -> None:
        sizer = GrinoldSizer.from_cfg(SignalsCfg())
        out = sizer.mu_ann(_panel([float("nan"), 1.0]), _panel([0.01, 0.01]))
        assert np.isnan(out.iloc[0]) and np.isfinite(out.iloc[1])

    def test_sigma_aligned_by_index_not_position(self) -> None:
        alpha = _panel([1.0, 1.0])
        sigma = _panel([0.01, 0.02]).iloc[::-1]  # reversed order, same index labels
        out = GrinoldSizer.from_cfg(SignalsCfg()).mu_ann(alpha, sigma)
        ratio = float(out.iloc[1] / out.iloc[0])
        np.testing.assert_allclose(ratio, 2.0, rtol=1e-12)


class TestConstruction:
    def test_horizon_comes_from_the_one_settings_field(self) -> None:
        """buildability §3.10: h lives in exactly one settings field; from_cfg
        consumes it — never a retyped literal."""
        cfg = SignalsCfg(horizon_bars=48, ic_target=0.03)
        sizer = GrinoldSizer.from_cfg(cfg)
        assert sizer.horizon_bars == 48
        assert sizer.ic_target == 0.03

    def test_validation(self) -> None:
        with pytest.raises(ValueError, match="ic_target"):
            GrinoldSizer(ic_target=0.0, horizon_bars=72)
        with pytest.raises(ValueError, match="ic_target"):
            GrinoldSizer(ic_target=1.0, horizon_bars=72)
        with pytest.raises(ValueError, match="horizon_bars"):
            GrinoldSizer(ic_target=0.02, horizon_bars=0)
