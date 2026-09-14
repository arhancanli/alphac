"""Isolated session-complete equity covariance panel; caller selects price basis."""

import pandas as pd
from alphamax_share_ratio_features import share_ratio_close

from alphaforge.core.types import AssetClass
from alphaforge.portfolio.strategy import BlendStrategy

DAY = 86400000


def session_close_panel(reader, ctx, ids, window, *, correct_splits):
    if ctx.asset_class is not AssetClass.EQUITY or window <= 0:
        raise ValueError("positive equity session window required")
    grid = ctx.calendar.expected_bar_opens(ctx.ts - (window * 2 + 32) * DAY, ctx.ts, ctx.tf)[
        -window:
    ]
    if len(grid) != window:
        raise ValueError("calendar does not cover requested session window")
    table = reader.ohlcv(ids, start=grid[0], end=ctx.ts, as_of=ctx.ts, tf=ctx.tf)
    frame = table.to_pandas()
    frame["ts_open"] = (
        pd.to_datetime(frame.ts_open, unit="ms", utc=True)
        .astype("datetime64[ms, UTC]")
        .astype("int64")
    )
    if frame.duplicated(["ts_open", "instrument_id"]).any():
        raise ValueError("duplicate covariance bars")
    raw = (
        frame.pivot(index="ts_open", columns="instrument_id", values="close")
        .reindex(index=grid, columns=ids)
        .astype(float)
    )
    raw.index = pd.Index(grid, name="ts_open", dtype="int64")
    if not correct_splits:
        return raw
    actions = reader.corporate_actions(ids, start=grid[0], end=ctx.ts, as_of=ctx.ts).to_pandas()
    for name in ["ex_date", "available_at"]:
        actions[name] = (
            pd.to_datetime(actions[name], unit="ms", utc=True)
            .astype("datetime64[ms, UTC]")
            .astype("int64")
        )
    return share_ratio_close(raw, actions)


class SessionPriceBasisStrategy(BlendStrategy):
    """Research-only; explicit reader comes from the frozen scenario snapshot."""

    def __init__(self, *args, basis_reader, correct_covariance_splits, **kwargs):
        super().__init__(*args, **kwargs)
        self._basis_reader = basis_reader
        self._correct_covariance_splits = correct_covariance_splits

    def _close_panel(self, ctx, ids):
        return session_close_panel(
            self._basis_reader,
            ctx,
            ids,
            self._cov_window_bars + 1,
            correct_splits=self._correct_covariance_splits,
        )
