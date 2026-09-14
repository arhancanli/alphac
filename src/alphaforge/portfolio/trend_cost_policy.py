"""Immutable, dated cost scenarios for the opt-in walk-forward trend gate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from alphaforge.portfolio.optimizer import check_mu_ann_contract, winsorize_mu_ann


@dataclass(frozen=True)
class TrendCostRow:
    instrument_id: str
    side: str
    start_ms: int
    end_ms: int
    known_ms: int
    round_trip_fraction: float
    source: str


@dataclass(frozen=True)
class TrendCostPolicy:
    rows: tuple[TrendCostRow, ...]
    basis: str  # explicit modeled scenario or sourced observation; never inferred
    allocation_mode: str = "filter_then_allocate"

    def __post_init__(self):
        if (
            type(self.rows) is not tuple
            or not self.rows
            or self.basis not in {"modeled", "observed"}
            or self.allocation_mode not in {"filter_then_allocate", "retain_cash"}
        ):
            raise ValueError("Immutable rows and explicit cost basis required")
        for row in self.rows:
            if not isinstance(row, TrendCostRow):
                raise ValueError("Typed cost rows required")
            if (
                not row.instrument_id
                or not row.source
                or row.side not in {"long", "short"}
                or any(type(t) is not int for t in (row.start_ms, row.end_ms, row.known_ms))
                or not 0 <= row.known_ms <= row.start_ms < row.end_ms
                or not np.isfinite(row.round_trip_fraction)
                or row.round_trip_fraction < 0
            ):
                raise ValueError("Invalid dated cost evidence")
        for i, row in enumerate(self.rows):
            for other in self.rows[:i]:
                if (row.instrument_id, row.side) == (other.instrument_id, other.side) and max(
                    row.start_ms, other.start_ms
                ) < min(row.end_ms, other.end_ms):
                    raise ValueError("Overlapping cost intervals")

    def binding(self, *, horizon_bars: int, periods_per_year: float) -> dict:
        payload = {
            "basis": self.basis,
            "rows": [asdict(r) for r in self.rows],
            "horizon_bars": horizon_bars,
            "periods_per_year": periods_per_year,
        }
        if self.allocation_mode != "filter_then_allocate":
            payload["allocation_mode"] = self.allocation_mode
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return {**payload, "sha256": hashlib.sha256(raw).hexdigest()}

    def apply(self, frame: pd.DataFrame, *, horizon_bars: int, periods_per_year: float):
        if (
            type(horizon_bars) is not int
            or horizon_bars <= 0
            or not np.isfinite(periods_per_year)
            or periods_per_year <= 0
        ):
            raise ValueError("Invalid signal horizon/annualization")
        if frame.index.has_duplicates:
            raise ValueError("Duplicate signal observations")
        ts = frame.index.get_level_values("ts_open").to_numpy(dtype=np.int64)
        ids = frame.index.get_level_values("instrument_id").to_numpy()
        mu = frame.mu_ann.to_numpy(dtype=float)
        if np.isinf(mu).any():
            raise ValueError("Infinite expected returns")
        for indices in frame.groupby(level="ts_open", sort=False).indices.values():
            check_mu_ann_contract(mu[indices])
        bounded_mu, _ = winsorize_mu_ann(mu)
        cost = np.full(len(frame), np.nan)
        active = np.isfinite(mu) & (mu != 0)
        for row in self.rows:
            selected = (
                (ids == row.instrument_id)
                & (ts >= row.start_ms)
                & (ts < row.end_ms)
                & ((mu > 0) if row.side == "long" else (mu < 0))
            )
            cost[selected] = row.round_trip_fraction
        if np.any(active & ~np.isfinite(cost)):
            raise ValueError("Missing dated cost coverage for nonzero signals")
        result = frame.copy()
        result["mu_ann_before_cost_gate"] = mu
        result["cost_gate_round_trip_fraction"] = cost
        reject = active & (np.abs(bounded_mu) * (horizon_bars / periods_per_year) <= cost)
        if self.allocation_mode == "retain_cash":
            # Keep original signals through allocation and overlays; mask target
            # weights afterward so rejected capital cannot be redistributed.
            result["cash_retention_eligible"] = ~reject
        else:
            result.loc[reject, "mu_ann"] = 0.0
        return result
