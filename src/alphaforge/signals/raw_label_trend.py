"""Opt-in raw-label trend variant; no registered candidate or activation implied.

Feature frame open_px is never used to calculate holding returns. Forecasts and
features still require their own validated synthetic input path. Callers supply a
complete after-close session prefix, as in the retained causal service.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from alphaforge.signals.blending import BlendWeights
from alphaforge.signals.causal_trend import CausalTrendSignalService, released_weights
from alphaforge.validation.metrics import rank_ic
from alphaforge.validation.trend_observation import session_window
from alphaforge.validation.trend_raw_label_provider import RawHoldingLabelProvider


class RawLabelTrendSignalService(CausalTrendSignalService):
    """Research-only correction; requires a complete, fixed-anchor session prefix."""

    def __init__(self, *args, raw_label_provider, **kwargs):
        super().__init__(*args, **kwargs)
        if not isinstance(raw_label_provider, RawHoldingLabelProvider):
            raise ValueError("Explicit raw holding-label provider required")
        self._raw_label_provider = raw_label_provider

    @property
    def trial_binding(self):
        return {
            **super().trial_binding,
            "trend_label_availability": "raw_cash_exit_session_close_v2",
            **self._raw_label_provider.binding,
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
        requested = frame.index[frame.index.get_level_values("ts_open").isin(decisions)]
        labels = self._raw_label_provider.labels(
            requested,
            horizon=h,
            as_of_ms=session_window(int(sessions[-1]))[0],
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
