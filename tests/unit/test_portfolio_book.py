"""Unit tests for alphaforge.portfolio.book (CrossAssetBook combiner).

Covers the institutional non-negotiables: PIT weights/leverage (no look-ahead), the
diversification identity (decorrelated sleeves → combined Sharpe ≈ sqrt(ΣS²)), vol-target
convergence, correlation measured on common active days, and the static-vs-PIT distinction.
Synthetic curves are constructed from known return streams so every assertion is exact-ish.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from alphaforge.portfolio.book import DAY_MS, SleeveCurve, combine_book


def _curve(
    name: str, rets: np.ndarray, *, start_day: int = 19_000, step_days: int = 1
) -> SleeveCurve:
    """Build a SleeveCurve from a daily return stream (equity = cumprod, base 100k)."""
    eq = 100_000.0 * np.cumprod(1.0 + np.concatenate([[0.0], rets]))
    ts = [(start_day + i * step_days) * DAY_MS for i in range(eq.size)]
    return SleeveCurve(name=name, ts_ms=ts, equity=eq.tolist())


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


class TestDailyResample:
    def test_returns_recovered_from_equity(self) -> None:
        rets = np.array([0.01, -0.02, 0.015, 0.0, 0.03])
        book = combine_book([_curve("a", rets)], scheme="equal_weight")
        np.testing.assert_allclose(book.sleeve_returns["a"], rets, atol=1e-12)

    def test_hourly_curve_collapses_to_daily(self) -> None:
        # 6 days of hourly marks → 5 daily returns; intra-day marks overwritten by day-close.
        n_days = 6
        ts = [19_000 * DAY_MS + h * 3_600_000 for h in range(24 * n_days)]
        eq = [100_000.0 * (1.0 + 0.0001 * h) for h in range(24 * n_days)]
        daily_partner = _curve("d", np.full(n_days, 0.001), start_day=19_000)
        book = combine_book([SleeveCurve("h", ts, eq), daily_partner], scheme="equal_weight")
        # hourly sleeve collapses to one return per day over the common window
        assert book.n_days >= n_days - 2
        assert np.all(book.sleeve_returns["h"] != 0.0)  # genuine daily returns, not padding


class TestDiversification:
    def test_decorrelated_sleeves_hit_sqrt_sum_squares(self) -> None:
        """Two uncorrelated positive-Sharpe sleeves → combined ≈ sqrt(S_a² + S_b²)."""
        rng = _rng(42)
        n = 2000
        a = 0.0008 + 0.01 * rng.standard_normal(n)  # ~Sharpe 1.5-ish daily→ann
        b = 0.0008 + 0.01 * rng.standard_normal(n)
        book = combine_book(
            [_curve("a", a), _curve("b", b)],
            scheme="static",  # full-sample equal-risk = the clean theory check
            trading_days=365,
        )
        assert abs(book.corr[("a", "b")]) < 0.1  # genuinely decorrelated
        # sqrt(ΣS²) is the CEILING (optimal weights, zero corr); equal-risk lands below it
        # but above the better standalone. For two ~equal sleeves standalone ≈ ceiling/√2.
        standalone_approx = book.sharpe_theory_uncorr / math.sqrt(2)
        assert book.sharpe > standalone_approx  # diversification genuinely lifts Sharpe
        assert book.sharpe <= book.sharpe_theory_uncorr * 1.02  # never exceeds the ceiling
        assert book.sharpe == pytest.approx(book.sharpe_theory_uncorr, rel=0.2)

    def test_perfectly_correlated_sleeves_give_no_diversification(self) -> None:
        rng = _rng(7)
        a = 0.0005 + 0.01 * rng.standard_normal(1500)
        book = combine_book(
            [_curve("a", a), _curve("b", a.copy())],  # identical → corr 1
            scheme="static",
        )
        assert book.corr[("a", "b")] == pytest.approx(1.0, abs=1e-6)
        assert book.diversification_ratio == pytest.approx(1.0, abs=0.02)

    def test_diversification_ratio_above_one_when_decorrelated(self) -> None:
        rng = _rng(11)
        a = 0.0005 + 0.012 * rng.standard_normal(1500)
        b = 0.0005 + 0.012 * rng.standard_normal(1500)
        book = combine_book([_curve("a", a), _curve("b", b)], scheme="static")
        assert book.diversification_ratio > 1.2  # near sqrt(2) for two equal-vol uncorr sleeves


class TestPITNoLookahead:
    def test_weights_only_depend_on_past(self) -> None:
        """Truncating the future must not change any weight at/before the truncation day."""
        rng = _rng(3)
        a = 0.0005 + 0.01 * rng.standard_normal(800)
        b = 0.0005 + 0.02 * rng.standard_normal(800)  # different vol → non-trivial weights
        full = combine_book([_curve("a", a), _curve("b", b)], scheme="equal_risk")
        cut = 600
        trunc = combine_book([_curve("a", a[:cut]), _curve("b", b[:cut])], scheme="equal_risk")
        m = trunc.n_days
        # weights over the shared prefix must be byte-identical (pure function of the past)
        np.testing.assert_allclose(full.weights["a"][:m], trunc.weights["a"][:m], atol=1e-12)
        np.testing.assert_allclose(full.weights["b"][:m], trunc.weights["b"][:m], atol=1e-12)

    def test_static_scheme_is_flagged_not_pit(self) -> None:
        rng = _rng(5)
        a = 0.0005 + 0.01 * rng.standard_normal(500)
        b = 0.0005 + 0.01 * rng.standard_normal(500)
        assert combine_book([_curve("a", a), _curve("b", b)], scheme="static").pit is False
        assert combine_book([_curve("a", a), _curve("b", b)], scheme="equal_risk").pit is True


class TestVolTarget:
    def test_vol_target_brings_book_near_target(self) -> None:
        rng = _rng(9)
        a = 0.0003 + 0.006 * rng.standard_normal(2500)  # low vol so leverage > 1 is needed
        b = 0.0003 + 0.006 * rng.standard_normal(2500)
        target = 0.20
        book = combine_book(
            [_curve("a", a), _curve("b", b)],
            scheme="equal_risk",
            vol_target_ann=target,
            max_leverage=5.0,
            trading_days=365,
        )
        # realized book vol should be in the neighborhood of the target (PIT, so not exact)
        assert 0.13 < book.vol < 0.30
        assert np.all(book.leverage > 0)

    def test_per_sleeve_gross_cap_binds_below_book_leverage(self) -> None:
        """A dollar-neutral sleeve (gross 2x) under a Reg-T 2x venue cap must constrain the
        book leverage below what the vol-target alone would demand."""
        rng = _rng(17)
        a = 0.0003 + 0.006 * rng.standard_normal(2000)  # low vol -> vol-target wants high lev
        b = 0.0003 + 0.006 * rng.standard_normal(2000)
        uncapped = combine_book(
            [_curve("eq", a), _curve("cr", b)],
            scheme="equal_risk",
            vol_target_ann=0.30,
            max_leverage=5.0,
        )
        capped = combine_book(
            [_curve("eq", a), _curve("cr", b)],
            scheme="equal_risk",
            vol_target_ann=0.30,
            max_leverage=5.0,
            sleeve_gross={"eq": 2.0, "cr": 1.0},  # eq is dollar-neutral L/S
            venue_gross_cap={"eq": 2.0, "cr": 3.0},  # Reg-T 2x on equity
        )
        # equity realized gross must never breach its venue cap
        assert np.max(capped.sleeve_gross_exposure["eq"]) <= 2.0 + 1e-9
        # the cap genuinely bit: capped leverage is strictly lower where eq weight is high
        assert capped.leverage.mean() < uncapped.leverage.mean()

    def test_gross_exposure_reported_without_cap(self) -> None:
        rng = _rng(23)
        a = 0.0005 + 0.01 * rng.standard_normal(600)
        b = 0.0005 + 0.01 * rng.standard_normal(600)
        book = combine_book(
            [_curve("eq", a), _curve("cr", b)],
            scheme="equal_weight",
            sleeve_gross={"eq": 2.0, "cr": 1.0},
        )
        # unleveraged book: eq gross = 1.0*0.5*2.0 = 1.0, cr gross = 1.0*0.5*1.0 = 0.5
        np.testing.assert_allclose(book.sleeve_gross_exposure["eq"], 1.0, atol=1e-9)
        np.testing.assert_allclose(book.sleeve_gross_exposure["cr"], 0.5, atol=1e-9)

    def test_max_leverage_caps(self) -> None:
        rng = _rng(13)
        a = 0.0001 + 0.001 * rng.standard_normal(1500)  # tiny vol → wants huge leverage
        b = 0.0001 + 0.001 * rng.standard_normal(1500)
        book = combine_book(
            [_curve("a", a), _curve("b", b)],
            scheme="equal_risk",
            vol_target_ann=0.50,
            max_leverage=2.0,
        )
        assert np.max(book.leverage) <= 2.0 + 1e-9


class TestWeightSchemes:
    def test_weights_sum_to_one_each_day(self) -> None:
        rng = _rng(1)
        a = 0.0005 + 0.01 * rng.standard_normal(700)
        b = 0.0005 + 0.03 * rng.standard_normal(700)
        for scheme in ("equal_risk", "inverse_var", "equal_weight", "static"):
            book = combine_book([_curve("a", a), _curve("b", b)], scheme=scheme)  # type: ignore[arg-type]
            tot = book.weights["a"] + book.weights["b"]
            np.testing.assert_allclose(tot, 1.0, atol=1e-9)

    def test_equal_risk_underweights_the_vol_hog(self) -> None:
        rng = _rng(2)
        calm = 0.0005 + 0.005 * rng.standard_normal(1500)
        wild = 0.0005 + 0.020 * rng.standard_normal(1500)
        book = combine_book([_curve("calm", calm), _curve("wild", wild)], scheme="static")
        assert book.weights["calm"][-1] > book.weights["wild"][-1]

    def test_fixed_weights_respected(self) -> None:
        rng = _rng(4)
        a = 0.0005 + 0.01 * rng.standard_normal(400)
        b = 0.0005 + 0.01 * rng.standard_normal(400)
        book = combine_book(
            [_curve("a", a), _curve("b", b)],
            scheme="fixed",
            fixed_weights={"a": 0.7, "b": 0.3},
        )
        assert book.weights["a"][0] == pytest.approx(0.7)
        assert book.weights["b"][0] == pytest.approx(0.3)


class TestWindowAndErrors:
    def test_common_window_is_intersection_of_spans(self) -> None:
        a = _curve("a", np.full(100, 0.001), start_day=19_000)
        b = _curve("b", np.full(100, 0.001), start_day=19_050)  # starts 50 days later
        book = combine_book([a, b], scheme="equal_weight")
        assert book.window[0] >= 19_050  # book starts only when both are live

    def test_raises_on_non_overlapping_sleeves(self) -> None:
        a = _curve("a", np.full(10, 0.001), start_day=19_000)
        b = _curve("b", np.full(10, 0.001), start_day=20_000)
        with pytest.raises(ValueError, match=r"overlap|window"):
            combine_book([a, b], scheme="equal_weight")

    def test_single_sleeve_passthrough(self) -> None:
        rets = np.array([0.01, -0.01, 0.02, 0.0, 0.005])
        book = combine_book([_curve("solo", rets)], scheme="equal_weight")
        np.testing.assert_allclose(book.book_returns, rets, atol=1e-12)
        assert book.diversification_ratio == pytest.approx(1.0, abs=1e-6)


class TestCorrelationOnActiveDays:
    def test_weekend_padding_does_not_distort_correlation(self) -> None:
        """A session sleeve (5/7 days) padded with weekend zeros must still report the
        true co-movement with a 24/7 sleeve — correlation is on common ACTIVE days only."""
        rng = _rng(21)
        n = 800
        daily_24_7 = 0.0005 + 0.01 * rng.standard_normal(n)
        crypto = _curve("crypto", daily_24_7, start_day=19_000, step_days=1)
        # equity present only on ~5/7 days (skip weekends): build sparse ts
        eq_rets = 0.0005 + 0.01 * rng.standard_normal(n)
        eq_eq = 100_000.0 * np.cumprod(1.0 + np.concatenate([[0.0], eq_rets]))
        ts, vals, d = [], [], 19_000
        for i in range(eq_eq.size):
            while d % 7 in (5, 6):  # skip "weekends"
                d += 1
            ts.append(d * DAY_MS)
            vals.append(eq_eq[i])
            d += 1
        equity = SleeveCurve("equity", ts, vals)
        book = combine_book([crypto, equity], scheme="equal_weight")
        # genuinely independent draws → |corr| small even though equity is padded with zeros
        assert abs(book.corr[("crypto", "equity")]) < 0.15
