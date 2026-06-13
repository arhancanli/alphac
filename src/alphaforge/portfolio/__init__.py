"""Portfolio construction (execDesign §6): blended alpha → μ → Σ → weights → orders.

Pipeline each rebalance::

    mu_ann  (from signals; THE mu_ann contract, leakageCritique finding 2)
      → covariance.ewma_cov / ledoit_wolf_cc / nearest_psd / annualize_cov
      → RankEqualVolFallback (v1 primary) or MeanVarianceOptimizer (upgrade)
      → overlay.vol_target
      → discretize.weights_to_orders

Everything in this package is pure and deterministic: arrays/mappings in,
arrays/orders out; no I/O, no clocks, no randomness.
"""

from alphaforge.portfolio.covariance import (
    annualize_cov,
    ewma_cov,
    ledoit_wolf_cc,
    nearest_psd,
)
from alphaforge.portfolio.discretize import weights_to_orders
from alphaforge.portfolio.optimizer import (
    MU_ANN_ABS_MAX,
    MeanVarianceOptimizer,
    OptResult,
    PortfolioConstraints,
    RankEqualVolFallback,
    check_mu_ann_contract,
)
from alphaforge.portfolio.overlay import vol_target
from alphaforge.portfolio.strategy import BlendStrategy

__all__ = [
    "MU_ANN_ABS_MAX",
    "BlendStrategy",
    "MeanVarianceOptimizer",
    "OptResult",
    "PortfolioConstraints",
    "RankEqualVolFallback",
    "annualize_cov",
    "check_mu_ann_contract",
    "ewma_cov",
    "ledoit_wolf_cc",
    "nearest_psd",
    "vol_target",
    "weights_to_orders",
]
