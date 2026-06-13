"""Signal blending and sizing — the alpha→portfolio seam (alphaDesign.md §9).

Three modules, one contract:

* :mod:`alphaforge.signals.blending` — EWMA Rank-IC blend weights on the
  non-overlapping h-grid (realized labels only; κ floor per leakage finding 19)
  and the blend ``Ã = cs_zscore(Σ_k w_k z_k)``.
* :mod:`alphaforge.signals.sizing` — Grinold rule to the ANNUALIZED expected
  return ``mu_ann = IC_target·sigma_hat·sqrt(h)·F̃ · (8760/h)`` — THE μ contract of
  leakage finding 2; the optimizer consumes the ``mu_ann`` column verbatim.
* :mod:`alphaforge.signals.service` — :class:`SignalService`, the one seam class
  research (``compute_research``) and live (``on_bar_close``) both consume,
  with batch≡live parity as the deployed contract.

``h`` is ``SignalsCfg.horizon_bars`` everywhere — the ONE holding-period
constant (buildabilityCritique.md §3.10).
"""

from alphaforge.signals.blending import (
    ALPHA_BLEND_COLUMN,
    BLEND_EWMA_HALFLIFE_GRID,
    KAPPA_FLOOR,
    KAPPA_SHRINK,
    BlendWeights,
    blend,
    estimate_blend_weights,
)
from alphaforge.signals.service import SIGMA_COLUMN, SignalService
from alphaforge.signals.sizing import MU_ANN_COLUMN, GrinoldSizer

__all__ = [
    "ALPHA_BLEND_COLUMN",
    "BLEND_EWMA_HALFLIFE_GRID",
    "KAPPA_FLOOR",
    "KAPPA_SHRINK",
    "MU_ANN_COLUMN",
    "SIGMA_COLUMN",
    "BlendWeights",
    "GrinoldSizer",
    "SignalService",
    "blend",
    "estimate_blend_weights",
]
