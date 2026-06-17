"""Hand-rolled Gaussian HMM regime gate (alphaDesign.md §8, §9.2).

This module is a **gross-exposure gate, not a signal**. Its single job is to emit a
scalar multiplier ``G ∈ [0.3, 1.0]`` per UTC calendar day that the alpha layer
multiplies into the already-formed ``mu_ann`` magnitude (§9.2)::

    mu_ann_{i,t} = IC_target · sigmâ_{i,t}·sqrt(h) · F̃_{i,t} · G_d

where ``d`` is the UTC day containing hour-bar ``t``. By **correctness rule 3** the
gate NEVER flips a sign — ``G ≥ 0.3 > 0`` always, it shrinks the magnitude only. By
**correctness rule 5** it does not touch the μ contract: the gate is applied INSIDE
the alpha layer, so the optimizer still consumes a single verbatim ``mu_ann`` column.
The HMM observes **daily** market state; the gate is broadcast to all 24 hourly
decision bars of a day.

Timing (correctness rule 4 / leakageCritique finding 13) is the load-bearing
property: the multiplier applied on day ``D`` is the FILTERED posterior computed from
observations available strictly BEFORE day ``D`` — i.e. through day ``D-1``'s close
and using NO observation from day ``D`` itself. The forward filter
(:meth:`RegimeHMM.filtered_probs`) is the ONLY recursion whose output reaches ``G``;
the Baum-Welch backward pass exists for FITTING only (a closed historical window) and
its smoothed posteriors never touch a live multiplier.

Platform constraint (this build): **no ``hmmlearn``** — the forward filter and the
multi-seed Baum-Welch EM are hand-rolled here. ``hmmlearn`` has no ``n_init``, so the
multi-seed restart loop (finding 13) is implemented explicitly. Emission densities are
evaluated in log space (:func:`scipy.stats.multivariate_normal.logpdf` per state, then
:func:`scipy.special.logsumexp` for normalizers) — never raw products of densities,
which underflow over ~2500 days. scipy carries stubs in this environment (see
:mod:`alphaforge.validation.dsr`).

The model is fitted offline (monthly); live inference is a cheap forward pass. It
persists nothing: :meth:`RegimeHMM.fit` returns ``self`` with :attr:`RegimeHMM.params`
set, and the caller (live loop / walk-forward runner) owns the frozen
:class:`HMMParams` and the refit cadence.

This module never mutates its input frame.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.special import logsumexp
from scipy.stats import multivariate_normal

from alphaforge.core.time import Timeframe, available_at
from alphaforge.features.library.vol import yang_zhang

__all__ = [
    "COV_FLOOR",
    "GATE_WEIGHTS",
    "MAX_ITER",
    "MIN_FIT_DAYS",
    "N_SEEDS",
    "RANDOM_STATE",
    "TOL",
    "YZ_WINDOW_DAYS",
    "HMMParams",
    "IdentityRegime",
    "RegimeGate",
    "RegimeHMM",
    "build_observations",
]

_LOG = logging.getLogger(__name__)

MIN_FIT_DAYS: Final[int] = 730
"""Minimum daily observations the HMM will fit on (§8 expanding window, ≈2y)."""

YZ_WINDOW_DAYS: Final[int] = 14
"""Yang-Zhang window on DAILY bars for the vol observation ``v_d`` (§1)."""

RANDOM_STATE: Final[int] = 42
"""Master seed; per-seed child seeds derive deterministically (finding 13)."""

N_SEEDS: Final[int] = 10
"""Multi-seed Baum-Welch restarts; the best-loglik fit wins (no hmmlearn n_init)."""

MAX_ITER: Final[int] = 300
"""EM iteration cap per seed."""

TOL: Final[float] = 1e-4
"""EM convergence tolerance on the loglik increment."""

COV_FLOOR: Final[float] = 1e-6
"""Diagonal floor added to every covariance each M-step (anti-collapse)."""

GATE_WEIGHTS: Final[dict[int, tuple[float, ...]]] = {2: (1.0, 0.3), 3: (1.0, 0.7, 0.3)}
"""Per-(vol-sorted)-state gross multiplier, DESCENDING (low-vol state gets 1.0)."""

_N_FEATURES: Final[int] = 2
"""Observation dimensionality: ``[m_d, v_d]``."""

_OBS_COLUMNS: Final[tuple[str, str]] = ("m", "v")
"""The two observation columns consumed by the model."""

_AVAILABLE_AT: Final[str] = "available_at"
"""Point-in-time stamp column on the observation / gate frames (epoch-ms day close)."""

type _F64 = npt.NDArray[np.float64]
"""Module-internal shorthand for a float64 ndarray (keeps EM signatures legible)."""


# --------------------------------------------------------------------------- seam


@runtime_checkable
class RegimeGate(Protocol):
    """The seam the alpha layer depends on: days -> daily gross multiplier.

    :mod:`alphaforge.regime.hmm` ships :class:`RegimeHMM`; :class:`IdentityRegime`
    (constant ``1.0``) and any future model satisfy the same Protocol so the signal
    path never imports the HMM concretely (mirrors
    :class:`alphaforge.backtest.fills.FillModel` and
    :class:`alphaforge.execution.paper.OrderBookSource`).

    The returned Series is keyed by epoch-ms ``ts_open`` (the UTC day the gate
    APPLIES TO) and is lagged so that the value at day ``D`` originated from
    observations available strictly before day ``D`` (``lag_days`` days, default 1).
    Everything is epoch-ms :data:`alphaforge.core.time.Ms`; never a ``DatetimeIndex``.
    """

    def gross_multiplier_series(self, obs: pd.DataFrame, *, lag_days: int = 1) -> pd.Series:
        """Lagged daily gross multiplier in ``[0.3, 1.0]`` keyed by day-``D`` ts_open."""
        ...


# --------------------------------------------------------------- observation builder


def build_observations(daily_btc: pd.DataFrame) -> pd.DataFrame:
    """Daily HMM observation frame ``[m, v]`` from a BTC daily OHLC panel (§1).

    The two observations per UTC day ``d`` (alphaDesign.md §8)::

        m_d = ln(C_d / C_{d-1})                              # daily log return
        v_d = ln( yang_zhang(BTC OHLC, window=14, annualize) )  # ln 14d YZ vol

    ``m_d`` uses the daily close panel; ``v_d`` reuses the ONE sanctioned vol
    estimator :func:`alphaforge.features.library.vol.yang_zhang` (do NOT
    re-implement vol) — 14-day window on daily bars, ``annualize=True`` for
    cross-refit comparability of the logged state means (any positive scaling is
    absorbed by the Gaussian means). ``ln(·)`` brings the heavy-tailed vol toward
    normality (§8).

    Each ``x_d`` is available at ``available_at(ts_open_d, Timeframe.D1)`` = day-``d``
    close = ``00:00`` of day ``d+1`` — the linchpin of the §4 timing rule, stamped in
    the ``available_at`` column and computed with :func:`core.time.available_at`,
    never by hand.

    Parameters
    ----------
    daily_btc:
        Daily BTC OHLC panel with columns ``open``, ``high``, ``low``, ``close``,
        indexed by ``ts_open`` (epoch-ms UTC int64, 1d-aligned). One row per day;
        a partial day (a gap) must NOT be present — like
        :mod:`alphaforge.labeling.forward_returns`, gaps are never bridged.

    Returns
    -------
    pd.DataFrame
        Indexed by ``ts_open`` (int64); float64 columns ``m`` (daily log return),
        ``v`` (ln 14d annualized YZ vol), and an int64 ``available_at`` column
        (= day close). Leading warm-up NaN rows (14d YZ warm-up + the one-bar gap
        return) and any interior gap-NaN row are dropped; raises ``ValueError`` if
        fewer than :data:`MIN_FIT_DAYS` finite rows remain.
    """
    required = {"open", "high", "low", "close"}
    missing = required - set(daily_btc.columns)
    if missing:
        raise ValueError(f"daily_btc is missing required columns: {sorted(missing)}")
    if not pd.api.types.is_integer_dtype(daily_btc.index):
        raise TypeError(
            f"daily_btc index must be int64 epoch-ms ts_open; got dtype {daily_btc.index.dtype}"
        )
    ordered = daily_btc.sort_index()
    if ordered.index.duplicated().any():
        raise ValueError("daily_btc contains duplicate ts_open rows")

    ts = ordered.index.to_numpy(dtype=np.int64)
    # yang_zhang consumes the sanctioned WIDE layout (one column per instrument); a
    # single-column frame is the BTC panel. annualize=True only for legibility.
    one = pd.DataFrame
    close = one(ordered["close"].to_numpy(dtype=float), index=ts, columns=["btc"])
    open_ = one(ordered["open"].to_numpy(dtype=float), index=ts, columns=["btc"])
    high = one(ordered["high"].to_numpy(dtype=float), index=ts, columns=["btc"])
    low = one(ordered["low"].to_numpy(dtype=float), index=ts, columns=["btc"])

    with np.errstate(divide="ignore", invalid="ignore"):
        m = np.log(close["btc"].to_numpy() / np.roll(close["btc"].to_numpy(), 1))
    m[0] = np.nan  # the roll wraps the last close to position 0 — never a real return
    yz = yang_zhang(open_, high, low, close, window=YZ_WINDOW_DAYS, annualize=True)["btc"]
    with np.errstate(divide="ignore", invalid="ignore"):
        v = np.log(yz.to_numpy(dtype=float))

    # available_at(ts_open, D1) = ts_open + D1.ms (core.time contract); vectorized in
    # exact int64 over the whole column — the per-row helper proves the identity.
    assert available_at(0, Timeframe.D1) == Timeframe.D1.ms  # contract tripwire
    avail = ts + np.int64(Timeframe.D1.ms)
    frame = pd.DataFrame(
        {
            _OBS_COLUMNS[0]: m,
            _OBS_COLUMNS[1]: v,
            _AVAILABLE_AT: avail,
        },
        index=pd.Index(ts, name="ts_open"),
    )
    # Drop warm-up + interior gaps: a non-finite m or v means the day is not usable.
    finite = np.isfinite(frame[_OBS_COLUMNS[0]].to_numpy()) & np.isfinite(
        frame[_OBS_COLUMNS[1]].to_numpy()
    )
    frame = frame.loc[finite]
    if len(frame) < MIN_FIT_DAYS:
        raise ValueError(
            f"need >= {MIN_FIT_DAYS} finite daily observations to fit the HMM; got {len(frame)}"
        )
    frame[_AVAILABLE_AT] = frame[_AVAILABLE_AT].astype(np.int64)
    result: pd.DataFrame = frame.copy()
    return result


# ------------------------------------------------------------------ params value obj


@dataclass(frozen=True, slots=True, kw_only=True)
class HMMParams:
    """Frozen, vol-sorted HMM parameters (state index 0 = lowest log-vol).

    All arrays are float64 and C-contiguous. ``n_states`` ``K`` ∈ {2, 3};
    ``start_prob`` ``(K,)`` sums to 1; ``trans_mat`` ``(K, K)`` each row sums to 1
    (``A[j, k] = P(s_t = k | s_{t-1} = j)``); ``means`` ``(K, 2)``; ``covs``
    ``(K, 2, 2)`` SPD; ``loglik`` = winning-seed data log-likelihood; ``n_obs`` = fit
    length; ``seed`` = winning seed index. States are pre-sorted by ascending
    ``means[:, 1]`` (mean of ``v_d = ln sigma``), so state identity is pinned by
    volatility, not by EM's arbitrary labeling.
    """

    n_states: int
    start_prob: npt.NDArray[np.float64]
    trans_mat: npt.NDArray[np.float64]
    means: npt.NDArray[np.float64]
    covs: npt.NDArray[np.float64]
    loglik: float
    n_obs: int
    seed: int


# ---------------------------------------------------------------- internal EM kernel


def _log_emissions(
    x: _F64,
    means: _F64,
    covs: _F64,
) -> _F64:
    """``log_b[t, k] = logpdf(x_t; means_k, covs_k)`` — emission log-likelihoods.

    Shape ``(T, K)``. Computed in log space per state via
    :func:`scipy.stats.multivariate_normal.logpdf` (never raw densities; underflow).
    ``allow_singular=False`` so a degenerate covariance surfaces loudly rather than
    silently producing a meaningless ``+inf`` density.
    """
    n_states = means.shape[0]
    out = np.empty((x.shape[0], n_states), dtype=np.float64)
    for k in range(n_states):
        out[:, k] = multivariate_normal.logpdf(x, mean=means[k], cov=covs[k], allow_singular=False)
    return out


def _forward_filter(
    log_b: _F64,
    log_pi: _F64,
    trans: _F64,
) -> tuple[_F64, _F64, float]:
    """Scaled forward recursion (§2.1) — FILTERED posteriors, no backward pass.

    Returns ``(filt, log_c, loglik)`` where ``filt[t, k] = P(s_t = k | x_{1:t})``
    (each row sums to 1), ``log_c[t]`` is the per-step log normalizer, and
    ``loglik = Σ_t log_c[t]`` is the data log-likelihood. Works in the normalized
    (filtered) domain so the recursion stays bounded over thousands of days.
    """
    n_obs, n_states = log_b.shape
    filt = np.empty((n_obs, n_states), dtype=np.float64)
    log_c = np.empty(n_obs, dtype=np.float64)

    log_alpha0 = log_pi + log_b[0]
    log_c[0] = float(logsumexp(log_alpha0))
    filt[0] = np.exp(log_alpha0 - log_c[0])
    for t in range(1, n_obs):
        pred = filt[t - 1] @ trans  # one-step-ahead prior P(s_t | x_{1:t-1})
        with np.errstate(divide="ignore"):
            log_alpha = np.log(pred) + log_b[t]
        log_c[t] = float(logsumexp(log_alpha))
        filt[t] = np.exp(log_alpha - log_c[t])
    loglik = float(np.sum(log_c))
    return filt, log_c, loglik


def _backward(
    log_b: _F64,
    trans: _F64,
    log_c: _F64,
) -> _F64:
    """Scaled backward recursion (FIT ONLY) sharing the forward ``log_c`` scalers.

    Returns ``beta[t, k]`` with ``beta[T-1] = 1`` and
    ``beta[t] = (trans @ (b_{t+1} ⊙ beta_{t+1})) / c_{t+1}``. The backward pass is
    permissible HERE because fitting runs on a closed historical window and its
    output (the params) is frozen and applied forward-only; ``beta`` never reaches a
    live multiplier.
    """
    n_obs, n_states = log_b.shape
    beta = np.empty((n_obs, n_states), dtype=np.float64)
    beta[-1] = 1.0
    for t in range(n_obs - 2, -1, -1):
        weighted = np.exp(log_b[t + 1] - log_c[t + 1]) * beta[t + 1]
        beta[t] = trans @ weighted
    return beta


def _kmeanspp_means(x: npt.NDArray[np.float64], n_states: int, rng: np.random.Generator) -> _F64:
    """k-means++-style pick of ``n_states`` observation rows as initial means.

    The first centre is a uniform random row; each subsequent centre is drawn with
    probability ∝ squared distance to the nearest chosen centre — the standard
    spread-out initialization, giving well-separated seeds without an extra dep.
    """
    n_obs = x.shape[0]
    first = int(rng.integers(n_obs))
    centres = [x[first]]
    for _ in range(1, n_states):
        dist_sq = np.min(np.stack([np.sum((x - c) ** 2, axis=1) for c in centres], axis=0), axis=0)
        total = float(dist_sq.sum())
        if total <= 0.0:  # all points coincide with a centre — fall back to uniform
            idx = int(rng.integers(n_obs))
        else:
            idx = int(rng.choice(n_obs, p=dist_sq / total))
        centres.append(x[idx])
    return np.asarray(centres, dtype=np.float64)


def _init_params(
    x: npt.NDArray[np.float64], n_states: int, rng: np.random.Generator
) -> tuple[_F64, _F64, _F64, _F64]:
    """Seed ``(pi, trans, means, covs)``: uniform π, diagonal-heavy A, global Σ.

    ``trans`` is diagonal-heavy (``0.9`` self-transition) to reflect sticky regimes;
    ``means`` from :func:`_kmeanspp_means`; every ``covs[k]`` starts at the global
    sample covariance (plus the diagonal floor), guaranteeing SPD from iteration 0.
    """
    pi = np.full(n_states, 1.0 / n_states, dtype=np.float64)
    off = (1.0 - 0.9) / (n_states - 1)
    trans = np.full((n_states, n_states), off, dtype=np.float64)
    np.fill_diagonal(trans, 0.9)
    means = _kmeanspp_means(x, n_states, rng)
    global_cov = np.cov(x, rowvar=False, ddof=1) + COV_FLOOR * np.eye(_N_FEATURES)
    covs = np.repeat(global_cov[np.newaxis, :, :], n_states, axis=0).astype(np.float64)
    return pi, trans, means, covs


def _baum_welch_once(
    x: _F64,
    n_states: int,
    rng: np.random.Generator,
    *,
    max_iter: int,
    tol: float,
) -> tuple[_F64, _F64, _F64, _F64, float]:
    """One EM run from a random seed; returns ``(pi, trans, means, covs, loglik)``.

    Standard scaled forward-backward + M-step (§2.2). Converges when the loglik
    increment drops below ``tol`` or ``max_iter`` is hit. The M-step re-estimates
    ``pi = gamma_0``, the transition matrix from the normalized joints ``ξ``, and the
    Gaussian means/covariances from the smoothed posteriors ``gamma`` — with
    :data:`COV_FLOOR` added to every covariance diagonal to prevent the classic
    single-point collapse of Gaussian EM.
    """
    pi, trans, means, covs = _init_params(x, n_states, rng)
    n_obs = x.shape[0]
    prev_loglik = -np.inf
    loglik = -np.inf
    for _ in range(max_iter):
        log_b = _log_emissions(x, means, covs)
        with np.errstate(divide="ignore"):
            log_pi = np.log(pi)
        filt, log_c, loglik = _forward_filter(log_b, log_pi, trans)
        beta = _backward(log_b, trans, log_c)

        # E-step posteriors.
        gamma = filt * beta
        gamma /= gamma.sum(axis=1, keepdims=True)

        # Joints ξ_t(j,k) ∝ filt_{t-1}(j)·A[j,k]·b_t(k)·beta_t(k), normalized per t.
        trans_num = np.zeros((n_states, n_states), dtype=np.float64)
        for t in range(1, n_obs):
            b_beta = np.exp(log_b[t] - log_c[t]) * beta[t]  # (K,)
            xi = (filt[t - 1][:, None] * trans) * b_beta[None, :]
            xi /= xi.sum()
            trans_num += xi

        # M-step.
        pi = gamma[0].copy()
        denom = gamma[:-1].sum(axis=0)
        trans = trans_num / denom[:, None]
        trans /= trans.sum(axis=1, keepdims=True)
        weights = gamma.sum(axis=0)
        means = (gamma.T @ x) / weights[:, None]
        covs = np.empty((n_states, _N_FEATURES, _N_FEATURES), dtype=np.float64)
        for k in range(n_states):
            centred = x - means[k]
            cov_k = (gamma[:, k][:, None] * centred).T @ centred / weights[k]
            covs[k] = cov_k + COV_FLOOR * np.eye(_N_FEATURES)

        if loglik - prev_loglik < tol:
            break
        prev_loglik = loglik
    return pi, trans, means, covs, loglik


def _sort_by_vol(
    pi: _F64,
    trans: _F64,
    means: _F64,
    covs: _F64,
) -> tuple[_F64, _F64, _F64, _F64]:
    """Relabel states by ascending mean log-vol ``means[:, 1]`` (§2.3).

    Ties on equal vol means break by DESCENDING mean return ``means[:, 0]``. The
    permutation is applied to ``pi``, ``trans`` (rows AND columns), ``means`` and
    ``covs`` so the stored params are canonical vol-ascending — state identity is
    pinned by vol on every refit, no cross-refit matching needed for the gate.
    """
    order = np.lexsort((-means[:, 0], means[:, 1]))
    return (
        pi[order].copy(),
        trans[np.ix_(order, order)].copy(),
        means[order].copy(),
        covs[order].copy(),
    )


# ----------------------------------------------------------------------- the model


class RegimeHMM:
    """Hand-rolled ``K``-state Gaussian HMM on ``[BTC daily ret, ln 14d YZ vol]``.

    Multi-seed Baum-Welch fit, FILTERED (forward-only) live inference, vol-ascending
    state identity, gross-exposure gate. Satisfies :class:`RegimeGate`.

    No ``hmmlearn`` (platform constraint). Persists nothing: :meth:`fit` returns
    ``self`` with :attr:`params` set; callers freeze/store :attr:`params` for the
    monthly refit cadence. The gate NEVER flips a sign and never leaks same-day data
    (§4).
    """

    def __init__(
        self,
        n_states: int = 3,
        *,
        random_state: int = RANDOM_STATE,
        n_seeds: int = N_SEEDS,
        max_iter: int = MAX_ITER,
        tol: float = TOL,
        gate_weights: tuple[float, ...] | None = None,
    ) -> None:
        """Configure the HMM; nothing is fitted until :meth:`fit` is called.

        ``n_states`` must be in ``{2, 3}``. ``gate_weights`` defaults to
        :data:`GATE_WEIGHTS`\\ ``[n_states]``; its length must equal ``n_states``, it
        must be DESCENDING (the low-vol state gets the largest multiplier), and every
        weight must lie in ``[0, 1]``.
        """
        if n_states not in (2, 3):
            raise ValueError(f"n_states must be in {{2, 3}}; got {n_states}")
        if n_seeds < 1:
            raise ValueError(f"n_seeds must be >= 1; got {n_seeds}")
        if max_iter < 1:
            raise ValueError(f"max_iter must be >= 1; got {max_iter}")
        weights = GATE_WEIGHTS[n_states] if gate_weights is None else gate_weights
        if len(weights) != n_states:
            raise ValueError(
                f"gate_weights must have length n_states={n_states}; got {len(weights)}"
            )
        if not all(0.0 <= w <= 1.0 for w in weights):
            raise ValueError(f"gate_weights must lie in [0, 1]; got {weights}")
        if any(weights[i] < weights[i + 1] for i in range(len(weights) - 1)):
            raise ValueError(
                f"gate_weights must be DESCENDING (low-vol state largest); got {weights}"
            )
        self._n_states = n_states
        self._random_state = random_state
        self._n_seeds = n_seeds
        self._max_iter = max_iter
        self._tol = tol
        self._gate_weights = np.asarray(weights, dtype=np.float64)
        self._params: HMMParams | None = None

    @property
    def n_states(self) -> int:
        """Number of hidden states ``K`` ∈ {2, 3}."""
        return self._n_states

    @property
    def gate_weights(self) -> npt.NDArray[np.float64]:
        """Per-(vol-sorted)-state multiplier vector, descending, in ``[0, 1]``."""
        return self._gate_weights

    @property
    def params(self) -> HMMParams:
        """The fitted, vol-sorted :class:`HMMParams`; raises if :meth:`fit` not run."""
        if self._params is None:
            raise RuntimeError("RegimeHMM is not fitted; call fit() first")
        return self._params

    @staticmethod
    def _extract(obs: pd.DataFrame) -> _F64:
        """The ``(T, 2)`` ``[m, v]`` observation matrix from ``obs``; never mutates it.

        Raises ``ValueError`` if the ``m``/``v`` columns are absent — the model only
        ever consumes the two sanctioned observation columns (the ``available_at``
        stamp is a join key, not a feature).
        """
        missing = set(_OBS_COLUMNS) - set(obs.columns)
        if missing:
            raise ValueError(f"obs is missing observation columns: {sorted(missing)}")
        return obs.loc[:, list(_OBS_COLUMNS)].to_numpy(dtype=np.float64, copy=True)

    def fit(self, obs: pd.DataFrame) -> RegimeHMM:
        """Multi-seed Baum-Welch on ``obs[['m', 'v']]``; store vol-sorted params.

        Runs :data:`N_SEEDS` independent EM fits from deterministic per-seed RNGs
        (``np.random.default_rng(random_state)`` → child seeds), keeps the highest
        final-loglik fit, relabels states by ascending mean ``v`` (§2.3), and stores
        the result in :attr:`params`. Returns ``self``.

        Raises ``ValueError`` if ``obs`` has fewer than :data:`MIN_FIT_DAYS` rows or
        contains any non-finite ``m``/``v`` value (a malformed observation must never
        reach the EM).
        """
        x = self._extract(obs)
        if x.shape[0] < MIN_FIT_DAYS:
            raise ValueError(f"need >= {MIN_FIT_DAYS} observations to fit; got {x.shape[0]}")
        if not np.all(np.isfinite(x)):
            raise ValueError("obs contains non-finite m/v values; clean gaps before fit")

        seed_seq = np.random.SeedSequence(self._random_state)
        child_seeds = seed_seq.spawn(self._n_seeds)
        best: (
            tuple[
                npt.NDArray[np.float64],
                npt.NDArray[np.float64],
                npt.NDArray[np.float64],
                npt.NDArray[np.float64],
                float,
            ]
            | None
        ) = None
        best_seed = -1
        for seed_idx, child in enumerate(child_seeds):
            rng = np.random.default_rng(child)
            result = _baum_welch_once(
                x, self._n_states, rng, max_iter=self._max_iter, tol=self._tol
            )
            _LOG.debug("seed %d final loglik %.6f", seed_idx, result[4])
            if best is None or result[4] > best[4]:
                best = result
                best_seed = seed_idx
        assert best is not None  # n_seeds >= 1 guaranteed by __init__
        pi, trans, means, covs, loglik = best
        pi, trans, means, covs = _sort_by_vol(pi, trans, means, covs)
        _LOG.debug("chosen seed %d loglik %.6f", best_seed, loglik)
        self._params = HMMParams(
            n_states=self._n_states,
            start_prob=np.ascontiguousarray(pi),
            trans_mat=np.ascontiguousarray(trans),
            means=np.ascontiguousarray(means),
            covs=np.ascontiguousarray(covs),
            loglik=loglik,
            n_obs=x.shape[0],
            seed=best_seed,
        )
        return self

    def filtered_probs(self, obs: pd.DataFrame) -> pd.DataFrame:
        """Forward-only ``P(s_d = k | x_{1:d})`` per day (§2.1) — NO smoothing.

        Columns ``state_0 .. state_{K-1}`` (vol-ascending), indexed by ``obs.index``
        (``ts_open``). Uses :attr:`params`; a pure forward filter, so row ``d`` uses
        observations ``0..d`` ONLY — deleting ``d+1:`` leaves row ``d`` unchanged
        (the leak-regression invariant). A smoothed posterior would NOT have this
        property.
        """
        params = self.params
        x = self._extract(obs)
        log_b = _log_emissions(x, params.means, params.covs)
        with np.errstate(divide="ignore"):
            log_pi = np.log(params.start_prob)
        filt, _, _ = _forward_filter(log_b, log_pi, params.trans_mat)
        columns = [f"state_{k}" for k in range(self._n_states)]
        return pd.DataFrame(filt, index=obs.index, columns=columns)

    def gross_multiplier(self, probs: pd.DataFrame) -> pd.Series:
        """``G_d = Σ_k probs[state_k]·g_k`` — posterior-weighted blend (§2.3).

        Indexed by ``probs.index``; every value lies in
        ``[min(gate_weights), max(gate_weights)] = [0.3, 1.0]`` because it is a
        convex combination of the weights (rows of ``probs`` sum to 1). Strictly
        positive — correctness rule 3 (the gate never flips a sign).
        """
        values = probs.to_numpy(dtype=float) @ self._gate_weights
        return pd.Series(values, index=probs.index, name="regime_gate")

    def gross_multiplier_series(self, obs: pd.DataFrame, *, lag_days: int = 1) -> pd.Series:
        """END-TO-END GATE WITH THE TIMING LAG (§4) — the :class:`RegimeGate` seam.

        Returns a Series indexed by the day-``D`` ``ts_open`` the gate APPLIES TO,
        whose value is the filtered multiplier computed from observations available
        strictly BEFORE day ``D`` — i.e. through day ``D - lag_days``'s close. The
        lag lives HERE and ONLY here (leakageCritique finding 4: no double
        application): the value at day ``D`` is ``blend(filt_{D-lag_days})``, obtained
        by shifting the un-lagged multiplier forward by ``lag_days`` rows. The first
        ``lag_days`` days (cold start) get ``G = 1.0`` (no gate yet) — never NaN.

        ``lag_days`` must be ``>= 1``; ``lag_days = 0`` is rejected — it would gate
        day ``D`` with ``filt_D``, which bakes in day-``D``'s own return and vol (a
        same-day leak). The Phase-12 hourly join is a single backward
        :func:`pandas.merge_asof` keyed on the day-``D`` ``ts_open`` (NOT on
        ``available_at``), so the lag is applied exactly once.
        """
        if lag_days < 1:
            raise ValueError(
                f"lag_days must be >= 1 (lag_days=0 leaks same-day data); got {lag_days}"
            )
        probs = self.filtered_probs(obs)
        raw = self.gross_multiplier(probs)
        gate = raw.shift(lag_days)
        max_g = float(self._gate_weights.max())
        filled = gate.fillna(max_g)  # cold start: no gate yet -> permissive max (1.0)
        filled.name = "regime_gate"
        return filled


# ------------------------------------------------------------------- identity gate


@dataclass(frozen=True, slots=True)
class IdentityRegime:
    """A no-op :class:`RegimeGate` that returns ``1.0`` for every requested day.

    Used as the default gate so the regime layer is opt-in: with
    :class:`IdentityRegime` the alpha layer's ``mu_ann`` is byte-identical to the
    un-gated path (the OFF==today regression guard). Also the documented cold-start /
    insufficient-data fallback for early walk-forward legs (finding 14).
    """

    def gross_multiplier_series(self, obs: pd.DataFrame, *, lag_days: int = 1) -> pd.Series:
        """Constant ``1.0`` indexed by ``obs.index`` (``lag_days`` is irrelevant)."""
        if lag_days < 1:
            raise ValueError(f"lag_days must be >= 1; got {lag_days}")
        return pd.Series(1.0, index=obs.index, name="regime_gate", dtype="float64")
