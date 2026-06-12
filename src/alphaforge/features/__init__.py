"""AlphaForge feature framework — the ONE deployed path for factor computation.

Curated public surface (dataDesign.md §7; buildabilityCritique.md ruling 3.4): specs
(:class:`FeatureSpec` / :class:`Family`), the process-global registry
(:func:`default_registry`, :func:`feature`), the PIT-windowed
:class:`FeatureContext`, the dual-window :class:`FeatureEngine`
(``compute_history`` batch / ``compute_asof`` live, same function bodies), and the
anti-skew harnesses (:func:`verify_parity`, :func:`verify_truncation`).

Factor bodies live in ``alphaforge.features.library`` modules and register themselves
on import via :func:`feature`; this package itself registers only the two reference
features ``ret_log_1`` and ``close_px``.

Non-negotiables inherited by every feature: values at decision bar ``t`` are pure
functions of data available at the bar close ``t + Δ``; funding joins on
``available_at`` (never ``ts_funding``); ``lookback_bars`` derives from params; no
input mutation; batch/as-of parity is the contract (atol=0 finite-window, 1e-9
relative for the documented EWMA-family truncation convention).
"""

from alphaforge.features.context import (
    FLAG_AVAILABILITY_LAG_BARS,
    FeatureContext,
    long_series,
)
from alphaforge.features.engine import ANCHOR_TIMEFRAME, FeatureEngine
from alphaforge.features.parity import (
    EWMA_PARITY_RTOL,
    ParityReport,
    SpecParityResult,
    parity_tolerance,
    verify_parity,
    verify_truncation,
)
from alphaforge.features.registry import (
    FeatureRegistry,
    close_px,
    default_registry,
    feature,
    ret_log_1,
)
from alphaforge.features.spec import EWMA_LOOKBACK_SPANS, Family, FeatureFn, FeatureSpec

__all__ = [
    "ANCHOR_TIMEFRAME",
    "EWMA_LOOKBACK_SPANS",
    "EWMA_PARITY_RTOL",
    "FLAG_AVAILABILITY_LAG_BARS",
    "Family",
    "FeatureContext",
    "FeatureEngine",
    "FeatureFn",
    "FeatureRegistry",
    "FeatureSpec",
    "ParityReport",
    "SpecParityResult",
    "close_px",
    "default_registry",
    "feature",
    "long_series",
    "parity_tolerance",
    "ret_log_1",
    "verify_parity",
    "verify_truncation",
]
