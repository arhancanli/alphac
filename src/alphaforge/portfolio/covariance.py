"""Covariance estimation: EWMA + Ledoit-Wolf constant-correlation shrinkage (execDesign §6.1).

Pipeline per rebalance::

    S_1h    = ewma_cov(returns_1h)                  # zero-mean EWMA, bar units
    Σ, δ*   = ledoit_wolf_cc(trailing_window, S_1h)  # shrink toward constant-correlation
    Σ_psd   = nearest_psd(Σ)                         # eigenvalue clip
    Σ_ann   = annualize_cov(Σ_psd, periods_per_year) # x8760 for 1h bars

All functions are pure and deterministic: NumPy in, NumPy out, no I/O, no
randomness, no global state.

Zero-mean convention (everywhere in this module): hourly mean returns are
statistically indistinguishable from zero and estimating them only adds
variance, so second moments are computed about zero (``E[r r^T]``, not the
demeaned covariance). The Ledoit-Wolf asymptotic estimates inherit the same
convention so the shrinkage intensity is consistent with the matrix it shrinks.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "annualize_cov",
    "ewma_cov",
    "ledoit_wolf_cc",
    "nearest_psd",
]


def _as_finite_2d(name: str, a: np.ndarray) -> np.ndarray:
    """Validate ``a`` is a finite 2-D float64 array; return a float64 copy."""
    out = np.asarray(a, dtype=np.float64)
    if out.ndim != 2:
        raise ValueError(f"{name} must be 2-D, got ndim={out.ndim}")
    if not np.all(np.isfinite(out)):
        raise ValueError(f"{name} must be finite (no NaN/inf)")
    return out.copy()


def _require_square(name: str, s: np.ndarray) -> np.ndarray:
    """Validate ``s`` is a finite square matrix; return a float64 copy."""
    out = _as_finite_2d(name, s)
    if out.shape[0] != out.shape[1]:
        raise ValueError(f"{name} must be square, got shape {out.shape}")
    return out


def ewma_cov(
    returns_1h: pd.DataFrame, halflife_bars: int = 720, min_periods: int = 240
) -> np.ndarray:
    """Zero-mean EWMA covariance of hourly returns (execDesign §6.1), in bar units.

    Recursion (zero-mean: hourly means are noise, assuming 0 reduces estimator
    variance)::

        λ   = 0.5^(1/H),  H = halflife_bars
        S_0 = (1/m) X_seed^T X_seed          # zero-mean sample cov, first m = min_periods bars
        S_t = (1-λ) r_t r_t^T + λ S_{t-1}    # for every bar after the seed window

    implemented in closed form as ``S_T = λ^(T-m) S_0 + (1-λ) Σ_t λ^(T-1-t) r_t r_t^T``
    (identical to the recursion in exact arithmetic).

    Young-instrument handling (drop-and-reinsert with variance-only fallback):
    columns containing ANY non-finite value (instruments listed mid-window, data
    gaps) are dropped from the joint estimate. For each dropped column the
    variance is estimated alone as the zero-mean sample variance ``mean(r²)``
    over its finite observations (unweighted — a deliberately simple, documented
    fallback) and reinserted on the diagonal with zero covariances to every
    other asset. Cross-terms with < ``min_periods`` of joint history are not
    estimable with acceptable variance, and a zero covariance is the
    conservative shrinkage-to-independence choice.

    Args:
        returns_1h: wide TxN DataFrame of 1h simple returns (one column per
            instrument). Needs at least ``min_periods`` rows.
        halflife_bars: EWMA halflife H in bars (default 720 = 30 days;
            effective sample ≈ 2H/ln2 ≈ 2078 obs).
        min_periods: seed-window length m (default 240 = 10 days) before the
            recursion starts; also the minimum usable history.

    Returns:
        NxN covariance matrix in (1h-bar)² units, ordered as the input columns.

    Raises:
        ValueError: too few rows, invalid parameters, or a NaN column with
            fewer than 2 finite observations.
    """
    if halflife_bars <= 0:
        raise ValueError(f"halflife_bars must be > 0, got {halflife_bars}")
    if min_periods < 2:
        raise ValueError(f"min_periods must be >= 2, got {min_periods}")
    values = returns_1h.to_numpy(dtype=np.float64)
    if values.ndim != 2 or values.shape[1] == 0:
        raise ValueError(f"returns_1h must be a TxN frame with N >= 1, got shape {values.shape}")
    t_total, n = values.shape
    if t_total < min_periods:
        raise ValueError(
            f"returns_1h has {t_total} rows < min_periods={min_periods}; "
            "the EWMA covariance is not usable yet"
        )

    finite_mask = np.isfinite(values)
    full_cols = np.flatnonzero(finite_mask.all(axis=0))
    young_cols = np.flatnonzero(~finite_mask.all(axis=0))

    out = np.zeros((n, n), dtype=np.float64)

    if full_cols.size > 0:
        x = values[:, full_cols]
        lam = 0.5 ** (1.0 / float(halflife_bars))
        seed = x[:min_periods]
        s = (seed.T @ seed) / float(min_periods)  # zero-mean sample cov of the seed window
        tail = x[min_periods:]
        k = tail.shape[0]
        if k > 0:
            # Closed form: S_T = λ^k S_0 + (1-λ) Σ_{j=0..k-1} λ^(k-1-j) r_j r_j^T.
            # Row-scale by sqrt of the weights so one Gram product does the sum.
            exponents = np.arange(k - 1, -1, -1, dtype=np.float64)
            scaled = tail * np.sqrt(lam**exponents)[:, None]
            s = (lam**k) * s + (1.0 - lam) * (scaled.T @ scaled)
        out[np.ix_(full_cols, full_cols)] = 0.5 * (s + s.T)

    for col in young_cols:
        r = values[finite_mask[:, col], col]
        if r.size < 2:
            raise ValueError(
                f"column {returns_1h.columns[int(col)]!r} has {r.size} finite observations; "
                "need >= 2 for the variance-only fallback"
            )
        out[col, col] = float(np.mean(r * r))  # zero-mean sample variance

    return out


def ledoit_wolf_cc(returns_1h: np.ndarray, S: np.ndarray) -> tuple[np.ndarray, float]:
    """Constant-correlation Ledoit-Wolf shrink. Returns ``(Sigma_shrunk, delta_star)``.

    Ledoit & Wolf (2004), "Honey, I Shrunk the Sample Covariance Matrix",
    computed on the trailing ``T``-row unweighted window ``X = returns_1h``
    (T=720 in production). Using an *unweighted* window for the asymptotic
    estimates while ``S`` is the EWMA covariance is a documented approximation:
    the asymptotics assume iid observations and the unweighted window is the
    closest admissible sample; ``s_ij`` below are taken from the passed ``S``
    so the intensity is estimated for the matrix actually being shrunk.

    With ``x_ti`` the (zero-mean convention, not demeaned) returns and
    ``s_ij = S[i, j]``::

        r̄    = (2 / (N(N-1))) Σ_{i<j} s_ij / sqrt(s_ii s_jj)   # mean pairwise correlation
        F    : f_ii = s_ii ;  f_ij = r̄ sqrt(s_ii s_jj)         # shrinkage target
        π_ij = (1/T) Σ_t (x_ti x_tj - s_ij)² ;       π̂ = Σ_ij π_ij
        θ_kk,ij = (1/T) Σ_t (x_tk² - s_kk)(x_ti x_tj - s_ij)
        rho_hat    = Σ_i π_ii + Σ_{i≠j} (r̄/2) [sqrt(s_jj/s_ii) θ_ii,ij + sqrt(s_ii/s_jj) θ_jj,ij]
        gamma_hat    = Σ_ij (f_ij - s_ij)²
        δ*   = clip((π̂ - rho_hat) / (gamma_hat T), 0, 1)
        Σ_shrunk = δ* F + (1-δ*) S

    Edge cases: ``N == 1`` returns ``(S, 0.0)`` (nothing to shrink toward);
    ``gamma_hat == 0`` exactly (S already equals its target) returns ``(S, 0.0)``.

    Args:
        returns_1h: TxN finite return matrix (the unweighted trailing window).
        S: NxN covariance to shrink (typically the EWMA estimate); strictly
            positive diagonal required.

    Returns:
        ``(Sigma_shrunk, delta_star)`` with ``delta_star`` in [0, 1].
    """
    x = _as_finite_2d("returns_1h", returns_1h)
    s = _require_square("S", S)
    t_obs, n = x.shape
    if s.shape[0] != n:
        raise ValueError(f"S is {s.shape[0]}x{s.shape[0]} but returns_1h has N={n} columns")
    if t_obs < 2:
        raise ValueError(f"need T >= 2 observations, got {t_obs}")
    s = 0.5 * (s + s.T)
    diag = np.diag(s)
    if np.any(diag <= 0.0):
        raise ValueError("S must have a strictly positive diagonal")
    if n == 1:
        return s.copy(), 0.0

    d = np.sqrt(diag)
    corr = s / np.outer(d, d)
    off = ~np.eye(n, dtype=bool)
    r_bar = float(corr[off].sum()) / float(n * (n - 1))  # == (2/(N(N-1))) Σ_{i<j}

    f = r_bar * np.outer(d, d)
    np.fill_diagonal(f, diag)

    # π̂: π_ij = mean_t (x_ti x_tj)² - 2 s_ij mean_t (x_ti x_tj) + s_ij²
    x2 = x * x
    q = (x2.T @ x2) / float(t_obs)  # mean_t x_ti² x_tj²
    c = (x.T @ x) / float(t_obs)  # mean_t x_ti x_tj
    pi_mat = q - 2.0 * s * c + s * s
    pi_hat = float(pi_mat.sum())

    # θ_ii,ij = mean_t x_ti³ x_tj - s_ij m2_i - s_ii c_ij + s_ii s_ij,  m2_i = mean_t x_ti².
    b = ((x * x2).T @ x) / float(t_obs)  # b[i, j] = mean_t x_ti³ x_tj
    m2 = np.diag(c).copy()
    theta_ii = b - s * m2[:, None] - diag[:, None] * c + diag[:, None] * s
    theta_jj = b.T - s * m2[None, :] - diag[None, :] * c + diag[None, :] * s

    ratio = np.outer(1.0 / d, d)  # ratio[i, j] = sqrt(s_jj / s_ii)
    rho_hat = float(np.trace(pi_mat)) + 0.5 * r_bar * float(
        (ratio * theta_ii + ratio.T * theta_jj)[off].sum()
    )

    gamma_hat = float(((f - s) ** 2).sum())
    if gamma_hat == 0.0:
        return s.copy(), 0.0

    delta_star = float(np.clip((pi_hat - rho_hat) / (gamma_hat * float(t_obs)), 0.0, 1.0))
    sigma = delta_star * f + (1.0 - delta_star) * s
    return 0.5 * (sigma + sigma.T), delta_star


def nearest_psd(S: np.ndarray, eps_rel: float = 1e-10) -> np.ndarray:
    """Repair a near-PSD matrix by eigenvalue clipping (execDesign §6.1).

    Symmetrize, eigendecompose, clip every eigenvalue at
    ``eps = eps_rel * tr(Sigma)/N`` (a scale-aware floor: relative to the
    average variance, so the repair is invariant to units), reconstruct. A
    matrix that is already comfortably PSD passes through up to floating-point
    reconstruction error.

    Loud-failure on a degenerate trace (execDesign §10.4 safeguard 4,
    ``assert cov_ann.trace()/N > 0.001``): a covariance matrix has a strictly
    positive trace (it is a sum of variances), so ``tr(Sigma) <= 0`` can only
    mean the upstream EWMA/Ledoit-Wolf pipeline produced a corrupt matrix. The
    scale-aware floor would silently collapse such a matrix to PSD-singular
    (with ``tr(Sigma) <= 0`` the floor ``eps`` is exactly 0, so every clipped
    eigenvalue is non-negative and the result LOOKS repaired while hiding a real
    numerical failure). Per the cardinal rule, refuse rather than launder it.

    Args:
        S: square matrix (symmetrized internally).
        eps_rel: relative eigenvalue floor (default 1e-10).

    Returns:
        Symmetric PSD matrix with min eigenvalue >= eps.

    Raises:
        ValueError: when ``tr(Sigma) <= 0`` -- a corrupt covariance the
            eigenvalue floor would otherwise launder into a singular matrix.
    """
    a = _require_square("S", S)
    a = 0.5 * (a + a.T)
    n = a.shape[0]
    trace = float(np.trace(a))
    if trace <= 0.0:
        raise ValueError(
            f"nearest_psd: tr(Sigma) = {trace:.6g} <= 0 for an {n}x{n} matrix; a "
            "covariance has strictly positive trace, so this signals a corrupt "
            "EWMA/Ledoit-Wolf estimate. Refusing to clip it to a singular matrix "
            "(the scale-aware eigenvalue floor would silently swallow the failure)."
        )
    eps = eps_rel * trace / float(n)
    eigvals, eigvecs = np.linalg.eigh(a)
    clipped = np.maximum(eigvals, eps)
    out = (eigvecs * clipped[None, :]) @ eigvecs.T
    return np.asarray(0.5 * (out + out.T), dtype=np.float64)


def annualize_cov(cov_bar: np.ndarray, periods_per_year: float) -> np.ndarray:
    """Scale a per-bar covariance to annual units: ``Σ_ann = Σ_bar x periods_per_year``.

    For 1h bars on a 24/7 calendar ``periods_per_year`` is 8760
    (``Timeframe.H1.bars_per_year`` — always take it from the calendar, never
    hard-code).
    """
    if not np.isfinite(periods_per_year) or periods_per_year <= 0.0:
        raise ValueError(f"periods_per_year must be finite and > 0, got {periods_per_year!r}")
    return np.asarray(_require_square("cov_bar", cov_bar) * float(periods_per_year))
