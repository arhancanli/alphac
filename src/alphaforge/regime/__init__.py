"""Regime gate: hand-rolled Gaussian HMM gross-exposure multiplier (alphaDesign.md §8, §9.2).

Curated public surface — downstream modules import from :mod:`alphaforge.regime`,
not its submodules. The gate is a GROSS-EXPOSURE multiplier, not a signal: it emits
a scalar ``G ∈ [0.3, 1.0]`` per UTC day that the alpha layer multiplies into the
``mu_ann`` MAGNITUDE (correctness rule 3 — never a sign flip; correctness rule 5 —
the optimizer still consumes one verbatim ``mu_ann`` column).

By correctness rule 4 the multiplier on day ``D`` uses the FILTERED posterior
through day ``D-1``'s close only (no same-day leak); the Baum-Welch smoothed pass
exists for FITTING a closed historical window and never reaches a live multiplier.

* :class:`RegimeGate` — the Protocol seam Phase 12 consumes.
* :class:`RegimeHMM` — the v1 implementation (hand-rolled multi-seed Baum-Welch EM
  + forward filter; no ``hmmlearn``).
* :class:`IdentityRegime` — the OFF gate (``G ≡ 1.0``) satisfying the same seam.
* :func:`build_observations` — the daily BTC observation features.
* :class:`HMMParams` — the frozen fitted-parameter container.
"""

from alphaforge.regime.hmm import (
    COV_FLOOR,
    GATE_WEIGHTS,
    MAX_ITER,
    MIN_FIT_DAYS,
    N_SEEDS,
    RANDOM_STATE,
    TOL,
    YZ_WINDOW_DAYS,
    HMMParams,
    IdentityRegime,
    RegimeGate,
    RegimeHMM,
    build_observations,
)

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
