"""Diagnostic routing with preserved zero-volume sessions and explicit disputes.

Zero volume permits a recorded signal observation, never a fill or executable
label endpoint. Price disputes block feature histories and intersecting labels.
Execution views preserve all calendar rows and carry mandatory eligibility flags;
an engine adapter must enforce these flags before this route is activated.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from alphaforge.validation.trend_holding_label_v2 import holding_label, label_sessions
from alphaforge.validation.trend_observation import ObservationError, session_window


class TrendInputRoutesV2:
    def __init__(self, paired: pd.DataFrame):
        keys = ["symbol", "session_ms"]
        fields = ["open", "high", "low", "close"]
        required = {
            *keys,
            "raw_volume",
            "price_disputed",
            *(f"{prefix}_{f}" for prefix in ["raw", "signal"] for f in fields),
        }
        if not required.issubset(paired.columns) or paired.empty:
            raise ObservationError("Paired raw and synthetic OHLC plus volume required")
        frame = paired.loc[:, sorted(required)].copy(deep=True)
        if frame.duplicated(keys).any() or frame[keys].isna().any().any():
            raise ObservationError("Unique symbol/session keys required")
        if not all(isinstance(s, str) and s.isascii() and s.isalpha() for s in frame.symbol):
            raise ObservationError("Alphabetic symbols required")
        for session in frame.session_ms.unique():
            if not isinstance(session, (int, np.integer)):
                raise ObservationError("Integer session labels required")
            session_window(int(session))
        for prefix in ["raw", "signal"]:
            values = frame[[f"{prefix}_{f}" for f in fields]]
            if any(
                not pd.api.types.is_numeric_dtype(values[c])
                or pd.api.types.is_bool_dtype(values[c])
                for c in values
            ):
                raise ObservationError("Numeric OHLC required")
            if not np.isfinite(values.to_numpy()).all() or not (values > 0).all().all():
                raise ObservationError("Positive finite prices required")
            o, h, low, c = (frame[f"{prefix}_{f}"] for f in fields)
            if not ((low <= np.minimum(o, c)) & (np.maximum(o, c) <= h)).all():
                raise ObservationError("Invalid OHLC ordering")
        volume = frame.raw_volume
        if (
            not pd.api.types.is_numeric_dtype(volume)
            or pd.api.types.is_bool_dtype(volume)
            or not np.isfinite(volume).all()
            or not (volume >= 0).all()
        ):
            raise ObservationError("Nonnegative finite raw volume required")
        if frame.price_disputed.isna().any() or not pd.api.types.is_bool_dtype(
            frame.price_disputed
        ):
            raise ObservationError("Explicit boolean price-dispute flags required")
        self._frame = frame.sort_values(keys).reset_index(drop=True)

    def _view(self, prefix: str, through_session: int) -> pd.DataFrame:
        session_window(through_session)
        columns = [
            "symbol",
            "session_ms",
            "raw_volume",
            "price_disputed",
            *[f"{prefix}_{f}" for f in ["open", "high", "low", "close"]],
        ]
        result = self._frame.loc[self._frame.session_ms <= through_session, columns].copy(deep=True)
        result["execution_eligible"] = (result.raw_volume > 0) & ~result.price_disputed
        return result.rename(
            columns={
                "raw_volume": "volume",
                **{f"{prefix}_{f}": f for f in ["open", "high", "low", "close"]},
            }
        )

    def feature_bars(self, *, through_session: int) -> pd.DataFrame:
        result = self._view("signal", through_session)
        if result.price_disputed.any():
            raise ObservationError("Unresolved source prices in requested feature history")
        return result

    def execution_bars(self, *, through_session: int) -> pd.DataFrame:
        return self._view("raw", through_session)

    def label(
        self,
        *,
        symbol: str,
        decision_session: int,
        horizon: int,
        snapshot,
        as_of_ms: int,
        mode: str = "PROSPECTIVE",
    ):
        entry, end = label_sessions(decision_session, horizon)
        frame = self._frame[self._frame.symbol == symbol].set_index("session_ms")
        if entry not in frame.index or end not in frame.index:
            raise ObservationError("Exact raw entry/exit opens required; no interpolation")
        interval = frame.loc[(frame.index >= entry) & (frame.index <= end)]
        if interval.price_disputed.any():
            raise ObservationError("Unresolved prices in label interval")
        if frame.loc[entry, "raw_volume"] == 0 or frame.loc[end, "raw_volume"] == 0:
            raise ObservationError("No executable raw open at zero-volume label endpoint")
        return holding_label(
            symbol=symbol,
            entry_ms=entry,
            exit_ms=end,
            entry_open=float(frame.loc[entry, "raw_open"]),
            exit_open=float(frame.loc[end, "raw_open"]),
            snapshot=snapshot,
            as_of_ms=as_of_ms,
            mode=mode,
        )
