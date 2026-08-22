"""The live covariance estimator's memory is not the halflife it is given.

`ewma_cov` sees only `cov_window_bars` rows and seeds S_0 with the EQUALLY WEIGHTED sample
covariance of the oldest `cov_min_periods` rows, then decays that seed block by lambda^k. So the
window bounds the memory: on the crypto H1 sleeve a 720-bar window is 30 DAYS, and no halflife --
21 days or 720 -- can give the estimator more memory than that.

The drawdown sweep that set overlay policy simulated an UNTRUNCATED recursion, where the median
weight age IS the halflife. Treating its ladder as a ladder of live settings assumes a mapping
that does not hold. scripts/analyze_live_covariance_memory.py measures the real one; this pins the
weights that analysis rests on against the production function itself, so the mapping cannot drift
away from the estimator it describes.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from alphaforge.portfolio.covariance import ewma_cov

REPO = Path(__file__).parents[2]
_spec = importlib.util.spec_from_file_location(
    "analyze_live_covariance_memory", REPO / "scripts" / "analyze_live_covariance_memory.py"
)
assert _spec is not None and _spec.loader is not None
memory = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(memory)


def _empirical_weight(row: int, halflife_bars: float) -> float:
    """A unit impulse at `row` makes out[0, 0] equal exactly that row's weight."""
    values = np.zeros((memory.WINDOW_BARS, 2))
    values[row, 0] = 1.0
    frame = pd.DataFrame(values, columns=["a", "b"])
    return float(
        ewma_cov(frame, halflife_bars=halflife_bars, min_periods=memory.MIN_PERIODS)[0, 0]
    )


@pytest.mark.parametrize("halflife", [21, 240, 504, 720, 17280])
def test_the_analytic_weights_are_the_production_weights(halflife: int) -> None:
    """Derived, then checked against the function it claims to describe."""
    analytic = memory.weights(halflife)
    assert analytic.shape == (memory.WINDOW_BARS,)
    assert analytic.sum() == pytest.approx(1.0, abs=1e-12), "the weights must be a distribution"
    for row in (0, memory.MIN_PERIODS - 1, memory.MIN_PERIODS, memory.WINDOW_BARS - 1, 480):
        assert _empirical_weight(row, halflife) == pytest.approx(
            float(analytic[row]), abs=1e-15
        ), f"row {row} disagrees with the production estimator at halflife {halflife}"


def test_the_seed_block_is_flat_and_never_vanishes() -> None:
    """The defect that makes the parameter differ from the memory."""
    for halflife in (21, 504, 720):
        w = memory.weights(halflife)
        seed = w[: memory.MIN_PERIODS]
        assert np.allclose(seed, seed[0]), "the seed block must be equally weighted"
        assert seed.sum() > 0.0, (
            "the seed block carries weight at every halflife, so the recursion can never fully "
            "forget the oldest rows inside the window"
        )


def test_the_window_caps_memory_below_the_requested_halflife() -> None:
    """A 720-bar window is 30 days on crypto; no halflife can buy more memory than that."""
    crypto_bars_per_day = memory.SLEEVES["crypto_H1"]
    window_days = memory.WINDOW_BARS / crypto_bars_per_day
    for days in (21.0, 252.0, 720.0):
        actual = memory.profile(days * crypto_bars_per_day, crypto_bars_per_day)
        assert actual["median_weight_age_days"] < window_days, (
            f"a {days:.0f}-day request cannot yield more than the {window_days:.0f}-day window"
        )
        if days > window_days:
            assert actual["median_weight_age_days"] < days, (
                "a request longer than the window must be truncated, not honoured"
            )


def test_the_same_request_means_different_things_on_the_two_sleeves() -> None:
    """One parameter, two calendars. Stated as a relationship, not two constants."""
    crypto = memory.profile(21.0 * 24, 24.0)
    equity = memory.profile(21.0 * 1, 1.0)
    assert crypto["effective_sample_rows"] > equity["effective_sample_rows"] * 5, (
        "the crypto sleeve packs far more bars into the same day count, so the same requested "
        "halflife gives it a much larger effective sample; if these converge, the per-calendar "
        "conversion has been dropped"
    )
