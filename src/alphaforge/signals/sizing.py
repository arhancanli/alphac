"""Grinold sizing — Ã to the expected-return vector ``mu_ann`` (alphaDesign.md §9.2).

THE μ CONTRACT (leakage finding 2 — read before touching anything here)
========================================================================
The alpha layer (B) and the portfolio layer (C) disagreed on μ units in the
original designs, a silent 72x position-scaling error. The ruling:

* This module emits **``mu_ann``** — the ANNUALIZED expected return::

      mu_h_{i,t}   = IC_target · sigma_hat_{i,t} · sqrt(h) · F̃_{i,t}          (Grinold rule)
      mu_ann_{i,t} = mu_h_{i,t} · (bars_per_year / h)                 (= ·8760/72 for 1h)

* The output column/Series is literally named ``mu_ann`` (:data:`MU_ANN_COLUMN`).
* The optimizer consumes it VERBATIM (no re-annualization) and refuses to run
  when ``np.abs(mu_ann).max() >= 3.0`` — a 300%-annualized per-name alpha means
  the units are wrong, not that the alpha is great.
* ``h`` comes from the ONE shared settings field ``SignalsCfg.horizon_bars``
  (buildabilityCritique.md §3.10: alpha horizon == cost-amortization holding
  period == purge-gap floor; never duplicated as a second constant).

Term definitions
================
* ``IC_target = 0.02`` (``SignalsCfg.ic_target``): deliberately conservative
  realized-RankIC assumption for mid-frequency crypto; recalibrated quarterly to
  trailing realized IC, never bumped to make a backtest look better.
* ``sigma_hat_{i,t}``: PER-BAR EWMA volatility at the decision bar (span 168, zero-mean —
  the ONE sanctioned implementation,
  :func:`alphaforge.features.library.vol.ewma_vol`). ``sigma_hat·sqrt(h)`` is the h-bar
  horizon volatility, so ``mu_h`` is "IC_target horizon-sigmas of edge, scaled by
  the standardized signal".
* ``F̃_{i,t}``: the final cross-sectionally standardized signal. **v1: F̃ = Ã**
  (the blend from :mod:`alphaforge.signals.blending`) — there is NO ML
  meta-model gate and NO HMM regime gate yet. Future hooks, in design order
  (alphaDesign.md §5.3, §8): ``F = Ã·|size_meta|`` (the meta-model scales,
  never flips) re-standardized to ``F̃``, and a gross multiplier ``G_t`` from the
  filtered (never smoothed) HMM posterior. Both arrive as explicit factors in
  the formula above; nothing else in this module changes.

Pure and deterministic; inputs are never mutated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from alphaforge.config.settings import SignalsCfg
from alphaforge.core.time import Timeframe

__all__ = ["MU_ANN_COLUMN", "GrinoldSizer"]

MU_ANN_COLUMN: Final[str] = "mu_ann"
"""THE output column name (leakage finding 2). The optimizer keys on this name;
renaming it is a contract break caught by the B→C boundary test."""


@dataclass(frozen=True, slots=True, kw_only=True)
class GrinoldSizer:
    """Maps the standardized signal F̃ and per-bar sigma_hat to ``mu_ann`` (module docstring).

    ``horizon_bars`` must be ``SignalsCfg.horizon_bars`` — construct via
    :meth:`from_cfg` so the ONE shared horizon constant is consumed, not retyped.
    """

    ic_target: float = 0.02
    horizon_bars: int
    timeframe: Timeframe = Timeframe.H1

    def __post_init__(self) -> None:
        if not (0.0 < self.ic_target < 1.0):
            raise ValueError(f"ic_target must be in (0, 1); got {self.ic_target}")
        if self.horizon_bars <= 0:
            raise ValueError(f"horizon_bars must be > 0; got {self.horizon_bars}")

    @classmethod
    def from_cfg(cls, cfg: SignalsCfg, *, timeframe: Timeframe = Timeframe.H1) -> GrinoldSizer:
        """Build from settings — the sanctioned constructor: ``ic_target`` and the
        ONE horizon constant both come from ``SignalsCfg`` (finding 2 / §3.10)."""
        return cls(ic_target=cfg.ic_target, horizon_bars=cfg.horizon_bars, timeframe=timeframe)

    @property
    def annualization(self) -> float:
        """``bars_per_year / h`` — the horizon-μ → mu_ann factor (8760/72 for 1h/72)."""
        return self.timeframe.bars_per_year / self.horizon_bars

    def mu_ann(self, alpha_tilde: pd.Series, sigma_bar: pd.Series) -> pd.Series:
        """The Grinold expected-return vector, ANNUALIZED (finding 2)::

            mu_h   = ic_target · sigma_hat · sqrt(h) · F̃        F̃ = alpha_tilde (v1: = Ã)
            mu_ann = mu_h · (bars_per_year / h)

        ``alpha_tilde``: the standardized signal F̃; ``sigma_bar``: PER-BAR EWMA sigma_hat
        at the decision bar, aligned by index (``sigma_bar`` is reindexed to
        ``alpha_tilde.index``). Non-positive or missing sigma_hat — and NaN F̃ — yield NaN
        (an instrument without a trusted vol estimate gets no expected return,
        never a zero that the optimizer would read as "certified flat").

        Returns a float Series named ``"mu_ann"`` aligned to ``alpha_tilde.index``.
        """
        sigma = sigma_bar.reindex(alpha_tilde.index).to_numpy(dtype=float, copy=True)
        sigma[~(sigma > 0.0)] = np.nan
        mu_h = (
            self.ic_target
            * sigma
            * np.sqrt(float(self.horizon_bars))
            * alpha_tilde.to_numpy(dtype=float)
        )
        return pd.Series(
            mu_h * self.annualization, index=alpha_tilde.index, name=MU_ANN_COLUMN, dtype=float
        )
