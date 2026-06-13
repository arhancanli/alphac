"""Portfolio monitors — historical VaR/CVaR, the drawdown ladder, and the
data-staleness circuit breaker (execDesign §7.2).

All state machines here are pure and deterministic: feed the same equity
sequence, get the same state sequence. Nothing reads the clock, the
filesystem, or global config.

VaR convention — DAILY returns, empirical, no distributional assumption:
    Hourly VaR scaled by ``sqrt(24)`` was REJECTED (leakageCritique finding
    29): iid scaling understates tail risk under volatility clustering, which
    is exactly when VaR matters. The monitor therefore consumes
    daily-aggregated portfolio returns directly and reports the 1-day numbers
    with no scaling step at all.
"""

from __future__ import annotations

import enum
import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from alphaforge.core.time import Ms

__all__ = [
    "DDState",
    "DrawdownLadder",
    "StalenessBreaker",
    "VarReport",
    "historical_var_cvar",
]


# --------------------------------------------------------------------------- VaR


@dataclass(frozen=True, slots=True, kw_only=True)
class VarReport:
    """Historical 1-day VaR/CVaR, both POSITIVE loss fractions of equity.

    ``n_obs`` is the number of daily returns actually used (after the window
    cut) and ``k_tail`` the number of tail observations averaged by CVaR.
    """

    confidence: float
    n_obs: int
    k_tail: int
    var_frac: float
    cvar_frac: float


def historical_var_cvar(
    daily_returns: Sequence[float] | npt.NDArray[np.float64],
    *,
    confidence: float = 0.99,
    window_days: int = 365,
) -> VarReport:
    """Empirical (historical-simulation) VaR and CVaR on DAILY returns.

    With tail probability ``p = 1 - confidence`` over the last
    ``window_days`` observations, sort returns ascending
    ``r_(1) <= ... <= r_(n)`` and take the order-statistic estimator::

        k     = max(1, floor(p * n))         # tail size
        VaR   = -r_(k)        ( = -quantile(1 - confidence), lower estimator)
        CVaR  = -(1/k) * sum_{j=1..k} r_(j)  ( = -mean of the tail)

    Exact, assumption-free, and hand-checkable on small fixtures (no
    interpolation between order statistics — interpolated quantiles invent
    loss levels never observed). Positive outputs = losses; CVaR >= VaR by
    construction. Daily aggregation per leakage finding 29 (module docstring).

    Raises ``ValueError`` on empty/non-finite input or invalid parameters.
    """
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"require 0 < confidence ({confidence}) < 1")
    if window_days < 1:
        raise ValueError(f"require window_days ({window_days}) >= 1")
    r = np.asarray(daily_returns, dtype=np.float64)
    if r.ndim != 1:
        raise ValueError(f"daily_returns must be 1-D, got shape {r.shape}")
    if r.size == 0:
        raise ValueError("daily_returns is empty")
    if not np.isfinite(r).all():
        raise ValueError("daily_returns contains non-finite values")
    window = r[-window_days:]
    n = int(window.size)
    p = 1.0 - confidence
    # 1e-9 guard: (1 - 0.80) * 10 = 1.9999999999999996 in float64 must count
    # as floor 2, not 1 — only ties within 1e-9 of an integer are affected,
    # where either tail size is statistically defensible.
    k = max(1, math.floor(p * n + 1e-9))
    tail = np.sort(window)[:k]
    return VarReport(
        confidence=confidence,
        n_obs=n,
        k_tail=k,
        var_frac=-float(tail[-1]),
        cvar_frac=-float(tail.mean()),
    )


# --------------------------------------------------------- drawdown ladder


class DDState(enum.StrEnum):
    """Drawdown-ladder states; the value doubles as the persisted label."""

    NORMAL = "normal"
    HALF_GROSS = "half_gross"
    FLAT_HALTED = "flat_halted"


class DrawdownLadder:
    """Drawdown-from-HWM state machine (execDesign §7.2). REAL states, not a
    threshold lookup — history matters (hysteresis, absorbing halt).

    Definitions: ``HWM_t = max(HWM_{t-1}, E_t)`` (while not halted),
    ``DD_t = 1 - E_t / HWM_t`` (positive fraction).

    Transitions on :meth:`update`:

    - NORMAL    --(DD >= dd_half_frac)--> HALF_GROSS
    - any live  --(DD >= dd_flat_frac)--> FLAT_HALTED
    - HALF_GROSS --(DD < 0.75 * dd_half_frac)--> NORMAL — recovery requires
      retracing to 75% of the trigger (hysteresis: oscillation around the
      threshold must not flap gross sizing on/off every bar).
    - FLAT_HALTED is ABSORBING: no equity print exits it — even a full
      recovery. The exit is :meth:`rearm`, an explicit manual human act
      (CLI ``alphaforge arm --confirm``): a 15% drawdown means the system was
      wrong in a way it cannot self-diagnose, so a human must inspect before
      capital is re-risked.

    HWM updates ONLY in NORMAL/HALF_GROSS and is FROZEN while halted: the
    book is flat, so post-halt equity drift is noise/funding, and letting it
    raise the bar would manufacture phantom drawdown (or, on :meth:`rearm`,
    instantly re-trip). Rearm resets HWM to the latest marked equity for the
    same reason.

    :meth:`gross_multiplier` is what the sizing layer consumes:
    1.0 / 0.5 / 0.0 for NORMAL / HALF_GROSS / FLAT_HALTED.
    """

    __slots__ = ("_dd_flat", "_dd_half", "_hwm", "_last_equity", "_release", "_state")

    #: HALF_GROSS releases to NORMAL only below this fraction of dd_half_frac.
    RELEASE_FRAC: float = 0.75

    def __init__(self, *, dd_half_frac: float = 0.10, dd_flat_frac: float = 0.15) -> None:
        if not 0.0 < dd_half_frac < dd_flat_frac < 1.0:
            raise ValueError(
                f"require 0 < dd_half_frac ({dd_half_frac}) < dd_flat_frac ({dd_flat_frac}) < 1"
            )
        self._dd_half = dd_half_frac
        self._dd_flat = dd_flat_frac
        self._release = self.RELEASE_FRAC * dd_half_frac
        self._hwm = math.nan
        self._last_equity = math.nan
        self._state = DDState.NORMAL

    @property
    def state(self) -> DDState:
        """Current ladder state."""
        return self._state

    @property
    def hwm(self) -> float:
        """Current high-water mark (NaN before the first update)."""
        return self._hwm

    @property
    def drawdown(self) -> float:
        """Current drawdown fraction ``1 - E/HWM`` (NaN before the first update)."""
        if math.isnan(self._hwm):
            return math.nan
        return 1.0 - self._last_equity / self._hwm

    def gross_multiplier(self) -> float:
        """Sizing multiplier the portfolio layer applies: 1.0 / 0.5 / 0.0."""
        if self._state is DDState.NORMAL:
            return 1.0
        if self._state is DDState.HALF_GROSS:
            return 0.5
        return 0.0

    def update(self, equity: float) -> DDState:
        """Mark equity, advance the state machine, return the new state."""
        if not math.isfinite(equity) or equity <= 0.0:
            raise ValueError(f"equity must be finite and > 0, got {equity!r}")
        self._last_equity = equity
        if self._state is DDState.FLAT_HALTED:
            # Absorbing: HWM frozen, no transition (see class docstring).
            return self._state
        self._hwm = equity if math.isnan(self._hwm) else max(self._hwm, equity)
        dd = 1.0 - equity / self._hwm
        if dd >= self._dd_flat:
            self._state = DDState.FLAT_HALTED
        elif self._state is DDState.NORMAL:
            if dd >= self._dd_half:
                self._state = DDState.HALF_GROSS
        elif dd < self._release:  # HALF_GROSS, hysteresis release
            self._state = DDState.NORMAL
        return self._state

    def rearm(self) -> None:
        """Manual exit from FLAT_HALTED (the ONLY exit): state -> NORMAL and
        HWM resets to the last marked equity, else the ladder would re-trip
        on the very next update. Raises ``RuntimeError`` if not halted —
        rearming a live ladder is operator error, not a no-op."""
        if self._state is not DDState.FLAT_HALTED:
            raise RuntimeError(f"rearm() is only valid in FLAT_HALTED, state is {self._state}")
        if math.isnan(self._last_equity):
            raise RuntimeError("rearm() before any equity update")
        self._hwm = self._last_equity
        self._state = DDState.NORMAL


# ------------------------------------------------------ staleness breaker


@dataclass(frozen=True, slots=True)
class StalenessBreaker:
    """Data-staleness circuit breaker (execDesign §7.2).

    Stale prices read as ZERO volatility — without this gate, vol targeting
    would lever up into a data outage. If the latest bar's close timestamp is
    more than ``max_bars`` bar intervals before ``now``, trading is forbidden
    for the cycle (positions are held, not flattened: no fresh prices means
    no informed orders, including exits).
    """

    max_bars: int

    def __post_init__(self) -> None:
        if self.max_bars < 1:
            raise ValueError(f"max_bars must be >= 1, got {self.max_bars}")

    def trading_allowed(self, *, now: Ms, latest_bar_close: Ms, bar_ms: int) -> bool:
        """True iff a fresh bar closed within ``max_bars`` intervals of ``now``.

        ``latest_bar_close`` is the close timestamp (open + interval) of the
        newest bar available; ``bar_ms`` the bar interval. A future-stamped
        bar (clock skew) counts as fresh — staleness is the failure mode
        guarded here, skew is the ingest layer's problem.
        """
        if bar_ms <= 0:
            raise ValueError(f"bar_ms must be > 0, got {bar_ms}")
        return now - latest_bar_close <= self.max_bars * bar_ms
