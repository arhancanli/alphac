"""Unit tests for alphaforge.portfolio.optimizer.

Covers: the unconstrained-limit sanity check (lambda-only problem recovers
(1/lambda) Sigma^-1 mu), constraint binding, the turnover cap, the cost
penalty's trade-shrinking effect, the mu_ann contract tripwire (leakageCritique
finding 2), the rank/inverse-vol fallback (determinism, half-gross, shortable
mask, w_max clip), solver-failure delegation, and the from_settings wiring of
the single shared horizon constant h = 72.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp

from alphaforge.config.settings import Settings
from alphaforge.portfolio import (
    MU_ANN_ABS_MAX,
    MeanVarianceOptimizer,
    OptResult,
    PortfolioConstraints,
    RankEqualVolFallback,
    check_mu_ann_contract,
)
from alphaforge.portfolio.optimizer import (
    MU_ANN_SYSTEMATIC_MEDIAN_MAX,
    winsorize_mu_ann,
)

H = 72  # mirrors settings.signals.horizon_bars; from_settings test asserts the link

LOOSE = PortfolioConstraints(gross_max=100.0, net_max=100.0, w_max=100.0, turnover_max=100.0)


def make_mvo(
    constraints: PortfolioConstraints, risk_aversion: float = 7.0
) -> MeanVarianceOptimizer:
    return MeanVarianceOptimizer(
        risk_aversion=risk_aversion, holding_bars=H, constraints=constraints
    )


def rand_cov(n: int, seed: int, base_var: float = 0.04) -> np.ndarray:
    """Well-conditioned annualized covariance (vols around 20%)."""
    rng = np.random.default_rng(seed)
    b = rng.normal(0.0, 0.05, size=(n, n))
    return base_var * np.eye(n) + b @ b.T


def legit_tail_mu(n: int, tail_value: float, seed: int = 33) -> np.ndarray:
    """A realistic mu_ann vector: median ~0.2, all-but-one in a sane band, ONE
    extreme single-name tail. Models the linear-in-sigma Grinold overshoot on a
    high-vol coin (verified on real history: rare single-name |mu_ann| beyond 3).
    """
    rng = np.random.default_rng(seed)
    mu = rng.normal(0.0, 0.2, size=n)
    mu[0] = tail_value
    return mu


def crash_tail_mu(n: int, *, tail_frac: float, tail_value: float, seed: int = 7) -> np.ndarray:
    """A market-wide-crash mu_ann vector: sane median, a FAT tail. ``tail_frac``
    of names sit at +/-``tail_value`` (extreme but honest -- many alts at 650%+
    vol at once), the rest at ~0.15 median. Models the LUNA/FTX regime that
    killed the first 6y run (4.8% of names beyond 3.0, median 0.148)."""
    rng = np.random.default_rng(seed)
    mu = rng.normal(0.0, 0.18, size=n)
    k = round(tail_frac * n)
    signs = rng.choice([-1.0, 1.0], size=k)
    mu[:k] = signs * tail_value
    return mu


class TestMuAnnTripwire:
    """The finding-2 contract is detected on the MEDIAN |mu_ann|: a systematic
    ~72x units bug inflates every name (median explodes), so it raises; a
    market-wide crash inflates only the tail (median stays sane), so it is
    winsorized, never refused. This is the discriminator the fraction-based
    check got wrong -- it killed the first 6y run at 4.8% tail / median 0.148."""

    def test_all_names_inflated_is_systematic_error(self) -> None:
        # A double annualization / raw-per-h bug inflates the WHOLE vector:
        # median == 5.0 >> the bound -> the unambiguous systematic signature.
        with pytest.raises(ValueError, match="systematic"):
            check_mu_ann_contract(np.full(50, 5.0))

    def test_realistic_72x_unit_bug_raises(self) -> None:
        # The exact finding-2 slip: a sane per-h distribution annualized by 8760
        # instead of 8760/h (~72x). The median (~0.15 -> ~11) trips the bound.
        rng = np.random.default_rng(1)
        sane = np.abs(rng.normal(0.0, 0.18, size=300))
        assert float(np.median(sane * 72.0)) > MU_ANN_SYSTEMATIC_MEDIAN_MAX
        with pytest.raises(ValueError, match="mu_ann contract"):
            check_mu_ann_contract(sane * 72.0)

    def test_crash_tail_does_not_raise(self) -> None:
        # THE regression: the 6y-killing regime. ~5% of names beyond 3.0 but a
        # sane median -> an honest crash tail, winsorized downstream, NOT refused.
        mu = crash_tail_mu(300, tail_frac=0.05, tail_value=4.2)
        assert (np.abs(mu) >= MU_ANN_ABS_MAX).mean() >= 0.04  # the tail is real
        assert float(np.median(np.abs(mu))) < MU_ANN_SYSTEMATIC_MEDIAN_MAX  # median sane
        check_mu_ann_contract(mu)  # must NOT raise

    def test_single_tail_small_vector_sane_median_does_not_raise(self) -> None:
        # One name at -3.01 among sane names: median ~0.2 -> winsorized, not a bug.
        check_mu_ann_contract(np.array([0.1, -3.01, 0.2, 0.15]))

    def test_accepts_near_ceiling_values_with_sane_median(self) -> None:
        # Two names near the ceiling among sane names: median ~0.1, no raise
        # (and they are under 3.0, so not even winsorized).
        check_mu_ann_contract(np.array([2.99, -2.99, 0.1, 0.1, 0.1, 0.1]))

    def test_legit_single_tail_in_large_vector_does_not_raise(self) -> None:
        # 200 names, median ~0.2, ONE name at 4.3 -> the honest extreme-vol tail
        # must NOT kill a multi-year run (median is what matters, not the tail).
        mu = legit_tail_mu(200, tail_value=4.3)
        assert float(np.median(np.abs(mu))) < MU_ANN_SYSTEMATIC_MEDIAN_MAX
        check_mu_ann_contract(mu)  # no raise

    def test_solve_refuses_systematic_violation(self) -> None:
        n = 4
        mvo = make_mvo(PortfolioConstraints())
        with pytest.raises(ValueError, match="mu_ann contract"):
            mvo.solve(
                np.full(n, 5.0),  # whole vector inflated -> systematic
                0.04 * np.eye(n),
                np.zeros(n),
                np.zeros(n),
                np.ones(n),
            )

    def test_fallback_also_refuses_systematic_violation(self) -> None:
        n = 4
        fb = RankEqualVolFallback()
        with pytest.raises(ValueError, match="mu_ann contract"):
            fb.solve(
                np.full(n, -5.0),  # whole vector inflated -> systematic
                0.04 * np.eye(n),
                np.zeros(n),
                np.zeros(n),
                np.ones(n),
            )

    def test_solve_winsorizes_crash_tail(self) -> None:
        # A 300-name book in a crash (5% tail beyond 3.0, sane median) solves
        # WITHOUT raising; the tail entries are winsorized to the ceiling.
        n = 300
        mu = crash_tail_mu(n, tail_frac=0.05, tail_value=4.2)
        cov = 0.04 * np.eye(n)
        res = make_mvo(PortfolioConstraints()).solve(mu, cov, np.zeros(n), np.zeros(n), np.ones(n))
        assert res.status in ("optimal", "fallback_used")
        assert np.all(np.abs(res.weights) <= PortfolioConstraints().w_max + 1e-9)


class TestWinsorizeMuAnn:
    def test_clips_single_tail_to_ceiling_and_counts(self) -> None:
        mu = legit_tail_mu(200, tail_value=4.3)
        clipped, n_clipped = winsorize_mu_ann(mu)
        assert n_clipped == 1
        assert float(np.abs(clipped).max()) <= MU_ANN_ABS_MAX
        assert clipped[0] == pytest.approx(MU_ANN_ABS_MAX)
        # Every non-tail entry is untouched.
        np.testing.assert_array_equal(clipped[1:], mu[1:])

    def test_no_clip_leaves_array_unchanged(self) -> None:
        mu = np.array([0.2, -0.5, 1.9, -2.9])
        clipped, n_clipped = winsorize_mu_ann(mu)
        assert n_clipped == 0
        np.testing.assert_array_equal(clipped, mu)

    def test_negative_tail_clipped_to_negative_ceiling(self) -> None:
        clipped, n_clipped = winsorize_mu_ann(np.array([0.1, -4.3, 0.2]))
        assert n_clipped == 1
        assert clipped[1] == pytest.approx(-MU_ANN_ABS_MAX)

    def test_nan_passes_through_unchanged(self) -> None:
        clipped, n_clipped = winsorize_mu_ann(np.array([np.nan, 0.2, 4.3]))
        assert np.isnan(clipped[0])
        assert n_clipped == 1  # NaN is not > ceiling; only the 4.3 counts

    def test_winsorization_is_economically_neutral(self) -> None:
        # Solving with the raw-but-winsorized mu must equal solving with a
        # hand-clipped mu: the tail name maxes out w_max either way, so the
        # clip changes no weight. (solve() winsorizes internally; here we feed
        # an already-clipped vector and assert identical books.)
        n = 200
        mu_raw = legit_tail_mu(n, tail_value=4.3)
        mu_handclip, _ = winsorize_mu_ann(mu_raw)
        cov = 0.04 * np.eye(n)
        mvo = make_mvo(PortfolioConstraints())
        from_raw = mvo.solve(mu_raw, cov, np.zeros(n), np.zeros(n), np.ones(n))
        from_clip = mvo.solve(mu_handclip, cov, np.zeros(n), np.zeros(n), np.ones(n))
        np.testing.assert_allclose(from_raw.weights, from_clip.weights, atol=1e-9)


class TestMeanVarianceOptimizer:
    def test_unconstrained_limit_recovers_closed_form(self) -> None:
        # Huge caps, zero costs, zero turnover penalty: the optimum is the
        # analytic w* = (1/lambda) Sigma^-1 mu.
        n = 4
        cov = rand_cov(n, seed=21)
        mu = np.array([0.10, -0.05, 0.08, 0.02])
        mvo = make_mvo(LOOSE)
        res = mvo.solve(mu, cov, np.zeros(n), np.zeros(n), np.ones(n))
        want = np.linalg.solve(7.0 * cov, mu)
        assert res.status == "optimal"
        np.testing.assert_allclose(res.weights, want, atol=1e-6)
        assert res.ex_ante_vol_ann == pytest.approx(float(np.sqrt(want @ cov @ want)), abs=1e-6)

    def test_gross_binds_exactly_when_alpha_huge(self) -> None:
        n = 4
        cov = 0.04 * np.eye(n)
        mu = np.array([2.0, -2.0, 2.0, -2.0])  # inside tripwire, dwarfs risk term
        cons = PortfolioConstraints(gross_max=1.0, net_max=0.5, w_max=1.0, turnover_max=100.0)
        res = make_mvo(cons).solve(mu, cov, np.zeros(n), np.zeros(n), np.ones(n))
        assert res.status == "optimal"
        assert float(np.abs(res.weights).sum()) == pytest.approx(1.0, abs=1e-5)

    def test_turnover_cap_binds_vs_w_prev(self) -> None:
        n = 4
        cov = 0.04 * np.eye(n)
        mu = np.array([2.0, -2.0, 2.0, -2.0])
        w_prev = np.zeros(n)
        cons = PortfolioConstraints(gross_max=1.0, net_max=0.5, w_max=0.5, turnover_max=0.05)
        res = make_mvo(cons).solve(mu, cov, w_prev, np.zeros(n), np.ones(n))
        assert res.status == "optimal"
        turnover = float(np.abs(res.weights - w_prev).sum())
        assert turnover == pytest.approx(0.05, abs=1e-5)
        assert turnover <= 0.05 + 1e-5

    def test_cost_penalty_shrinks_trading(self) -> None:
        # Same alpha, c = 0 vs c = 50 bps one-way: the amortized penalty
        # A*c = (8760/72)*0.005 ~ 0.61 per unit turnover bites, so the
        # costly book trades strictly less from the same w_prev.
        n = 4
        cov = rand_cov(n, seed=22)
        mu = np.array([0.40, 0.20, -0.30, 0.10])
        w_prev = np.zeros(n)
        cons = PortfolioConstraints(gross_max=1.0, net_max=0.5, w_max=0.15, turnover_max=100.0)
        mvo = make_mvo(cons)
        free = mvo.solve(mu, cov, w_prev, np.zeros(n), np.ones(n))
        costly = mvo.solve(mu, cov, w_prev, np.full(n, 0.005), np.ones(n))
        trade_free = float(np.abs(free.weights - w_prev).sum())
        trade_costly = float(np.abs(costly.weights - w_prev).sum())
        assert trade_costly < trade_free - 1e-4

    def test_non_shortable_asset_never_short(self) -> None:
        n = 4
        cov = 0.04 * np.eye(n)
        mu = np.array([0.5, -0.5, 0.5, -0.5])
        shortable = np.array([1.0, 0.0, 1.0, 1.0])  # asset 1 wants short, can't
        res = make_mvo(PortfolioConstraints()).solve(mu, cov, np.zeros(n), np.zeros(n), shortable)
        assert res.status == "optimal"
        assert res.weights[1] >= -1e-7
        assert res.weights[3] < -1e-4  # the shortable bad asset IS shorted

    def test_infeasible_problem_delegates_to_fallback(self) -> None:
        # w_prev gross = 4 with gross_max = 1 and turnover_max = 0.1 admits no
        # feasible w: the solver reports infeasible and the rank/inverse-vol
        # fallback takes over, flagged in status.
        n = 8
        cov = 0.04 * np.eye(n)
        mu = np.linspace(0.5, -0.5, n)
        w_prev = np.full(n, 0.5)
        res = make_mvo(PortfolioConstraints()).solve(mu, cov, w_prev, np.zeros(n), np.ones(n))
        assert res.status == "fallback_used"
        assert float(np.abs(res.weights).sum()) == pytest.approx(0.5 * 1.0, abs=1e-12)

    def test_from_settings_uses_the_one_horizon_constant(self) -> None:
        settings = Settings()
        mvo = MeanVarianceOptimizer.from_settings(settings)
        assert mvo.holding_bars == settings.signals.horizon_bars == H
        assert mvo.cost_amortization == pytest.approx(8760.0 / 72.0)
        assert mvo.risk_aversion == settings.portfolio.risk_aversion == 7.0
        assert mvo.constraints == PortfolioConstraints(
            gross_max=1.0, net_max=0.5, w_max=0.15, turnover_max=0.10
        )

    def test_input_validation(self) -> None:
        mvo = make_mvo(PortfolioConstraints())
        n = 4
        good = (0.04 * np.eye(n), np.zeros(n), np.zeros(n), np.ones(n))
        with pytest.raises(ValueError, match="finite"):
            mvo.solve(np.array([np.nan, 0.1, 0.1, 0.1]), *good)
        with pytest.raises(ValueError, match="cov_ann must be"):
            mvo.solve(np.zeros(n), np.eye(3), np.zeros(n), np.zeros(n), np.ones(n))
        with pytest.raises(ValueError, match=">= 0"):
            mvo.solve(np.zeros(n), 0.04 * np.eye(n), np.zeros(n), -np.ones(n), np.ones(n))
        with pytest.raises(ValueError, match="shortable"):
            mvo.solve(np.zeros(n), 0.04 * np.eye(n), np.zeros(n), np.zeros(n), np.full(n, 0.5))

    def test_bad_construction_raises(self) -> None:
        with pytest.raises(ValueError, match="risk_aversion"):
            MeanVarianceOptimizer(risk_aversion=0.0, holding_bars=H)
        with pytest.raises(ValueError, match="holding_bars"):
            MeanVarianceOptimizer(holding_bars=0)
        with pytest.raises(ValueError, match="solver"):
            MeanVarianceOptimizer(holding_bars=H, solver="ECOS")


class TestRankEqualVolFallback:
    def make_inputs(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        n = 12  # K = min(10, 12 // 4) = 3
        mu = np.linspace(0.5, -0.5, n)
        # Vols chosen so no inverse-vol weight breaches w_max = 0.15: the
        # half-gross normalization is then exact (clip case tested separately).
        sigma = np.linspace(0.3, 0.5, n)
        cov = np.diag(sigma**2)
        return mu, cov, np.zeros(n), np.zeros(n), np.ones(n)

    def test_half_gross_and_long_short_selection(self) -> None:
        mu, cov, w_prev, cost, short = self.make_inputs()
        res = RankEqualVolFallback().solve(mu, cov, w_prev, cost, short)
        assert res.status == "fallback_used"
        assert float(np.abs(res.weights).sum()) == pytest.approx(0.5, abs=1e-12)
        assert np.all(res.weights[:3] > 0.0)  # top-3 mu long
        assert np.all(res.weights[-3:] < 0.0)  # bottom-3 mu short
        assert np.all(res.weights[3:9] == 0.0)  # middle flat

    def test_inverse_vol_proportionality(self) -> None:
        mu, cov, w_prev, cost, short = self.make_inputs()
        res = RankEqualVolFallback().solve(mu, cov, w_prev, cost, short)
        sigma = np.sqrt(np.diag(cov))
        # Within the selected legs, w_i * sigma_i is the same constant (sign apart).
        scaled = res.weights * sigma
        assert scaled[0] == pytest.approx(scaled[1], abs=1e-12)
        assert scaled[0] == pytest.approx(scaled[2], abs=1e-12)
        assert scaled[-1] == pytest.approx(-scaled[0], abs=1e-12)

    def test_determinism(self) -> None:
        mu, cov, w_prev, cost, short = self.make_inputs()
        fb = RankEqualVolFallback()
        a = fb.solve(mu, cov, w_prev, cost, short)
        b = fb.solve(mu, cov, w_prev, cost, short)
        assert np.array_equal(a.weights, b.weights)
        assert a.ex_ante_vol_ann == b.ex_ante_vol_ann
        assert a.objective == b.objective

    def test_shortable_mask_drops_short_leg(self) -> None:
        mu, cov, w_prev, cost, short = self.make_inputs()
        short[-1] = 0.0  # worst-mu asset cannot be shorted
        res = RankEqualVolFallback().solve(mu, cov, w_prev, cost, short)
        assert res.weights[-1] == 0.0
        # Book renormalizes to half gross over the remaining 5 legs.
        assert float(np.abs(res.weights).sum()) == pytest.approx(0.5, abs=1e-12)

    def test_w_max_clip_caps_book(self) -> None:
        # N=4 -> K=1: half gross 0.25 per leg would breach w_max=0.15; after
        # clip the renormalization is capped so no weight re-exceeds w_max.
        n = 4
        mu = np.array([0.4, 0.1, -0.1, -0.4])
        cov = 0.04 * np.eye(n)
        res = RankEqualVolFallback().solve(mu, cov, np.zeros(n), np.zeros(n), np.ones(n))
        assert res.weights[0] == pytest.approx(0.15, abs=1e-12)
        assert res.weights[3] == pytest.approx(-0.15, abs=1e-12)
        assert float(np.abs(res.weights).max()) <= 0.15 + 1e-12

    @pytest.mark.parametrize("n", [2, 3])
    def test_thin_universe_produces_a_real_long_short_book_not_a_silent_flat(self, n: int) -> None:
        """A3: at N in {2,3} raw min(10, N//4)=0 used to emit an all-zero book
        labelled status="fallback_used" — indistinguishable from a real flat
        decision and counted as a rebalance upstream. The k>=1 floor must now
        produce a NON-degenerate one-long/one-short rank book (gross > 0), never
        a silent flat book that an mvo-vs-rank run cannot tell apart."""
        mu = np.linspace(0.3, -0.3, n)  # strictly descending: clean rank
        cov = 0.04 * np.eye(n)
        res = RankEqualVolFallback().solve(mu, cov, np.zeros(n), np.zeros(n), np.ones(n))
        gross = float(np.abs(res.weights).sum())
        assert gross > 0.0, "thin universe must not return a silent flat book"
        assert res.weights[0] > 0.0, "best-mu name is the long leg"
        assert res.weights[-1] < 0.0, "worst-mu name is the short leg"
        # Exactly one long and one short leg (k=1), no overlap, rest flat.
        assert int(np.sum(res.weights > 0.0)) == 1
        assert int(np.sum(res.weights < 0.0)) == 1
        assert res.ex_ante_vol_ann > 0.0
        # ex-ante vol still equals the quadratic form (no degenerate path).
        assert res.ex_ante_vol_ann == pytest.approx(
            float(np.sqrt(res.weights @ cov @ res.weights)), abs=1e-15
        )

    def test_single_name_universe_is_genuinely_flat(self) -> None:
        """N=1 has no cross-sectional rank (long==short would be one name), so a
        flat book is CORRECT here — distinct from the N in {2,3} thin-universe
        hole. Guards the k = ... if n >= 2 else 0 branch against an overlap bug."""
        res = RankEqualVolFallback().solve(
            np.array([0.1]), np.array([[0.04]]), np.zeros(1), np.zeros(1), np.ones(1)
        )
        assert np.all(res.weights == 0.0)
        assert res.ex_ante_vol_ann == 0.0

    def test_ex_ante_vol_matches_quadratic_form(self) -> None:
        mu, cov, w_prev, cost, short = self.make_inputs()
        res = RankEqualVolFallback().solve(mu, cov, w_prev, cost, short)
        want = float(np.sqrt(res.weights @ cov @ res.weights))
        assert res.ex_ante_vol_ann == pytest.approx(want, abs=1e-15)
        assert res.objective == pytest.approx(float(mu @ res.weights), abs=1e-15)


class TestOptResult:
    def test_to_targets_zips_in_order(self) -> None:
        res = OptResult(
            weights=np.array([0.1, -0.2]), status="optimal", ex_ante_vol_ann=0.1, objective=0.0
        )
        assert res.to_targets(["A", "B"]) == {"A": 0.1, "B": -0.2}

    def test_to_targets_length_mismatch_raises(self) -> None:
        res = OptResult(
            weights=np.array([0.1]), status="optimal", ex_ante_vol_ann=0.1, objective=0.0
        )
        with pytest.raises(ValueError, match="instrument_ids"):
            res.to_targets(["A", "B"])


# --------------------------------------------------------------------------- #
# A4: optimizer constraint-feasibility as a hypothesis property.
# The constraint-binding tests above are hand-picked single cases; this fuzzes
# random (mu, PSD Sigma) and asserts the returned book is ALWAYS inside the
# caps and NEVER a silent infeasible result. hypothesis is already a dependency
# (no pyproject change). derandomize=True keeps it deterministic & offline.
# --------------------------------------------------------------------------- #

_TOL = 1e-5  # solver tolerance (matches the binding tests above)
_FUZZ_CONSTRAINTS = PortfolioConstraints(gross_max=1.0, net_max=0.5, w_max=0.15, turnover_max=0.10)


def _psd_cov(a: np.ndarray) -> np.ndarray:
    """A @ A.T + eps*I -> a strictly-PD annualized covariance (vols ~ A scale)."""
    n = a.shape[0]
    cov: np.ndarray = 1e-3 * np.eye(n) + a @ a.T
    return cov


def _assert_caps_hold(res: OptResult, short: np.ndarray, cons: PortfolioConstraints) -> None:
    """Invariants that hold for BOTH allocator paths (solver AND rank fallback):
    gross cap, per-name cap, the non-shortable mask, finite weights, and a
    status drawn only from the two declared states (never silent infeasible)."""
    w = res.weights
    assert np.all(np.isfinite(w)), "weights must be finite"
    assert res.status in {"optimal", "fallback_used"}, f"rogue status {res.status!r}"
    assert float(np.abs(w).sum()) <= cons.gross_max + _TOL, "gross cap breached"
    assert float(np.abs(w).max(initial=0.0)) <= cons.w_max + _TOL, "w_max breached"
    # Non-shortable names (short==0) must never carry a negative weight.
    non_shortable = short == 0.0
    if np.any(non_shortable):
        assert np.all(w[non_shortable] >= -_TOL), "non-shortable name went short"


class TestOptimizerConstraintFeasibilityProperty:
    """A4: random (mu, PSD Sigma) -> the book always respects the caps."""

    @settings(max_examples=120, derandomize=True, deadline=None)
    @given(
        n=st.integers(min_value=2, max_value=8),
        data=st.data(),
    )
    def test_mvo_from_flat_book_satisfies_every_constraint(
        self, n: int, data: st.DataObject
    ) -> None:
        """With w_prev = 0 the turnover constraint sum|w-0| <= turnover_max is
        feasible (w=0 always works), so the solver returns an OPTIMAL book and
        EVERY constraint -- gross, net, w_max, turnover, non-shortable -- must
        hold. This is the strongest always-feasible feasibility property."""
        mu = data.draw(
            hnp.arrays(
                np.float64,
                shape=n,
                # inside the mu_ann tripwire (median |mu| << 3.0): sane alphas.
                elements=st.floats(min_value=-1.5, max_value=1.5, allow_nan=False),
            )
        )
        a = data.draw(
            hnp.arrays(
                np.float64,
                shape=(n, n),
                elements=st.floats(min_value=-0.5, max_value=0.5, allow_nan=False),
            )
        )
        short = data.draw(hnp.arrays(np.float64, shape=n, elements=st.sampled_from([0.0, 1.0])))
        cov = _psd_cov(a)
        w_prev = np.zeros(n)
        cost = np.zeros(n)
        cons = _FUZZ_CONSTRAINTS
        res = make_mvo(cons).solve(mu, cov, w_prev, cost, short)
        _assert_caps_hold(res, short, cons)
        if res.status == "optimal":
            # Net and turnover only bind on the genuine solver solution; the
            # rank fallback (degenerate-but-feasible inputs) ignores both.
            assert float(abs(res.weights.sum())) <= cons.net_max + _TOL, "net cap breached"
            turnover = float(np.abs(res.weights - w_prev).sum())
            assert turnover <= cons.turnover_max + _TOL, "turnover cap breached"

    @settings(max_examples=120, derandomize=True, deadline=None)
    @given(
        n=st.integers(min_value=2, max_value=8),
        data=st.data(),
    )
    def test_any_w_prev_never_breaches_gross_wmax_or_shortable(
        self, n: int, data: st.DataObject
    ) -> None:
        """With an ARBITRARY w_prev a tight turnover cap can make the MVO
        infeasible and route to the rank fallback. Whichever path is taken, the
        path-invariant caps (gross, w_max, non-shortable) and a valid status
        must still hold -- the optimizer NEVER returns a silent infeasible book
        nor a degenerate all-zero "fallback_used" for a sized universe."""
        mu = data.draw(
            hnp.arrays(
                np.float64,
                shape=n,
                elements=st.floats(min_value=-1.5, max_value=1.5, allow_nan=False),
            )
        )
        a = data.draw(
            hnp.arrays(
                np.float64,
                shape=(n, n),
                elements=st.floats(min_value=-0.5, max_value=0.5, allow_nan=False),
            )
        )
        w_prev = data.draw(
            hnp.arrays(
                np.float64,
                shape=n,
                elements=st.floats(min_value=-0.3, max_value=0.3, allow_nan=False),
            )
        )
        short = np.ones(n)  # all shortable: keeps the fallback book non-empty
        cov = _psd_cov(a)
        cost = np.full(n, 1e-3)
        cons = _FUZZ_CONSTRAINTS
        res = make_mvo(cons).solve(mu, cov, w_prev, cost, short)
        _assert_caps_hold(res, short, cons)
        # A3 corollary: when the rank FALLBACK is reached for a sized, all-
        # shortable universe (n>=2) the book is a real long/short rank book,
        # never the old silent all-zero "fallback_used". (A genuine solver
        # decision to hold flat at mu~0 is NOT a bug, so this is fallback-only.)
        if res.status == "fallback_used":
            assert float(np.abs(res.weights).sum()) > 0.0, "fallback went silently flat"
