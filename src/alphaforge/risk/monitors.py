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
    threshold lookup — history matters (hysteresis, absorbing cooldown).

    Definitions: ``HWM_t = max(HWM_{t-1}, E_t)`` (while not halted),
    ``DD_t = 1 - E_t / HWM_t`` (positive fraction).

    Transitions on :meth:`update` (one call == one bar):

    - NORMAL    --(DD >= dd_half_frac)--> HALF_GROSS
    - any live  --(DD >= dd_flat_frac)--> FLAT_HALTED  (resets the halt counter)
    - HALF_GROSS --(DD < 0.75 * dd_half_frac)--> NORMAL — recovery requires
      retracing to 75% of the trigger (hysteresis: oscillation around the
      threshold must not flap gross sizing on/off every bar).
    - FLAT_HALTED --(flat_cooldown_bars updates elapsed)--> NORMAL — TIME-BASED
      AUTO-REARM (see below).

    Why FLAT_HALTED auto-rearms on a TIMER, not on recovery
    -------------------------------------------------------
    A full halt FLATTENS the book (``gross_multiplier() == 0``). A flat book
    marks no positions, so its equity FREEZES: it can never recover on its
    own, and a recovery-based exit could therefore NEVER fire. In any
    UNATTENDED run (a multi-year walk-forward backtest OR the 24/7 paper loop)
    a recovery- or manual-only exit means the strategy permanently DIES at the
    first 15% drawdown and sits flat in cash forever. The fix: FLAT_HALTED is
    absorbing for exactly ``flat_cooldown_bars`` :meth:`update` calls after
    entry, then AUTO-REARMS — identically in backtest and live.

    During the cooldown the halt keeps every absorbing invariant: equity is
    still marked, but ``gross_multiplier() == 0``, the HWM is FROZEN, and
    intra-cooldown equity recoveries are IGNORED (no transition, no flapping).

    On the update where bars-in-halt REACHES ``flat_cooldown_bars`` the ladder
    auto-rearms: state -> NORMAL, **HWM RESETS to the current equity** (NOT the
    old pre-drawdown HWM — otherwise drawdown is still <= -15% and it would
    re-halt on the very next bar), drawdown -> 0, halt counter -> 0,
    :attr:`n_auto_rearms` += 1. The strategy then resumes from a fresh
    high-water mark. Resetting HWM to current equity is DELIBERATE: in a
    sustained downtrend the ladder ratchets — halt -> cooldown -> resume ->
    (maybe) halt again — bounded in frequency by ``flat_cooldown_bars``. That
    bounded re-halting is correct always-on behavior and strictly better than
    permanent death.

    HWM updates ONLY in NORMAL/HALF_GROSS and is FROZEN while halted: the
    book is flat, so post-halt equity drift is noise/funding, and letting it
    raise the bar would manufacture phantom drawdown.

    Manual vs auto rearm
    --------------------
    :meth:`rearm` is the IMMEDIATE manual override (CLI ``alphaforge arm
    --confirm`` / the KillSwitch human path) — it does not wait for the
    cooldown. Auto-rearm is the unattended default; manual rearm is the
    operator override. The :class:`~alphaforge.risk.KillSwitch` (execDesign
    §7.3, a SEPARATE class) remains the ABSORBING manual halt that requires a
    human to clear; this ladder cooldown only governs the ladder's own
    self-recovery, leaving the kill-switch as the human-in-the-loop brake.

    HALF_GROSS is unaffected by the cooldown: its book still trades at 0.5x, so
    equity genuinely recovers and the existing ``dd < 0.75 * dd_half_frac``
    hysteresis release works. Only FLAT_HALTED needed a timer.

    :meth:`gross_multiplier` is what the sizing layer consumes:
    1.0 / 0.5 / 0.0 for NORMAL / HALF_GROSS / FLAT_HALTED.
    """

    __slots__ = (
        "_dd_flat",
        "_dd_half",
        "_flat_cooldown_bars",
        "_halt_bars",
        "_hwm",
        "_last_equity",
        "_n_auto_rearms",
        "_release",
        "_state",
    )

    #: HALF_GROSS releases to NORMAL only below this fraction of dd_half_frac.
    RELEASE_FRAC: float = 0.75

    def __init__(
        self,
        *,
        dd_half_frac: float = 0.10,
        dd_flat_frac: float = 0.15,
        flat_cooldown_bars: int = 336,
    ) -> None:
        """Build the ladder.

        ``flat_cooldown_bars`` (>0) is the number of :meth:`update` calls
        FLAT_HALTED stays absorbing before auto-rearming. The default 336 (14
        days of 1h bars) MATCHES ``RiskCfg.flat_cooldown_bars`` /
        ``configs/base.yaml`` so the ladder behaves identically whether or not
        the caller threads the config value through (the existing
        ``DrawdownLadder(dd_half_frac=..., dd_flat_frac=...)`` call site keeps
        the default until it is wired to pass ``r.flat_cooldown_bars``).
        """
        if not 0.0 < dd_half_frac < dd_flat_frac < 1.0:
            raise ValueError(
                f"require 0 < dd_half_frac ({dd_half_frac}) < dd_flat_frac ({dd_flat_frac}) < 1"
            )
        if flat_cooldown_bars <= 0:
            raise ValueError(f"flat_cooldown_bars must be > 0, got {flat_cooldown_bars!r}")
        self._dd_half = dd_half_frac
        self._dd_flat = dd_flat_frac
        self._flat_cooldown_bars = flat_cooldown_bars
        self._release = self.RELEASE_FRAC * dd_half_frac
        self._hwm = math.nan
        self._last_equity = math.nan
        self._state = DDState.NORMAL
        self._halt_bars = 0
        self._n_auto_rearms = 0

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

    @property
    def bars_in_halt(self) -> int:
        """Number of :meth:`update` calls elapsed in the CURRENT FLAT_HALTED
        spell (0 whenever not halted). Diagnostic: the walk-forward and
        ``af paper status`` read this to show "halted N/flat_cooldown_bars
        bars" progress toward the auto-rearm."""
        return self._halt_bars

    @property
    def n_auto_rearms(self) -> int:
        """Count of TIME-BASED auto-rearms so far (manual :meth:`rearm` calls
        are NOT counted). Observability signal: a large value over a run flags
        a chronic ratcheting downtrend rather than a single excursion."""
        return self._n_auto_rearms

    def gross_multiplier(self) -> float:
        """Sizing multiplier the portfolio layer applies: 1.0 / 0.5 / 0.0."""
        if self._state is DDState.NORMAL:
            return 1.0
        if self._state is DDState.HALF_GROSS:
            return 0.5
        return 0.0

    def update(self, equity: float) -> DDState:
        """Mark equity, advance the state machine, return the new state.

        One call == one bar. While FLAT_HALTED the call is absorbing (HWM
        frozen, no transition) for the FIRST ``flat_cooldown_bars`` calls after
        entry; the call that makes bars-in-halt REACH ``flat_cooldown_bars``
        auto-rearms to NORMAL with HWM reset to ``equity`` (see class
        docstring). Equity recoveries within the cooldown are ignored.
        """
        if not math.isfinite(equity) or equity <= 0.0:
            raise ValueError(f"equity must be finite and > 0, got {equity!r}")
        self._last_equity = equity
        if self._state is DDState.FLAT_HALTED:
            # Absorbing during cooldown: HWM frozen, equity recoveries ignored.
            self._halt_bars += 1
            if self._halt_bars >= self._flat_cooldown_bars:
                # Time-based auto-rearm: fresh HWM at current equity so the
                # ladder does not re-halt instantly on the residual drawdown.
                self._hwm = equity
                self._state = DDState.NORMAL
                self._halt_bars = 0
                self._n_auto_rearms += 1
            return self._state
        self._hwm = equity if math.isnan(self._hwm) else max(self._hwm, equity)
        dd = 1.0 - equity / self._hwm
        if dd >= self._dd_flat:
            self._state = DDState.FLAT_HALTED
            self._halt_bars = 0  # entering halt: start the cooldown clock fresh
        elif self._state is DDState.NORMAL:
            if dd >= self._dd_half:
                self._state = DDState.HALF_GROSS
        elif dd < self._release:  # HALF_GROSS, hysteresis release
            self._state = DDState.NORMAL
        return self._state

    def rearm(self) -> None:
        """IMMEDIATE manual exit from FLAT_HALTED (operator/KillSwitch path):
        state -> NORMAL and HWM resets to the last marked equity, else the
        ladder would re-trip on the very next update; the halt counter is
        cleared. This is the human override that does NOT wait for the
        time-based cooldown auto-rearm (the unattended default in
        :meth:`update`). Raises ``RuntimeError`` if not halted — rearming a
        live ladder is operator error, not a no-op."""
        if self._state is not DDState.FLAT_HALTED:
            raise RuntimeError(f"rearm() is only valid in FLAT_HALTED, state is {self._state}")
        if math.isnan(self._last_equity):
            raise RuntimeError("rearm() before any equity update")
        self._hwm = self._last_equity
        self._state = DDState.NORMAL
        self._halt_bars = 0


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
