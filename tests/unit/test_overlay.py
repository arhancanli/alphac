"""Unit tests for alphaforge.portfolio.overlay (vol targeting, execDesign §6.3)."""

from __future__ import annotations

import numpy as np
import pytest

from alphaforge.portfolio import vol_target


class TestVolTarget:
    def test_s_max_binds_in_quiet_regime(self) -> None:
        # Ex-ante vol 1% and realized 2%: target/sigma_hat = 7.5 but the
        # scale must cap at s_max = 1.5 — never lever up into a quiet regime.
        w = np.array([0.10, -0.10])
        cov = (0.01**2 / 0.02) * np.eye(2)  # w' cov w = 1e-4 -> ex-ante 1%
        w_final, s = vol_target(w, cov, realized_vol_ann=0.02)
        assert s == 1.5
        np.testing.assert_allclose(w_final, 1.5 * w, atol=0.0)

    def test_realized_vol_dominates_when_larger(self) -> None:
        # Conservatism: sigma_hat = max(ex-ante, realized). Ex-ante 30%,
        # realized 60% -> s = 0.15/0.60 = 0.25.
        w = np.array([1.0])
        cov = np.array([[0.09]])  # ex-ante 30%
        w_final, s = vol_target(w, cov, realized_vol_ann=0.60)
        assert s == pytest.approx(0.25, abs=1e-15)
        assert w_final[0] == pytest.approx(0.25, abs=1e-15)

    def test_ex_ante_dominates_when_larger(self) -> None:
        w = np.array([1.0])
        cov = np.array([[0.09]])  # ex-ante 30% > realized 5%
        w_final, s = vol_target(w, cov, realized_vol_ann=0.05)
        assert s == pytest.approx(0.15 / 0.30, abs=1e-12)
        assert w_final[0] == pytest.approx(0.5, abs=1e-12)

    def test_gross_reclip_after_scaling(self) -> None:
        # Gross 0.8 scaled by 1.5 -> 1.2 > gross_max=1.0: re-clip to exactly 1.0.
        w = np.array([0.4, -0.4])
        cov = 1e-6 * np.eye(2)  # tiny vol so s = s_max
        w_final, s = vol_target(w, cov, realized_vol_ann=0.0)
        assert s == 1.5
        assert float(np.abs(w_final).sum()) == pytest.approx(1.0, abs=1e-12)
        # Direction preserved.
        assert w_final[0] > 0.0 and w_final[1] < 0.0
        assert w_final[0] == pytest.approx(-w_final[1], abs=1e-15)

    def test_zero_book_stays_zero(self) -> None:
        w = np.zeros(3)
        w_final, s = vol_target(w, np.eye(3) * 0.04, realized_vol_ann=0.0)
        assert s == 1.5  # sigma_hat = 0 -> capped at s_max
        assert np.all(w_final == 0.0)

    def test_exact_target_needs_no_scaling(self) -> None:
        w = np.array([1.0])
        cov = np.array([[0.15**2]])
        w_final, s = vol_target(w, cov, realized_vol_ann=0.0)
        assert s == pytest.approx(1.0, abs=1e-12)
        assert w_final[0] == pytest.approx(1.0, abs=1e-12)

    def test_validation_errors(self) -> None:
        w = np.array([0.1])
        cov = np.array([[0.04]])
        with pytest.raises(ValueError, match="realized_vol_ann"):
            vol_target(w, cov, realized_vol_ann=-0.1)
        with pytest.raises(ValueError, match="finite"):
            vol_target(np.array([np.nan]), cov, realized_vol_ann=0.1)
        with pytest.raises(ValueError, match="cov_ann must be"):
            vol_target(w, np.eye(2), realized_vol_ann=0.1)
        with pytest.raises(ValueError, match="target"):
            vol_target(w, cov, realized_vol_ann=0.1, target=0.0)
        with pytest.raises(ValueError, match="s_max"):
            vol_target(w, cov, realized_vol_ann=0.1, s_max=0.0)
