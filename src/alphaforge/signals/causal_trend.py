"""Opt-in equity trend weights released only after the label's exit session.

Daily session labels denote midnight, not a tradable open. An observation at
session tau enters at tau+1 and exits at tau+1+h. It can first affect a signal
at the close of that exit session. A fixed history anchor pins the IC grid;
callers must retain the full prefix, including warm-up and missing rows.
The legacy service remains available solely to reproduce its archived trials.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass
from alphaforge.labeling import forward_returns
from alphaforge.signals.blending import (
    BLEND_EWMA_HALFLIFE_GRID,
    KAPPA_FLOOR,
    KAPPA_SHRINK,
    BlendWeights,
)
from alphaforge.signals.service import SignalService
from alphaforge.validation.metrics import rank_ic


def released_weights(ics: pd.DataFrame, releases: pd.Index) -> BlendWeights:
    """Smooth observations in order, indexed by when they become available."""
    if not len(ics.columns) or len(ics) != len(releases):
        raise ValueError("IC names and one release per observation are required")
    if not releases.is_unique or not releases.is_monotonic_increasing:
        raise ValueError("Release sessions must be unique and increasing")
    if len(ics) and np.any(releases.to_numpy() <= ics.index.to_numpy()):
        raise ValueError("Labels must be released after their decision sessions")
    names = tuple(ics.columns)
    if ics.empty:
        return BlendWeights.equal(names)
    smoothed = (
        ics.astype(float)
        .ewm(halflife=BLEND_EWMA_HALFLIFE_GRID, adjust=True, ignore_na=True, min_periods=1)
        .mean()
    )
    smoothed.index = pd.Index(releases, name="ts_open")
    values = smoothed.to_numpy()
    positive = np.where(np.isfinite(values) & (values > 0), values, 0.0)
    floor = np.maximum(KAPPA_SHRINK * positive.mean(axis=1), KAPPA_FLOOR)
    raw = positive + floor[:, None]
    weights = pd.DataFrame(
        raw / raw.sum(axis=1, keepdims=True), index=smoothed.index, columns=names
    )
    return BlendWeights(
        alpha_names=names,
        weights=weights,
        smoothed_ic=smoothed,
        gross_smoothed_ic=smoothed.copy(),
        net_smoothed_ic=smoothed.copy(),
    )


class CausalTrendSignalService(SignalService):
    """Research-only correction; requires a complete, fixed-anchor session prefix."""

    def __init__(self, *args, history_anchor: int, **kwargs):
        super().__init__(*args, **kwargs)
        if self._asset_class is not AssetClass.EQUITY or self._anchor_tf != Timeframe.D1:
            raise ValueError("Causal trend service supports daily equities only")
        if set(self.alpha_names) != {"mf_trend_63", "mf_trend_126", "mf_trend_252"}:
            raise ValueError("Causal trend service requires the fixed trend slate")
        self.history_anchor = int(history_anchor)

    @property
    def trial_binding(self):
        return {
            **super().trial_binding,
            "trend_label_availability": "exit_session_close_v1",
            "trend_ic_history_anchor": self.history_anchor,
        }

    def _weights_from_panel(self, frame, mask, zs):
        names = self.alpha_names
        if frame.empty:
            return BlendWeights.equal(names)
        sessions = frame.index.get_level_values("ts_open").unique().sort_values()
        expected = pd.Index(
            self._calendar.expected_bar_opens(
                self.history_anchor, int(sessions[-1]) + 1, self._anchor_tf
            ),
            name="ts_open",
        )
        if not sessions.equals(expected):
            raise ValueError("Expected complete session prefix from the fixed history anchor")
        h = self._cfg.horizon_bars
        # Retain NaN observations on the fixed grid. Missing asset prices never
        # move the IC phase or cause a label to bridge an unprinted session.
        positions = np.arange(0, max(0, len(sessions) - h - 1), h)
        decisions = sessions.take(positions)
        releases = sessions.take(positions + h + 1)
        if not len(positions):
            return BlendWeights.equal(names)
        bars = frame.open_px.dropna().rename("open").reset_index()
        if bars.empty:
            return released_weights(pd.DataFrame(np.nan, index=decisions, columns=names), releases)
        labels = forward_returns(
            bars, h, timeframe=self._anchor_tf, calendar=self._calendar
        ).reindex(frame.index)
        ics = pd.DataFrame(
            {
                name: rank_ic(zs[name], labels, mask, min_members=self._min_members).reindex(
                    decisions
                )
                for name in names
            }
        )
        return released_weights(ics, releases)
