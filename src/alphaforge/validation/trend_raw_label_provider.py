"""Explicit raw holding-label input, independent of synthetic feature prices."""

from __future__ import annotations

from dataclasses import asdict
from types import MappingProxyType

import numpy as np
import pandas as pd

from alphaforge.validation.trend_holding_label_v2 import label_sessions
from alphaforge.validation.trend_input_routes_v2 import TrendInputRoutesV2
from alphaforge.validation.trend_observation import ObservationError, fingerprint, session_window


class RawHoldingLabelProvider:
    def __init__(self, paired, *, instrument_symbols, snapshots, mode):
        if mode not in {"PROSPECTIVE", "DIAGNOSTIC_CURRENT_VINTAGE"}:
            raise ObservationError("Explicit label observation mode required")
        self._routes = TrendInputRoutesV2(paired)
        self._symbols = MappingProxyType(dict(instrument_symbols))
        self._snapshots = MappingProxyType(dict(snapshots))
        if (
            not self._symbols
            or len(set(self._symbols.values())) != len(self._symbols)
            or any(s not in self._snapshots for s in self._symbols.values())
        ):
            raise ObservationError("Unique instrument mapping and action coverage required")
        self._mode = mode
        raw = self._routes.execution_bars(through_session=int(paired.session_ms.max()))
        self._keys = frozenset(zip(raw.symbol, raw.session_ms, strict=True))
        self._digest = fingerprint(
            {
                "raw_bars": raw.to_dict("records"),
                "instruments": dict(self._symbols),
                "snapshots": {s: asdict(a) for s, a in self._snapshots.items()},
                "mode": mode,
            }
        )

    @property
    def binding(self):
        return {
            "raw_label_input_sha256": self._digest,
            "raw_label_mode": self._mode,
            "raw_label_convention": "raw_open_cash_accrual_fixed_release_v2",
        }

    def labels(self, index, *, horizon, as_of_ms):
        if not isinstance(index, pd.MultiIndex) or index.names != ["ts_open", "instrument_id"]:
            raise ObservationError("Explicit decision/instrument label index required")
        if not index.is_unique:
            raise ObservationError("Duplicate label decisions")
        if type(as_of_ms) is not int or as_of_ms <= 0:
            raise ObservationError("Actual integer label cutoff required")
        values = []
        for decision, instrument in index:
            if isinstance(decision, bool) or not isinstance(decision, (int, np.integer)):
                raise ObservationError("Integer decision sessions required")
            if instrument not in self._symbols:
                raise ObservationError("Unknown label instrument")
            symbol = self._symbols[instrument]
            entry, end = label_sessions(int(decision), horizon)
            if session_window(end)[0] > as_of_ms:
                values.append(np.nan)
                continue
            # Missing inception/end-point observations stay missing on the fixed
            # decision grid. Disputed/zero-volume printed endpoints instead fail.
            if (symbol, entry) not in self._keys or (symbol, end) not in self._keys:
                values.append(np.nan)
                continue
            result = self._routes.label(
                symbol=symbol,
                decision_session=int(decision),
                horizon=horizon,
                snapshot=self._snapshots[symbol],
                as_of_ms=as_of_ms,
                mode=self._mode,
            )
            values.append(result.gross_return)
        return pd.Series(values, index=index, name="raw_holding_return", dtype=float)
