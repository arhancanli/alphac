"""Exact raw-bar quality gate for the engine's queued-order fill interface.

Diagnostic historical adapter. Does not certify historical publication, control
forced liquidations, or integrate signal/label/dividend accounting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType

from alphaforge.backtest.fills import BarView, FillModel
from alphaforge.core.errors import FillUnavailableError, LookaheadError


@dataclass(frozen=True)
class ReviewedBar:
    instrument_id: str
    bar: BarView
    eligible: bool


class QualityGatedFill:
    def __init__(self, delegate: FillModel, reviewed: list[ReviewedBar]):
        records = {}
        for record in reviewed:
            key = (record.instrument_id, record.bar.ts_open)
            if not record.instrument_id or key in records or type(record.eligible) is not bool:
                raise ValueError(
                    "Unique instrument/session and explicit boolean eligibility required"
                )
            if record.eligible and (
                record.bar.volume <= 0
                or not math.isfinite(record.bar.quote_volume)
                or record.bar.quote_volume <= 0
            ):
                raise ValueError("Eligible bars require positive recorded volume and quote volume")
            records[key] = record
        self._reviewed = MappingProxyType(records)
        self._delegate = delegate

    def fill(self, order, inst, next_bar, *, adv_quote, sigma_daily):
        if next_bar.ts_open < order.decision_ts:
            raise LookaheadError("Quality gate received a bar before decision")
        if order.instrument_id != inst.instrument_id:
            raise FillUnavailableError("Quality gate instrument mismatch")
        record = self._reviewed.get((order.instrument_id, next_bar.ts_open))
        if record is None or not record.eligible:
            raise FillUnavailableError("Missing or ineligible reviewed raw bar")
        # This also prevents substituting synthetic signal prices or inflating
        # next-bar liquidity after the panel has been reviewed.
        if next_bar != record.bar:
            raise FillUnavailableError("Execution bar differs from reviewed raw OHLCV")
        return self._delegate.fill(
            order, inst, next_bar, adv_quote=adv_quote, sigma_daily=sigma_daily
        )
