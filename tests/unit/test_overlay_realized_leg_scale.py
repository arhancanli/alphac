"""The overlay's realized leg must be measured on the UNLEVERED book.

`BlendStrategy._realized_vol_ann` reads `_equity_hist`, which is the POST-overlay account
curve. It is compared inside `vol_target` against an ex-ante vol computed from the optimizer's
PRE-overlay weights. While the book runs de-levered (s < 1) the realized side is shrunk by
roughly s, always loses `max(ex_ante, realized)`, and the FAST regime detector (halflife 240)
is silently disabled -- leaving only the SLOW covariance leg (halflife 720). Measured in
artifacts/analysis/frontier_14: bound on 0.02% of days as shipped vs 81.8% de-levered, worth
+0.6 to +2.2pp of expected max drawdown.

WHY A NEW FILE RATHER THAN A CASE IN test_overlay.py: the existing
`test_overlay.py::test_realized_vol_dominates_when_larger` calls `vol_target()` directly with a
hand-passed realized value. It passed all the way through this defect and would pass if the fix
were reverted, because it pins the FUNCTION'S INTENTION and never the value the caller actually
supplies. These tests pin the caller's value and the consequence at the call site.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from alphaforge.portfolio.overlay import vol_target
from alphaforge.portfolio.strategy import BlendStrategy

_HL = 240.0
_PPY = 252.0


def _strategy(equity: list[float], scales: list[float]) -> BlendStrategy:
    """A BlendStrategy carrying only the state `_realized_vol_ann` reads."""
    s = object.__new__(BlendStrategy)
    s._equity_hist = list(equity)  # type: ignore[attr-defined]
    s._scale_hist = list(scales)  # type: ignore[attr-defined]
    s._rv_halflife_bars = _HL  # type: ignore[attr-defined]
    return s


def _naive_vol(equity: list[float]) -> float:
    """The pre-fix computation, reproduced verbatim, as the comparison baseline."""
    import pandas as pd

    eq = np.asarray(equity, dtype=np.float64)
    rets = eq[1:] / eq[:-1] - 1.0
    var = pd.Series(rets).pow(2).ewm(halflife=_HL, adjust=True, min_periods=1).mean().iloc[-1]
    return float(np.sqrt(max(float(var), 0.0)) * np.sqrt(_PPY))


def _equity_from(rets: np.ndarray) -> list[float]:
    return [1.0, *np.cumprod(1.0 + rets).tolist()]


@pytest.fixture
def levered_run() -> tuple[list[float], list[float], float]:
    """A book held at a constant 0.25x overlay scale.

    Returns (equity, scales, s) where the account's realized vol is 0.25x the unlevered
    book's, which is precisely the distortion the defect fed into `max(ex_ante, realized)`.
    """
    s = 0.25
    rng = np.random.default_rng(20260818)
    unlevered = rng.normal(0.0, 0.02, size=600)
    equity = _equity_from(unlevered * s)
    scales = [math.nan, *([s] * (len(equity) - 1))]
    return equity, scales, s


def test_realized_vol_is_reported_on_the_unlevered_basis(levered_run) -> None:
    equity, scales, s = levered_run
    got = _strategy(equity, scales)._realized_vol_ann(_PPY)
    naive = _naive_vol(equity)
    # The account curve understates the unlevered book by ~s; de-levering restores it.
    assert got == pytest.approx(naive / s, rel=0.02), f"{got=} {naive=} {s=}"
    assert got > naive * 3.0, "de-levering must materially raise the realized leg"


def test_the_realized_leg_actually_wins_the_max_once_de_levered(levered_run) -> None:
    """The consequence, not the intention.

    Choose an ex-ante vol that sits BETWEEN the levered and de-levered realized values.
    The defect makes the overlay ignore the realized leg; the fix makes it bind, which is
    the entire purpose of the fast detector.
    """
    equity, scales, _ = levered_run
    fixed = _strategy(equity, scales)._realized_vol_ann(_PPY)
    naive = _naive_vol(equity)
    ex_ante = (naive + fixed) / 2.0
    assert naive < ex_ante < fixed, "fixture must bracket ex_ante to be meaningful"

    w = np.array([1.0])
    cov = np.array([[ex_ante**2]])
    _, s_defect = vol_target(w, cov, naive, target=0.10, s_max=1.5, gross_max=10.0)
    _, s_fixed = vol_target(w, cov, fixed, target=0.10, s_max=1.5, gross_max=10.0)

    assert s_defect == pytest.approx(0.10 / ex_ante), "as shipped, ex_ante wins and realized is inert"
    assert s_fixed == pytest.approx(0.10 / fixed), "de-levered, the realized leg binds"
    assert s_fixed < s_defect, "binding on the hotter estimate must DE-lever further"


def test_bars_before_the_first_rebalance_are_excluded() -> None:
    """`_last_scale` is NaN until the first rebalance; those bars carry no scale information."""
    rets = np.concatenate([np.full(40, 0.05), np.full(400, 0.001)])
    equity = _equity_from(rets)
    scales = [math.nan] * 41 + [0.5] * (len(equity) - 41)
    got = _strategy(equity, scales)._realized_vol_ann(_PPY)
    assert math.isfinite(got) and got > 0.0


def test_flat_halted_bars_do_not_understate_vol() -> None:
    """A halted book has scale 0 and ~0 returns.

    Flooring the divisor would push a spurious 0 into the EWMA and understate vol exactly
    when risk is highest. Those bars must be dropped, not divided.
    """
    live = np.full(300, 0.02)
    halted = np.zeros(60)
    equity = _equity_from(np.concatenate([live, halted]))
    dropped = [math.nan, *([0.5] * 300), *([0.0] * 60)]
    floored = [math.nan, *([0.5] * 360)]
    got_dropped = _strategy(equity, dropped)._realized_vol_ann(_PPY)
    got_if_zeros_counted = _strategy(equity, floored)._realized_vol_ann(_PPY)
    assert got_dropped > got_if_zeros_counted, (
        "dropping halted bars must not report LOWER vol than counting their zero returns"
    )


def test_mismatched_history_lengths_fall_back_rather_than_crash() -> None:
    """Defensive: a scale history that is not index-aligned must not raise in a live loop."""
    equity = _equity_from(np.full(50, 0.01))
    got = _strategy(equity, [math.nan, 0.5])._realized_vol_ann(_PPY)
    assert math.isfinite(got) and got >= 0.0


def test_this_check_can_fail(levered_run) -> None:
    """A check that cannot fail is worse than no check.

    Asserts the pre-fix baseline really is the shrunken value, so if someone reverts the
    de-levering the two tests above cannot both still pass.
    """
    equity, _, s = levered_run
    naive = _naive_vol(equity)
    unlevered_direct = _naive_vol(_equity_from((np.asarray(equity[1:]) / np.asarray(equity[:-1]) - 1.0) / s))
    assert naive == pytest.approx(unlevered_direct * s, rel=0.05)
