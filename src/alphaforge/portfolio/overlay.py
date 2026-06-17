"""Volatility-targeting overlay (execDesign §6.3).

::

    sigma_hat = max( sqrt(w_opt^T Σ_ann w_opt), sigma_realized )  # conservatism: take the larger
    s         = min( sigma_target / sigma_hat, s_max )            # sigma_target=0.15, s_max=1.5
    w_final   = s · w_opt   (then re-clip so Σ|w| <= gross_max)

* ``sigma_target = 0.15`` — bottom of the 15-20% mandate band: crypto returns are
  fat-tailed so a Gaussian-calibrated 15% realizes hotter; start low, raise
  deliberately.
* ``s_max = 1.5`` prevents levering up when a quiet regime makes ex-ante vol
  deceptively small — exactly the moment vol targeting blows accounts up.
* ``sigma_realized`` is supplied by the caller: the EWMA std of realized portfolio
  per-bar returns (halflife 240 bars) x ``sqrt(calendar.periods_per_year)`` — the
  sleeve calendar's annualization basis (``8760`` for the crypto H1 sleeve, ``252`` for
  equity D1), never a hard-coded constant (SPINE_ARC §3.5). The annualization happens in
  the caller (``BlendStrategy._realized_vol_ann``); this overlay takes the already-
  annualized scalar.

Fractional Kelly note (documented here, NOT a separate mechanism): the
unconstrained MVO solution ``w* = (1/λ)Σ⁻¹μ`` *is* ``(1/λ) x full-Kelly``
(Kelly-optimal under log utility ≈ ``Σ⁻¹μ``). With λ = 7 the book is already
≈ 1/7-Kelly before constraints and this overlay bind further — comfortably
under the half-Kelly ceiling practitioners use to survive μ-estimation error.
Do NOT add a second Kelly knob; it is already in λ.
"""

from __future__ import annotations

import math

import numpy as np

__all__ = ["vol_target"]


def vol_target(
    w_opt: np.ndarray,
    cov_ann: np.ndarray,
    realized_vol_ann: float,
    target: float = 0.15,
    s_max: float = 1.5,
    gross_max: float = 1.0,
) -> tuple[np.ndarray, float]:
    """Scale the optimized book toward the annualized vol target.

    ``sigma_hat = max(ex-ante, realized)`` — the conservative estimate; then
    ``s = min(target/sigma_hat, s_max)`` and ``w_final = s·w_opt`` re-clipped so the
    scaled gross never exceeds ``gross_max`` (the overlay may de-lever past
    the optimizer's gross cap but never lever beyond it).

    Args:
        w_opt: optimized weights (fractions of equity).
        cov_ann: annualized covariance aligned with ``w_opt``.
        realized_vol_ann: annualized realized portfolio vol (EWMA std of per-bar
            portfolio returns, halflife 240 bars, x ``sqrt(calendar.periods_per_year)`` —
            ``sqrt(8760)`` for the crypto H1 sleeve); must be >= 0.
        target: annualized vol target sigma_target (default 0.15).
        s_max: scale ceiling (default 1.5) — quiet-regime leverage guard.
        gross_max: gross cap re-applied after scaling (default 1.0).

    Returns:
        ``(w_final, s)`` where ``s`` is the vol-target scale actually computed
        (the gross re-clip, when it binds, is applied on top of ``s``).

    Raises:
        ValueError: non-finite inputs, negative realized vol, or non-positive
            ``target``/``s_max``/``gross_max``.
    """
    w = np.asarray(w_opt, dtype=np.float64).ravel()
    cov = np.asarray(cov_ann, dtype=np.float64)
    n = w.shape[0]
    if cov.shape != (n, n):
        raise ValueError(f"cov_ann must be {n}x{n}, got {cov.shape}")
    if not (np.all(np.isfinite(w)) and np.all(np.isfinite(cov))):
        raise ValueError("w_opt and cov_ann must be finite (no NaN/inf)")
    if not math.isfinite(realized_vol_ann) or realized_vol_ann < 0.0:
        raise ValueError(f"realized_vol_ann must be finite and >= 0, got {realized_vol_ann!r}")
    for name, value in (("target", target), ("s_max", s_max), ("gross_max", gross_max)):
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name} must be finite and > 0, got {value!r}")

    ex_ante = math.sqrt(max(float(w @ cov @ w), 0.0))
    sigma_hat = max(ex_ante, float(realized_vol_ann))
    s = s_max if sigma_hat <= 0.0 else min(target / sigma_hat, s_max)

    w_final = s * w
    gross = float(np.abs(w_final).sum())
    if gross > gross_max:
        w_final *= gross_max / gross
    return w_final, s
