"""Research strategy ZOO — programmatically registered parameter-grid factors for the brutal
multiple-testing campaign (generate hundreds -> IC screen -> deflated walk-forward gauntlet).

NOT imported by the deployed factor library: ``alphaforge.features.library`` stays at its
committed canonical size (the registry-count guard in tests/integration/test_factor_invariants
keeps holding), so the zoo never touches a deployed run. The screen harness
(``scripts/zoo_screen.py``) imports this module explicitly and calls :func:`register_all`,
which adds the grid factors to ``default_registry()`` just for that process; the IC report then
screens every one. Each registered factor still flows through the SAME PIT/truncation-invariant
engine, so a zoo factor is as honest as a hand-written one — there are just a lot of them, and
the Deflated-Sharpe denominator must count ALL of them.

Grids reuse the existing parametric spec builders (``_xs_spec`` / ``_ts_spec`` etc.) so the
signal math is identical to the committed factors — only (lookback, skip, window, ...) vary.
"""

from __future__ import annotations

from alphaforge.features.library.momentum import _ts_spec, _xs_spec
from alphaforge.features.registry import FeatureRegistry, default_registry

# Cross-sectional momentum lookback x skip surface. Lookbacks span ~10 bars to ~2160 bars so the
# SAME grid is meaningful on the equity profile (D1 sessions: 21=1mo .. 252=1yr .. 1008=4yr) and
# the crypto profile (H1: 24=1d .. 168=1wk .. 720=1mo .. 2160=90d). Skips remove the most recent
# bars (1-month reversal contamination). The screen, run per-profile, interprets the bars.
_XS_LOOKBACKS = (10, 21, 42, 63, 126, 168, 252, 336, 504, 720, 1008, 1512, 2160)
_XS_SKIPS = (0, 5, 10, 21, 42, 63, 168)
_TS_LOOKBACKS = (21, 63, 126, 252, 504, 720, 1080, 2160)


def register_momentum_grid(reg: FeatureRegistry) -> int:
    """Register the XS (lookback x skip) + TS momentum grids; skip names already present."""
    have = {s.name for s in reg.all_specs()}
    n = 0
    for lookback in _XS_LOOKBACKS:
        for skip in _XS_SKIPS:
            if skip >= lookback:
                continue
            name = f"mom_xs_{lookback}_{skip}"
            if name in have:
                continue
            reg.register(lambda lookback=lookback, skip=skip: _xs_spec(lookback, skip))
            n += 1
    for lookback in _TS_LOOKBACKS:
        name = f"mom_ts_{lookback}"
        if name in have:
            continue
        reg.register(lambda lookback=lookback: _ts_spec(lookback))
        n += 1
    return n


def register_all(reg: FeatureRegistry | None = None) -> int:
    """Register every zoo grid into ``reg`` (default: the global registry). Returns the count.

    Extended as the strategy-zoo design lands (reversal / vol / liquidity / fundamental / crypto
    grids + hand-coded novel signals). Each addition raises the multiple-testing N the gauntlet
    must deflate against — that honesty is the whole point of the campaign.
    """
    reg = reg or default_registry()
    total = 0
    total += register_momentum_grid(reg)
    return total
