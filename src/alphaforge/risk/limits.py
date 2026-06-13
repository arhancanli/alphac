"""Risk limits — the entire risk posture in one frozen dataclass (execDesign §7).

One screenful, reviewable at a glance, immutable after construction. Every
hard cap the risk engine enforces lives here and ONLY here: the pre-trade
checker, the monitors, and the live loop all consume the same instance, so
backtest and live can never disagree about what "too big" means.

These are HARD limits, deliberately at-or-above the optimizer's soft caps in
``PortfolioCfg`` (the optimizer targets, the risk engine refuses): a hard-limit
trip is evidence of an upstream sizing bug, never routine drift.

Values come from :class:`~alphaforge.config.settings.RiskCfg` via
:meth:`RiskLimits.from_cfg` — config is the single source of numbers; this
class is the single source of validation and sign conventions (config stores
drawdown thresholds as NEGATIVE returns-from-HWM, the engine works in POSITIVE
drawdown fractions ``dd = 1 - E/HWM``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields

from alphaforge.config.settings import RiskCfg
from alphaforge.costs import MAX_ADV_PARTICIPATION

__all__ = ["RiskLimits"]


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskLimits:
    """Hard risk limits, all fractions of equity unless noted.

    - ``max_position_frac``: post-trade per-instrument |notional| cap.
    - ``max_gross``: post-trade gross exposure cap (sum of |notional_i|).
    - ``max_net``: post-trade |net| exposure cap (|sum of signed notional_i|).
    - ``max_order_adv_frac``: order notional <= this fraction of the
      instrument's 30d-median daily quote volume. The 1% default keeps every
      order inside the square-root impact law's validity regime (the law is
      only trustworthy for participation <~ 1%); the cost model's separate 5%
      ``CostModelMisuse`` tripwire exists to catch a BROKEN guard, never to be
      traded against — hence the construction-time assertion that this cap
      sits at or below it.
    - ``price_collar_frac``: |decision_price - close| <= frac * close, else
      the market moved since the signal was computed (stale-signal protection
      for market orders).
    - ``dd_half_frac`` / ``dd_flat_frac``: POSITIVE drawdown-from-HWM
      fractions at which gross is halved / the book is flattened and halted.
    - ``var_confidence`` / ``var_window_days``: historical VaR/CVaR
      parameters, computed on daily-aggregated returns.
    - ``staleness_max_bars``: no fresh bar within this many bar intervals of
      now => trading is forbidden for the cycle.
    """

    max_position_frac: float = 0.15
    max_gross: float = 1.0
    max_net: float = 0.5
    max_order_adv_frac: float = 0.01
    price_collar_frac: float = 0.05
    dd_half_frac: float = 0.10
    dd_flat_frac: float = 0.15
    var_confidence: float = 0.99
    var_window_days: int = 365
    staleness_max_bars: int = 2

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"RiskLimits.{f.name} must be finite, got {value!r}")
        if not 0.0 < self.max_position_frac <= self.max_gross:
            raise ValueError(
                f"require 0 < max_position_frac ({self.max_position_frac}) <= "
                f"max_gross ({self.max_gross})"
            )
        if not 0.0 <= self.max_net <= self.max_gross:
            raise ValueError(
                f"require 0 <= max_net ({self.max_net}) <= max_gross ({self.max_gross})"
            )
        if not 0.0 < self.max_order_adv_frac <= MAX_ADV_PARTICIPATION:
            raise ValueError(
                f"require 0 < max_order_adv_frac ({self.max_order_adv_frac}) <= "
                f"{MAX_ADV_PARTICIPATION} (the cost model's sqrt-law tripwire; the "
                "pre-trade cap must keep orders strictly inside the valid regime)"
            )
        if not 0.0 < self.price_collar_frac < 1.0:
            raise ValueError(f"require 0 < price_collar_frac ({self.price_collar_frac}) < 1")
        if not 0.0 < self.dd_half_frac < self.dd_flat_frac < 1.0:
            raise ValueError(
                f"require 0 < dd_half_frac ({self.dd_half_frac}) < "
                f"dd_flat_frac ({self.dd_flat_frac}) < 1"
            )
        if not 0.0 < self.var_confidence < 1.0:
            raise ValueError(f"require 0 < var_confidence ({self.var_confidence}) < 1")
        if self.var_window_days < 2:
            raise ValueError(f"require var_window_days ({self.var_window_days}) >= 2")
        if self.staleness_max_bars < 1:
            raise ValueError(f"require staleness_max_bars ({self.staleness_max_bars}) >= 1")

    @classmethod
    def from_cfg(cls, cfg: RiskCfg) -> RiskLimits:
        """Build limits from :class:`RiskCfg`, flipping the drawdown sign
        convention (config: negative return-from-HWM; engine: positive
        drawdown fraction ``dd = 1 - E/HWM``)."""
        return cls(
            max_position_frac=cfg.max_position_frac,
            max_gross=cfg.max_gross,
            max_net=cfg.max_net,
            max_order_adv_frac=cfg.max_order_adv_frac,
            price_collar_frac=cfg.price_collar_frac,
            dd_half_frac=-cfg.dd_halve_gross,
            dd_flat_frac=-cfg.dd_flat_halt,
            var_confidence=cfg.var_confidence,
            var_window_days=cfg.var_window_days,
            staleness_max_bars=cfg.staleness_max_bars,
        )
