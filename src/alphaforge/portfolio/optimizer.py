"""Portfolio allocators: rank/inverse-vol primary + mean-variance upgrade (execDesign §6.2).

Two allocators share one ``solve()`` signature and one :class:`OptResult`:

* :class:`RankEqualVolFallback` — THE v1 primary allocator (buildability
  ruling §1): rank by ``mu_ann``, long top K / short bottom K, inverse-vol
  weights at half gross. It ships *first* and runs a full paper-trading phase
  so that when the MVO arrives as a drop-in upgrade, its degraded mode is
  already battle-tested. At G_max=1.0, w_max=0.15, turnover cap 0.10 the
  constrained MVO and this book are similar anyway — the upgrade is real but
  not blocking.
* :class:`MeanVarianceOptimizer` — the cvxpy mean-variance problem (Clarabel,
  OSQP fallback) that delegates to :class:`RankEqualVolFallback` whenever the
  solver fails, returns non-finite weights, or produces an implausible ex-ante
  vol (``status == "fallback_used"``).

The mu_ann contract (leakageCritique finding 2)
-----------------------------------------------

The alpha layer emits **annualized** expected returns::

    mu_ann = mu_h x (8760 / h),   h = settings.signals.horizon_bars

and this module consumes them verbatim. The boundary tripwire
:func:`check_mu_ann_contract` refuses a SYSTEMATIC scaling error by its effect on
the MEDIAN ``|mu_ann|`` (a per-h return passed raw, or a per-bar return annualized
twice, inflates every name ~72x and is caught here instead of silently producing a
maximally-levered book); rare honest extreme-vol tails are winsorized to the 3.0
ceiling (:func:`winsorize_mu_ann`) rather than refused. The holding period ``h``
lives in exactly ONE settings
field (``signals.horizon_bars``) consumed by both the signal layer and the
cost-amortization factor ``A = 8760/h`` below (buildability finding 3.10) —
never duplicate it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Self, cast

import cvxpy as cp
import numpy as np
from cvxpy.atoms.affine.sum import sum as cvx_sum
from cvxpy.atoms.affine.wraps import psd_wrap
from cvxpy.atoms.elementwise.abs import abs as cvx_abs
from cvxpy.atoms.norm1 import norm1
from cvxpy.atoms.quad_form import quad_form

from alphaforge.core.time import Timeframe
from alphaforge.portfolio.covariance import nearest_psd

if TYPE_CHECKING:
    from alphaforge.config.settings import Settings

__all__ = [
    "MU_ANN_ABS_MAX",
    "MU_ANN_SYSTEMATIC_MEDIAN_MAX",
    "MeanVarianceOptimizer",
    "OptResult",
    "PortfolioConstraints",
    "RankEqualVolFallback",
    "check_mu_ann_contract",
    "winsorize_mu_ann",
]

#: Winsorization ceiling on the mu_ann contract: 300% annualized expected
#: return per asset. The linear-in-sigma Grinold mu (mu ∝ sigma·score) genuinely
#: overshoots in extreme-vol tails — a coin doing 650%+ annualized vol with a
#: strong signal score produces |mu_ann| up to ~4.3 (verified on real history:
#: median |mu_ann|≈0.20, p99.9≈2.0, with rare single-name tails beyond 3). Such
#: a name maxes out ``w_max`` whether mu is 3.0 or 4.3, so clipping the tail to
#: this ceiling is economically neutral and keeps the QP well-conditioned.
MU_ANN_ABS_MAX: Final[float] = 3.0

#: The finding-2 unit-bug tripwire, detected on the MEDIAN |mu_ann|. A SYSTEMATIC
#: scaling error (a raw per-h return, or a double annualization — both ~72-121x
#: too large) multiplies EVERY name, so the median itself explodes (~0.2 -> ~14).
#: A legitimate market-wide vol spike (LUNA/FTX: many alts at 650%+ annualized vol
#: at once) inflates only the TAIL while the median stays sane (real 6y history:
#: median ~0.15-0.20 even in the worst crash window, with up to ~5% of names in
#: the >3 tail). So the median is the correct discriminator — a fraction-of-tail
#: check false-trips on a crash (it killed the first 6y run at 4.8% tail / median
#: 0.148). Set equal to the per-name ceiling: if the MEDIAN reaches 300% annual,
#: the whole distribution is broken. That is ~15x the real median (0.2) yet ~5x
#: below any real ~72x bug (~14) — enormous separation either way — while a uniform
#: large-but-honest alpha (e.g. a 2-asset basis trade) is not mistaken for a bug.
#: Tail values are winsorized to the ceiling regardless of count (economically
#: neutral; w_max already binds).
MU_ANN_SYSTEMATIC_MEDIAN_MAX: Final[float] = MU_ANN_ABS_MAX

#: Ex-ante annualized portfolio vol above this is implausible for a gross<=1
#: crypto book and indicates a broken covariance/solver -> fallback engages.
_EX_ANTE_VOL_MAX: Final[float] = 5.0

#: Annualization factor for 1h bars (from the calendar, never hard-coded).
_PERIODS_PER_YEAR: Final[float] = Timeframe.H1.bars_per_year

#: Statuses accepted from cvxpy as a usable solution.
_OK_STATUSES: Final[frozenset[str]] = frozenset({cp.OPTIMAL, cp.OPTIMAL_INACCURATE})


def check_mu_ann_contract(mu_ann: np.ndarray) -> None:
    """Refuse expected returns that violate the mu_ann contract (finding 2).

    The signal layer MUST emit ``mu_ann = mu_h * 8760 / h`` (annualized). A
    SYSTEMATIC units bug — a raw per-h return treated as annual, or a double
    annualization (both ~72-121x too large) — multiplies EVERY name, so the
    MEDIAN ``|mu_ann|`` explodes (~0.2 -> ~14). So the violation is detected on
    the median, not on the tail: a legitimate market-wide vol spike (LUNA/FTX:
    many alts at 650%+ annualized vol at once) inflates only the tail while the
    median stays sane (real 6y history: median ~0.15-0.20 even in the worst
    crash, with up to ~5% of names beyond the ceiling). A fraction-of-tail check
    false-trips on exactly that crash regime (it killed the first 6y run at 4.8%
    tail / median 0.148); the median separates a real ~72x bug from an honest
    crash tail with ~10x margin either way. Tail values that pass this check are
    winsorized to the ceiling downstream (see :func:`winsorize_mu_ann`), which is
    economically neutral because ``w_max`` already binds for any such name.

    Raises:
        ValueError: when the median ``|mu_ann|`` exceeds
            ``MU_ANN_SYSTEMATIC_MEDIAN_MAX`` — a systematic scaling error that
            inflated the whole distribution, not a crash-driven tail.
    """
    if mu_ann.size == 0:
        return
    finite = mu_ann[np.isfinite(mu_ann)]
    if finite.size == 0:
        return
    abs_mu = np.abs(finite)
    median = float(np.median(abs_mu))
    if median > MU_ANN_SYSTEMATIC_MEDIAN_MAX:
        worst = float(abs_mu.max())
        frac = float((abs_mu >= MU_ANN_ABS_MAX).mean())
        raise ValueError(
            f"mu_ann contract violated: median |mu_ann| = {median:.3f} exceeds "
            f"{MU_ANN_SYSTEMATIC_MEDIAN_MAX} ({frac:.1%} of names >= {MU_ANN_ABS_MAX}, "
            f"max = {worst:.4f}). A systematic scaling error inflated the WHOLE "
            "distribution — signals must emit mu_ann = mu_h * 8760/h with "
            "h = settings.signals.horizon_bars (leakageCritique finding 2); a raw "
            "per-horizon return or a double annualization lands here. Refusing to size."
        )


def winsorize_mu_ann(mu_ann: np.ndarray) -> tuple[np.ndarray, int]:
    """Clip mu_ann into ``[-MU_ANN_ABS_MAX, +MU_ANN_ABS_MAX]`` (module + ceiling docstrings).

    Returns the clipped array and the count of clipped entries. Applied AFTER
    :func:`check_mu_ann_contract` has ruled out a systematic error, so any clip
    here is a rare honest extreme-vol tail (economically neutral — ``w_max``
    binds). NaNs pass through unchanged.
    """
    clipped = np.clip(mu_ann, -MU_ANN_ABS_MAX, MU_ANN_ABS_MAX)
    n_clipped = int(np.sum(np.abs(mu_ann) > MU_ANN_ABS_MAX))
    return clipped, n_clipped


@dataclass(frozen=True)
class PortfolioConstraints:
    """Optimizer soft caps, fractions of equity (risk engine holds looser hard caps)."""

    gross_max: float = 1.0
    net_max: float = 0.5
    w_max: float = 0.15
    turnover_max: float = 0.10

    def __post_init__(self) -> None:
        for name in ("gross_max", "net_max", "w_max", "turnover_max"):
            value = float(getattr(self, name))
            if not np.isfinite(value) or value <= 0.0:
                raise ValueError(f"PortfolioConstraints.{name} must be finite and > 0")
        if self.w_max > self.gross_max:
            raise ValueError(f"w_max ({self.w_max}) must be <= gross_max ({self.gross_max})")

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        """Build from the single ``portfolio`` config section."""
        p = settings.portfolio
        return cls(
            gross_max=p.gross_max,
            net_max=p.net_max,
            w_max=p.w_max,
            turnover_max=p.turnover_max,
        )


@dataclass(frozen=True, eq=False)
class OptResult:
    """One allocator decision.

    ``weights`` is aligned with the input arrays (array-in/array-out: naming
    happens at the discretize boundary via :meth:`to_targets`). ``status`` is
    ``"optimal"`` (solver solution) or ``"fallback_used"`` (rank/inverse-vol
    book — degraded mode when reached via the MVO, normal mode when the
    fallback is the configured primary allocator). ``objective`` is the value
    of the allocator's own objective at ``weights`` (the MVO objective for the
    solver; the expected annualized book return ``mu_ann @ w`` for the
    rank/inverse-vol allocator, which has no risk-aversion/amortization knobs).
    """

    weights: np.ndarray
    status: str
    ex_ante_vol_ann: float
    objective: float

    def to_targets(self, instrument_ids: Sequence[str]) -> dict[str, float]:
        """Zip weights with instrument ids (the input order) for discretization."""
        if len(instrument_ids) != self.weights.shape[0]:
            raise ValueError(
                f"got {len(instrument_ids)} instrument_ids for {self.weights.shape[0]} weights"
            )
        return {iid: float(w) for iid, w in zip(instrument_ids, self.weights, strict=True)}


def _validate_inputs(
    mu_ann: np.ndarray,
    cov_ann: np.ndarray,
    w_prev: np.ndarray,
    cost_frac_oneway: np.ndarray,
    shortable: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Shared validation: shapes agree, everything finite, costs >= 0, tripwire."""
    mu = np.asarray(mu_ann, dtype=np.float64).ravel()
    n = mu.shape[0]
    if n == 0:
        raise ValueError("mu_ann is empty: nothing to allocate")
    cov = np.asarray(cov_ann, dtype=np.float64)
    if cov.shape != (n, n):
        raise ValueError(f"cov_ann must be {n}x{n}, got {cov.shape}")
    prev = np.asarray(w_prev, dtype=np.float64).ravel()
    cost = np.asarray(cost_frac_oneway, dtype=np.float64).ravel()
    short = np.asarray(shortable, dtype=np.float64).ravel()
    for name, arr in (("w_prev", prev), ("cost_frac_oneway", cost), ("shortable", short)):
        if arr.shape[0] != n:
            raise ValueError(f"{name} must have length {n}, got {arr.shape[0]}")
    for name, arr in (
        ("mu_ann", mu),
        ("cov_ann", cov),
        ("w_prev", prev),
        ("cost_frac_oneway", cost),
        ("shortable", short),
    ):
        if not np.all(np.isfinite(arr)):
            raise ValueError(f"{name} must be finite (no NaN/inf)")
    if np.any(cost < 0.0):
        raise ValueError("cost_frac_oneway must be >= 0")
    if not np.all((short == 0.0) | (short == 1.0)):
        raise ValueError("shortable must contain only 0/1 (or booleans)")
    check_mu_ann_contract(mu)  # raises on a SYSTEMATIC units bug
    mu, _ = winsorize_mu_ann(mu)  # clip rare honest tails (economically neutral)
    return mu, cov, prev, cost, short


class RankEqualVolFallback:
    """Rank + inverse-vol allocator — the v1 PRIMARY (buildability §1) and the MVO fallback.

    Why primary-first: it has no solver, no conditioning sensitivity, and only
    two free choices (K and the gross level), so it can run a full
    paper-trading phase while the MVO is still being proven. When the MVO
    ships, this exact class becomes its degraded mode — already battle-tested.

    Algorithm (execDesign §6.2 fallback spec):

    1. Rank assets by ``mu_ann`` descending. Long top K, short bottom K,
       ``K = min(10, ⌊N/4⌋)``. Shorts only where ``shortable`` (non-shortable
       shorts are dropped, finding 22 — perps only in v1, so normally all 1).
    2. ``w_i ∝ sign_i / sigma_ann,i`` (inverse-vol from ``diag(cov_ann)``),
       normalized so ``Σ|w_i| = 0.5 · gross_max`` — half gross, deliberately
       conservative because when reached via the MVO we are in a degraded mode.
    3. Clip at ``±w_max``, then renormalize back toward half gross, capped so
       no weight re-exceeds ``w_max`` (scale = min(target/gross, w_max/max|w|)).

    Deterministic: ties in ``mu_ann`` are broken by input position
    (stable argsort). ``w_prev`` and ``cost_frac_oneway`` are validated but do
    not influence the book (this allocator never trades off turnover).
    """

    def __init__(self, constraints: PortfolioConstraints | None = None) -> None:
        self.constraints = constraints if constraints is not None else PortfolioConstraints()

    def solve(
        self,
        mu_ann: np.ndarray,
        cov_ann: np.ndarray,
        w_prev: np.ndarray,
        cost_frac_oneway: np.ndarray,
        shortable: np.ndarray,
    ) -> OptResult:
        """Build the rank/inverse-vol book. Always succeeds (no solver).

        Returns:
            :class:`OptResult` with ``status="fallback_used"`` and
            ``objective = mu_ann @ w`` (expected annualized book return —
            this allocator has no risk/cost terms; see :class:`OptResult`).
        """
        mu, cov, _prev, _cost, short = _validate_inputs(
            mu_ann, cov_ann, w_prev, cost_frac_oneway, shortable
        )
        n = mu.shape[0]
        c = self.constraints
        k = min(10, n // 4)
        weights = np.zeros(n, dtype=np.float64)
        if k > 0:
            order = np.argsort(-mu, kind="stable")
            sign = np.zeros(n, dtype=np.float64)
            sign[order[:k]] = 1.0
            short_legs = order[n - k :]
            sign[short_legs] = np.where(short[short_legs] == 1.0, -1.0, 0.0)

            active = sign != 0.0
            sigma = np.sqrt(np.clip(np.diag(cov), 0.0, None))
            if np.any(active & ~(sigma > 0.0)):
                raise ValueError(
                    "cov_ann has a non-positive variance for a selected asset; "
                    "inverse-vol weights are undefined"
                )
            weights[active] = sign[active] / sigma[active]
            target_gross = 0.5 * c.gross_max
            gross = float(np.abs(weights).sum())
            if gross > 0.0:
                weights *= target_gross / gross
                weights = np.clip(weights, -c.w_max, c.w_max)
                gross_clipped = float(np.abs(weights).sum())
                max_abs = float(np.abs(weights).max())
                if gross_clipped > 0.0 and max_abs > 0.0:
                    weights *= min(target_gross / gross_clipped, c.w_max / max_abs)

        ex_ante = float(np.sqrt(max(weights @ cov @ weights, 0.0)))
        return OptResult(
            weights=weights,
            status="fallback_used",
            ex_ante_vol_ann=ex_ante,
            objective=float(mu @ weights),
        )


class MeanVarianceOptimizer:
    """Mean-variance optimizer with turnover costs (execDesign §6.2 — the exact problem).

    ::

        maximize_w   mu_ann^T w - (λ/2) w^T Σ_ann w - A · Σ_i c_i |w_i - w̃_i|
        subject to   Σ|w_i| <= gross_max
                     |Σ w_i| <= net_max
                     -w_max·shortable_i <= w_i <= w_max
                     Σ|w_i - w̃_i| <= turnover_max

    * ``λ = risk_aversion = 7.0``: unconstrained MVO has ex-ante vol
      ``SR_implied/λ``; a believed gross Sharpe ≈ 1.0 at target vol 0.15 gives
      λ ≈ 6.7 → 7. μ and Σ must be annualized *together* (they are: §6.1 + the
      mu_ann contract), making λ invariant to the unit choice.
    * ``A = 8760 / holding_bars``: a one-shot cost ``c_i`` is paid against
      alpha accruing over the holding period h, so on the annualized footing it
      is amortized at trades-per-year. ``holding_bars`` MUST be
      ``settings.signals.horizon_bars`` (h = 72; A ≈ 121.7) — the ONE shared
      horizon constant (buildability finding 3.10); use :meth:`from_settings`.
    * Solver: Clarabel, then OSQP; on failure / non-finite weights /
      implausible ex-ante vol the solve delegates to
      :class:`RankEqualVolFallback` and flags ``status="fallback_used"``.
    """

    def __init__(
        self,
        risk_aversion: float = 7.0,
        *,
        holding_bars: int,
        constraints: PortfolioConstraints | None = None,
        solver: str = "CLARABEL",
    ) -> None:
        if not np.isfinite(risk_aversion) or risk_aversion <= 0.0:
            raise ValueError(f"risk_aversion must be finite and > 0, got {risk_aversion!r}")
        if holding_bars <= 0:
            raise ValueError(f"holding_bars must be > 0, got {holding_bars!r}")
        if solver not in ("CLARABEL", "OSQP"):
            raise ValueError(f"solver must be 'CLARABEL' or 'OSQP', got {solver!r}")
        self.risk_aversion = float(risk_aversion)
        self.holding_bars = int(holding_bars)
        self.constraints = constraints if constraints is not None else PortfolioConstraints()
        self.solver = solver
        self._fallback = RankEqualVolFallback(self.constraints)

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        """The blessed constructor: risk_aversion + caps from ``portfolio``,
        ``holding_bars`` from ``signals.horizon_bars`` — the single shared
        horizon constant (h = alpha horizon = cost-amortization horizon)."""
        return cls(
            risk_aversion=settings.portfolio.risk_aversion,
            holding_bars=settings.signals.horizon_bars,
            constraints=PortfolioConstraints.from_settings(settings),
        )

    @property
    def cost_amortization(self) -> float:
        """``A = 8760 / holding_bars`` — annualized turnover-cost multiplier."""
        return _PERIODS_PER_YEAR / float(self.holding_bars)

    def solve(
        self,
        mu_ann: np.ndarray,
        cov_ann: np.ndarray,
        w_prev: np.ndarray,
        cost_frac_oneway: np.ndarray,
        shortable: np.ndarray,
    ) -> OptResult:
        """Solve the MVO above; delegate to the rank/inverse-vol fallback on failure.

        Args:
            mu_ann: annualized expected returns (the mu_ann contract — tripwire
                enforced, see :func:`check_mu_ann_contract`).
            cov_ann: annualized covariance (PSD-repaired internally).
            w_prev: current drifted weights ``w̃`` from ledger marks.
            cost_frac_oneway: per-asset one-way cost fraction
                (``TransactionCostModel.oneway_cost_frac`` at the typical trade
                size — fee + half-spread + impact, NO latency).
            shortable: 0/1 per asset (1 = may go short; perps only in v1).

        Returns:
            :class:`OptResult`; ``status`` is ``"optimal"`` when the solver
            produced a usable book, else ``"fallback_used"``.

        Raises:
            ValueError: malformed inputs or mu_ann contract violation (these
                are caller bugs, never silently routed to the fallback).
        """
        mu, cov, prev, cost, short = _validate_inputs(
            mu_ann, cov_ann, w_prev, cost_frac_oneway, shortable
        )
        cov_psd = nearest_psd(cov)
        weights = self._solve_cvxpy(mu, cov_psd, prev, cost, short)
        if weights is not None:
            ex_ante = float(np.sqrt(max(weights @ cov_psd @ weights, 0.0)))
            if np.isfinite(ex_ante) and ex_ante <= _EX_ANTE_VOL_MAX:
                objective = float(
                    mu @ weights
                    - 0.5 * self.risk_aversion * (weights @ cov_psd @ weights)
                    - self.cost_amortization * (cost @ np.abs(weights - prev))
                )
                return OptResult(
                    weights=weights,
                    status="optimal",
                    ex_ante_vol_ann=ex_ante,
                    objective=objective,
                )
        return self._fallback.solve(mu, cov_psd, prev, cost, short)

    def _solve_cvxpy(
        self,
        mu: np.ndarray,
        cov_psd: np.ndarray,
        prev: np.ndarray,
        cost: np.ndarray,
        short: np.ndarray,
    ) -> np.ndarray | None:
        """Run cvxpy (primary solver, then the other); None on any failure."""
        n = mu.shape[0]
        c = self.constraints
        w = cp.Variable(n)
        trade = cvx_abs(w - prev)
        objective = cp.Maximize(
            mu @ w
            - 0.5 * self.risk_aversion * quad_form(w, psd_wrap(cov_psd))
            - self.cost_amortization * (cost @ trade)
        )
        constraints = [
            norm1(w) <= c.gross_max,
            cvx_abs(cvx_sum(w)) <= c.net_max,
            w <= c.w_max,
            w >= -c.w_max * short,
            cvx_sum(trade) <= c.turnover_max,
        ]
        problem = cp.Problem(objective, constraints)
        solvers = (self.solver, "OSQP" if self.solver == "CLARABEL" else "CLARABEL")
        solve = cast("Callable[..., object]", problem.solve)  # cvxpy's solve() is untyped
        for solver in solvers:
            try:
                solve(solver=solver)
            except (cp.SolverError, cp.DCPError, ValueError, ArithmeticError):
                continue
            if problem.status in _OK_STATUSES and w.value is not None:
                values = np.asarray(w.value, dtype=np.float64).ravel()
                if values.shape[0] == n and bool(np.all(np.isfinite(values))):
                    return values
        return None
