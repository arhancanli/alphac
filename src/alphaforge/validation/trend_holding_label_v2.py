"""Fixed-release guard: late records cannot enter an earlier IC observation.

The v1 accounting implementation remains frozen for the current-vintage diagnostic.
"""

from __future__ import annotations

from alphaforge.validation.trend_holding_label import holding_label as _accounting
from alphaforge.validation.trend_holding_label import label_sessions
from alphaforge.validation.trend_observation import ObservationError
from alphaforge.validation.trend_price_bridge import ActionSnapshot

VERSION = "raw_open_cash_accrual_fixed_release_v2"
__all__ = ["holding_label", "label_sessions"]


def holding_label(*, snapshot: ActionSnapshot, **kwargs):
    result = _accounting(snapshot=snapshot, **kwargs)
    if result.mode == "PROSPECTIVE" and snapshot.observed_ms > result.release_ms:
        raise ObservationError("Late action record cannot enter the fixed exit-close release")
    return result
