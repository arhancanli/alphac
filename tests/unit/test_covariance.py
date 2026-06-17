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
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

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


# ======================================================================= property
#
# Hypothesis @given property tests for the estimator INVARIANTS (idiom mirrors
# tests/property/test_hmm_props.py: small synthetic panels, capped examples,
# deadline disabled because the eigendecompositions are cheap but variable).
#
# The example-based tests above pin the exact numerics against a brute-force
# transcription; these assert the structural guarantees that must hold for
# EVERY admissible input, not just the seeded fixtures:
#
#   * ewma_cov / ledoit_wolf_cc / nearest_psd outputs are exactly symmetric;
#   * the annualize→nearest_psd pipeline is PSD (min eigenvalue >= -tiny tol);
#   * the Ledoit-Wolf intensity delta* always lands in [0, 1] and rises as the
#     sampling noise grows (shorter windows shrink harder toward the target);
#   * annualize_cov scales every entry by exactly periods_per_year (sign +
#     magnitude), preserving symmetry.
#
# Panel strategy: a TxN matrix of small zero-mean returns with a planted
# correlation structure (a random loading on a common factor plus idiosyncratic
# noise) so the panels resemble real return cross-sections rather than pure
# white noise.


def _returns_panel(t_obs: int, n: int, seed: int, noise: float = 1.0) -> np.ndarray:
    """A TxN zero-mean return panel: one common factor + idiosyncratic noise.

    ``noise`` scales the idiosyncratic part only; it leaves the population
    second moments finite and the columns genuinely correlated (so the
    constant-correlation target is non-trivial).
    """
    rng = np.random.default_rng(seed)
    factor = rng.normal(0.0, 0.01, size=(t_obs, 1))
    loadings = rng.uniform(0.3, 1.0, size=(1, n))
    idio = rng.normal(0.0, 0.01 * noise, size=(t_obs, n))
    return factor @ loadings + idio


@st.composite
def _panels(
    draw: st.DrawFn,
    *,
    min_t: int = 12,
    max_t: int = 60,
    min_n: int = 2,
    max_n: int = 6,
) -> tuple[np.ndarray, np.ndarray]:
    """Draw a (window, sample-cov) pair: a TxN panel and its zero-mean cov S."""
    t_obs = draw(st.integers(min_value=min_t, max_value=max_t))
    n = draw(st.integers(min_value=min_n, max_value=max_n))
    seed = draw(st.integers(min_value=0, max_value=2**31 - 1))
    x = _returns_panel(t_obs, n, seed)
    s = (x.T @ x) / float(t_obs)  # zero-mean sample cov (the canonical LW input)
    return x, s


_SLOW = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


class TestCovarianceProperties:
    # ----------------------------------------------------------------- symmetry
    @given(panel=_panels())
    @_SLOW
    def test_ewma_cov_is_exactly_symmetric(self, panel: tuple[np.ndarray, np.ndarray]) -> None:
        x, _ = panel
        t_obs, _ = x.shape
        min_periods = max(2, t_obs // 2)
        out = ewma_cov(pd.DataFrame(x), halflife_bars=20, min_periods=min_periods)
        np.testing.assert_array_equal(out, out.T)  # bit-identical, not just close

    @given(panel=_panels())
    @_SLOW
    def test_ledoit_wolf_output_is_exactly_symmetric(
        self, panel: tuple[np.ndarray, np.ndarray]
    ) -> None:
        x, s = panel
        sigma, _ = ledoit_wolf_cc(x, s)
        np.testing.assert_array_equal(sigma, sigma.T)

    @given(panel=_panels())
    @_SLOW
    def test_nearest_psd_output_is_exactly_symmetric(
        self, panel: tuple[np.ndarray, np.ndarray]
    ) -> None:
        _, s = panel
        out = nearest_psd(s)
        np.testing.assert_array_equal(out, out.T)

    # ---------------------------------------------------------------------- PSD
    @given(panel=_panels())
    @_SLOW
    def test_full_pipeline_is_psd(self, panel: tuple[np.ndarray, np.ndarray]) -> None:
        # The production pipeline: shrink -> nearest_psd -> annualize. The PSD
        # repair guarantees min eigenvalue >= eps = eps_rel * tr/N > 0, so the
        # annualized matrix (a positive scalar multiple) stays PSD.
        x, s = panel
        n = s.shape[0]
        sigma, _ = ledoit_wolf_cc(x, s)
        psd = nearest_psd(sigma)
        ann = annualize_cov(psd, 8760.0)
        eps = 1e-10 * float(np.trace(psd)) / n
        min_eig = float(np.linalg.eigvalsh(psd).min())
        assert min_eig >= eps - 1e-12  # repaired floor honoured
        assert float(np.linalg.eigvalsh(ann).min()) >= -1e-8  # scaled, still PSD

    @given(panel=_panels())
    @_SLOW
    def test_nearest_psd_repairs_planted_negative_eigenvalue(
        self, panel: tuple[np.ndarray, np.ndarray]
    ) -> None:
        # Perturb the sample cov with a symmetric negative-definite kick so a
        # genuinely indefinite matrix is fed in; nearest_psd must lift every
        # eigenvalue to the scale-aware floor.
        _, s = panel
        n = s.shape[0]
        # Subtract a multiple of the identity large enough to drive eigenvalues
        # negative while keeping the trace strictly positive (the loud-failure
        # guard requires tr > 0).
        lam_min = float(np.linalg.eigvalsh(s).min())
        kick = (lam_min + 0.5 * float(np.trace(s)) / n) * np.eye(n)
        indefinite = s - kick
        if float(np.trace(indefinite)) <= 0.0:
            return  # guard domain; covered by the example-based negative-trace test
        out = nearest_psd(indefinite)
        eps = 1e-10 * float(np.trace(indefinite)) / n
        assert float(np.linalg.eigvalsh(out).min()) >= eps - 1e-12

    # ------------------------------------------------- shrinkage intensity bounds
    @given(panel=_panels())
    @_SLOW
    def test_delta_star_always_in_unit_interval(self, panel: tuple[np.ndarray, np.ndarray]) -> None:
        x, s = panel
        _, delta = ledoit_wolf_cc(x, s)
        assert 0.0 <= delta <= 1.0

    @given(
        n=st.sampled_from([5, 6]),
        pop_seed=st.integers(min_value=0, max_value=2**31 - 1),
    )
    @settings(
        max_examples=25,  # ~30 ms/example (two reps-loops); keep runtime modest
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_delta_star_rises_as_sampling_noise_grows(self, n: int, pop_seed: int) -> None:
        # Ledoit-Wolf optimal intensity delta* = (pi_hat - rho_hat)/(gamma_hat T).
        # Holding the POPULATION fixed, a shorter estimation window carries more
        # sampling error, so the optimal intensity shrinks harder toward the
        # structured constant-correlation target (delta* is monotone-decreasing
        # in T in expectation). A single draw is far too noisy to see this, so we
        # average delta* over many independent samples from one fixed factor
        # population at a short vs a long window. (The relationship is genuinely
        # NON-monotone per single draw and per other "noise" knobs such as the
        # idiosyncratic-to-factor ratio, which change the population correlation
        # and hence the target fit -- window length is the clean knob here.)
        short_t, long_t, reps = 12, 600, 160

        def fixed_pop_panel(t_obs: int, samp_seed: int) -> np.ndarray:
            # Loadings depend ONLY on pop_seed (population is fixed); the factor
            # and idiosyncratic draws vary with samp_seed (independent samples).
            pop_rng = np.random.default_rng(pop_seed)
            loadings = pop_rng.uniform(0.3, 1.0, size=(1, n))
            samp_rng = np.random.default_rng(samp_seed)
            factor = samp_rng.normal(0.0, 0.01, size=(t_obs, 1))
            idio = samp_rng.normal(0.0, 0.01, size=(t_obs, n))
            return factor @ loadings + idio

        def mean_delta(t_obs: int) -> float:
            deltas = []
            for k in range(reps):
                x = fixed_pop_panel(t_obs, samp_seed=pop_seed * 7919 + k)
                s = (x.T @ x) / float(t_obs)
                _, d = ledoit_wolf_cc(x, s)
                deltas.append(d)
            return float(np.mean(deltas))

        short_delta = mean_delta(short_t)
        long_delta = mean_delta(long_t)
        assert 0.0 <= short_delta <= 1.0
        assert 0.0 <= long_delta <= 1.0
        # More sampling noise (short window) => at least as much shrinkage as the
        # long window. Tiny tolerance guards the already-saturated (both ~1.0)
        # corner so a clipped delta* never makes the property spuriously flaky.
        assert short_delta >= long_delta - 1e-9

    # --------------------------------------------------------------- annualization
    @given(
        panel=_panels(),
        ppy=st.floats(min_value=1.0, max_value=1e5, allow_nan=False, allow_infinity=False),
    )
    @_SLOW
    def test_annualize_scales_every_entry(
        self, panel: tuple[np.ndarray, np.ndarray], ppy: float
    ) -> None:
        # Run on a genuine PSD covariance so the scaling acts on a realistic
        # matrix. Σ_ann = Σ_bar * ppy entrywise: sign preserved (ppy > 0),
        # magnitude scaled exactly, symmetry preserved.
        _, s = panel
        psd = nearest_psd(s)
        ann = annualize_cov(psd, ppy)
        np.testing.assert_allclose(ann, psd * ppy, rtol=0.0, atol=0.0)
        np.testing.assert_array_equal(ann, ann.T)  # symmetry preserved
        # Sign: a positive scale never flips any entry's sign.
        assert np.all(np.sign(ann) == np.sign(psd))
        # Diagonal (variances) scale up for ppy > 1 and stay non-negative.
        if ppy >= 1.0:
            assert np.all(np.diag(ann) >= np.diag(psd) - 1e-18)
