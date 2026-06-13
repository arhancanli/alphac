"""Unit tests for alphaforge.portfolio.covariance.

The Ledoit-Wolf and EWMA estimators are checked against independent
brute-force implementations written directly from the design formulas
(execDesign §6.1): triple loops, no vectorization tricks shared with
production. Agreement to 1e-10 absolute.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alphaforge.portfolio import annualize_cov, ewma_cov, ledoit_wolf_cc, nearest_psd

# ---------------------------------------------------------------- brute force


def ewma_cov_brute(x: np.ndarray, halflife: int, min_periods: int) -> np.ndarray:
    """Literal recursion from the design: S_0 = seed sample cov, then
    S_t = (1-lam) r r^T + lam S."""
    lam = 0.5 ** (1.0 / halflife)
    seed = x[:min_periods]
    s = (seed.T @ seed) / min_periods
    for t in range(min_periods, x.shape[0]):
        r = x[t]
        s = (1.0 - lam) * np.outer(r, r) + lam * s
    return s


def lw_cc_brute(x: np.ndarray, s: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Triple-loop transcription of the §6.1 estimator. Returns
    (sigma_shrunk, delta_star, raw_unclipped)."""
    t, n = x.shape
    d = np.sqrt(np.diag(s))
    r_bar = (2.0 / (n * (n - 1))) * sum(
        s[i, j] / (d[i] * d[j]) for i in range(n) for j in range(i + 1, n)
    )
    f = np.empty((n, n))
    for i in range(n):
        for j in range(n):
            f[i, j] = s[i, i] if i == j else r_bar * d[i] * d[j]

    def theta(k: int, i: int, j: int) -> float:
        return float(np.mean((x[:, k] ** 2 - s[k, k]) * (x[:, i] * x[:, j] - s[i, j])))

    pi_hat = sum(
        float(np.mean((x[:, i] * x[:, j] - s[i, j]) ** 2)) for i in range(n) for j in range(n)
    )
    rho_hat = sum(float(np.mean((x[:, i] * x[:, i] - s[i, i]) ** 2)) for i in range(n))
    for i in range(n):
        for j in range(n):
            if i != j:
                rho_hat += (r_bar / 2.0) * (
                    np.sqrt(s[j, j] / s[i, i]) * theta(i, i, j)
                    + np.sqrt(s[i, i] / s[j, j]) * theta(j, i, j)
                )
    gamma_hat = float(((f - s) ** 2).sum())
    raw = (pi_hat - rho_hat) / (gamma_hat * t)
    delta = float(np.clip(raw, 0.0, 1.0))
    return delta * f + (1.0 - delta) * s, delta, raw


# ------------------------------------------------------------------ ewma_cov


class TestEwmaCov:
    def test_matches_brute_force_recursion(self) -> None:
        rng = np.random.default_rng(7)
        x = rng.normal(0.0, 0.01, size=(400, 4))
        got = ewma_cov(pd.DataFrame(x), halflife_bars=50, min_periods=60)
        want = ewma_cov_brute(x, 50, 60)
        np.testing.assert_allclose(got, want, atol=1e-10)
        np.testing.assert_allclose(got, got.T, atol=0.0)  # exactly symmetric

    def test_constant_return_is_fixed_point(self) -> None:
        # All returns equal c: seed = c^2 and (1-lam) c^2 + lam c^2 = c^2 forever.
        c = 0.003
        frame = pd.DataFrame({"A": np.full(500, c)})
        got = ewma_cov(frame, halflife_bars=100, min_periods=50)
        assert got.shape == (1, 1)
        assert got[0, 0] == pytest.approx(c * c, abs=1e-15)

    def test_seed_only_is_sample_cov(self) -> None:
        rng = np.random.default_rng(8)
        x = rng.normal(0.0, 0.02, size=(60, 3))
        got = ewma_cov(pd.DataFrame(x), halflife_bars=720, min_periods=60)
        want = (x.T @ x) / 60.0  # zero-mean sample cov, no recursion steps
        np.testing.assert_allclose(got, want, atol=1e-12)

    def test_nan_column_variance_only_fallback(self) -> None:
        rng = np.random.default_rng(9)
        full = rng.normal(0.0, 0.01, size=(300, 2))
        young = rng.normal(0.0, 0.05, size=300)
        young[:100] = np.nan
        frame = pd.DataFrame({"A": full[:, 0], "B": full[:, 1], "C": young})
        got = ewma_cov(frame, halflife_bars=50, min_periods=60)
        # Young column: zero covariances, mean-of-squares variance.
        assert got[2, 0] == 0.0 and got[2, 1] == 0.0 and got[0, 2] == 0.0 and got[1, 2] == 0.0
        assert got[2, 2] == pytest.approx(float(np.mean(young[100:] ** 2)), abs=1e-15)
        # Full block identical to estimating the two full columns alone.
        sub = ewma_cov(frame[["A", "B"]], halflife_bars=50, min_periods=60)
        np.testing.assert_allclose(got[:2, :2], sub, atol=0.0)

    def test_nan_column_too_short_raises(self) -> None:
        frame = pd.DataFrame({"A": np.full(100, 0.01), "B": [np.nan] * 99 + [0.01]})
        with pytest.raises(ValueError, match="finite observations"):
            ewma_cov(frame, halflife_bars=50, min_periods=50)

    def test_too_few_rows_raises(self) -> None:
        frame = pd.DataFrame({"A": np.full(10, 0.01)})
        with pytest.raises(ValueError, match="min_periods"):
            ewma_cov(frame, halflife_bars=50, min_periods=60)

    @pytest.mark.parametrize(("halflife", "min_periods"), [(0, 240), (720, 1)])
    def test_bad_params_raise(self, halflife: int, min_periods: int) -> None:
        frame = pd.DataFrame({"A": np.full(300, 0.01)})
        with pytest.raises(ValueError):
            ewma_cov(frame, halflife_bars=halflife, min_periods=min_periods)


# -------------------------------------------------------------- ledoit_wolf


class TestLedoitWolfCC:
    def test_matches_brute_force_direct_formula(self) -> None:
        rng = np.random.default_rng(11)
        x = rng.normal(0.0, 0.01, size=(50, 5))
        s = (x.T @ x) / 50.0  # zero-mean sample cov (the canonical LW input)
        got_sigma, got_delta = ledoit_wolf_cc(x, s)
        want_sigma, want_delta, raw = lw_cc_brute(x, s)
        assert got_delta == pytest.approx(want_delta, abs=1e-12)
        assert got_delta == pytest.approx(float(np.clip(raw, 0.0, 1.0)), abs=1e-12)
        np.testing.assert_allclose(got_sigma, want_sigma, atol=1e-10)

    def test_matches_brute_force_with_ewma_s(self) -> None:
        # Production passes the EWMA matrix as S; the estimator must agree
        # with the brute force evaluated at that same S.
        rng = np.random.default_rng(12)
        x = rng.normal(0.0, 0.02, size=(80, 4))
        s_ewma = ewma_cov_brute(x, 30, 20)
        got_sigma, got_delta = ledoit_wolf_cc(x, s_ewma)
        want_sigma, want_delta, _ = lw_cc_brute(x, 0.5 * (s_ewma + s_ewma.T))
        assert got_delta == pytest.approx(want_delta, abs=1e-12)
        np.testing.assert_allclose(got_sigma, want_sigma, atol=1e-10)

    def test_delta_clipped_to_one(self) -> None:
        # Near-perfectly correlated columns: gamma_hat is tiny while pi - rho
        # stays positive, so the raw ratio explodes above 1 and must clip.
        rng = np.random.default_rng(13)
        base = rng.normal(0.0, 0.01, size=200)
        x = np.column_stack([base, base + 1e-9 * rng.normal(size=200), base * (1 + 1e-9)])
        s = (x.T @ x) / 200.0
        _, _, raw = lw_cc_brute(x, s)
        assert raw > 1.0  # the engineered case really exceeds the cap
        sigma, delta = ledoit_wolf_cc(x, s)
        assert delta == 1.0
        assert sigma[0, 0] == pytest.approx(s[0, 0], abs=1e-18)  # f_ii = s_ii

    def test_delta_always_in_unit_interval(self) -> None:
        rng = np.random.default_rng(14)
        for _ in range(10):
            n = int(rng.integers(2, 7))
            x = rng.standard_t(df=3, size=(40, n)) * 0.01
            s = (x.T @ x) / 40.0
            _, delta = ledoit_wolf_cc(x, s)
            assert 0.0 <= delta <= 1.0

    def test_single_asset_is_identity(self) -> None:
        x = np.full((50, 1), 0.01)
        sigma, delta = ledoit_wolf_cc(x, np.array([[4.0]]))
        assert delta == 0.0
        assert sigma[0, 0] == 4.0

    def test_shape_mismatch_and_nan_raise(self) -> None:
        x = np.zeros((50, 3)) + 0.01
        with pytest.raises(ValueError, match="columns"):
            ledoit_wolf_cc(x, np.eye(4))
        bad = x.copy()
        bad[0, 0] = np.nan
        with pytest.raises(ValueError, match="finite"):
            ledoit_wolf_cc(bad, np.eye(3))


# -------------------------------------------------------------- nearest_psd


class TestNearestPsd:
    def test_repairs_planted_negative_eigenvalue(self) -> None:
        rng = np.random.default_rng(15)
        q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
        planted = np.array([1.0, 0.5, -0.1])
        a = (q * planted[None, :]) @ q.T
        out = nearest_psd(a)
        np.testing.assert_allclose(out, out.T, atol=0.0)
        eps = 1e-10 * np.trace(0.5 * (a + a.T)) / 3.0
        assert np.linalg.eigvalsh(out).min() >= eps - 1e-15
        # Positive eigen-directions are preserved.
        np.testing.assert_allclose(sorted(np.linalg.eigvalsh(out))[1:], [0.5, 1.0], atol=1e-10)

    def test_psd_input_passes_through(self) -> None:
        rng = np.random.default_rng(16)
        b = rng.normal(size=(4, 4))
        a = b @ b.T + 0.5 * np.eye(4)
        np.testing.assert_allclose(nearest_psd(a), a, atol=1e-12)

    def test_negative_trace_raises_not_silently_singular(self) -> None:
        # tr(Sigma) <= 0 cannot occur for a real covariance; the scale-aware
        # floor would otherwise be exactly 0 and the matrix would be laundered
        # into a PSD-singular result. nearest_psd must loudly refuse instead.
        bad = np.diag([-1.0, -2.0, -0.5])
        with pytest.raises(ValueError, match=r"tr.*<= 0|corrupt"):
            nearest_psd(bad)

    def test_zero_trace_raises(self) -> None:
        # A symmetric matrix with exactly zero trace (off-diagonal energy only)
        # also trips the guard: tr(Sigma) == 0 is non-positive.
        bad = np.array([[0.0, 1.0], [1.0, 0.0]])
        with pytest.raises(ValueError, match=r"tr.*<= 0|corrupt"):
            nearest_psd(bad)


# ------------------------------------------------------------ annualize_cov


class TestAnnualizeCov:
    def test_scales_by_periods_per_year(self) -> None:
        cov = np.array([[4.0, 1.0], [1.0, 9.0]])
        np.testing.assert_allclose(annualize_cov(cov, 8760.0), cov * 8760.0, atol=0.0)

    @pytest.mark.parametrize("ppy", [0.0, -1.0, np.nan])
    def test_bad_periods_per_year_raises(self, ppy: float) -> None:
        with pytest.raises(ValueError, match="periods_per_year"):
            annualize_cov(np.eye(2), ppy)
