"""Execution-aware forward returns (alphaDesign.md §5.1).

The label honours the system's execution contract exactly: a signal is computed at
the **close** of bar τ (decision availability ``τ + Δ``), the position is entered at
the **open** of the next bar, and exited at the **open** of the bar ``h`` bars later::

    entry = O(τ + Δ)              # open of the bar whose ts_open == τ + Δ
    exit  = O(τ + (1 + h)·Δ)
    y_h(τ) = ln(exit / entry)

Using ``C(τ)`` as the entry price is the classic lookahead bug and is banned. The
label is indexed at the *decision bar* τ so it joins 1:1 against factor values; the
future prices it contains make it a **training/evaluation target only** — it must
never be fed back in as a feature.

Gap discipline: entry/exit bars are the next **session** opens on the sleeve's trading
calendar, looked up against the panel by exact ``ts_open`` — never by positional shift.
The entry bar is ``calendar.next_bar_open(τ)`` and the exit bar is the open ``h`` sessions
after that (``1 + h`` sessions after τ). For the 24/7 crypto calendar a session hop is just
``+ Δ`` (``next_bar_open(t, H1) == t + Δ``), so the targets are ``τ + Δ`` and
``τ + (1 + h)·Δ`` exactly and the crypto labels are byte-identical to the prior fixed-offset
implementation; for an XNYS daily calendar a Friday's next open is the following Monday, not
a phantom Saturday slot. If the entry or exit session bar is missing from the panel (exchange
outage, delisting window, a halted name) the label is NaN — gaps are NEVER bridged, because a
live system could not have traded a bar that did not print.

This module never mutates its input frame.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd

from alphaforge.core.calendar import Always24x7Calendar, TradingCalendar
from alphaforge.core.time import Timeframe
from alphaforge.features.library.vol import EWMA_VOL_SPAN, ewma_vol

__all__ = ["forward_returns"]

_REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset({"instrument_id", "ts_open", "open"})

_DEFAULT_CALENDAR: Final[Always24x7Calendar] = Always24x7Calendar()
"""Default calendar — the 24/7 grid, under which a session hop reduces to ``+ Δ`` so existing
(crypto) callers that pass no calendar stay byte-identical to the fixed-offset arithmetic."""

# Extra calendar time appended to the session grid past the last decision bar so the
# (1 + h)-session-ahead exit target of the final bars is itself resolvable on the grid (it
# still NaNs after the panel reindex — no future bar printed — exactly as the old +Δ math did).
# A fortnight comfortably clears any weekend/holiday cluster at session granularity.
_GRID_LOOKAHEAD_PAD_MS: Final[int] = 14 * 86_400_000


def _sigma_at_decision(close: pd.Series, span: int = EWMA_VOL_SPAN) -> pd.Series:
    """Per-bar EWMA volatility at the decision bar τ — thin adapter over the ONE
    sanctioned implementation, :func:`alphaforge.features.library.vol.ewma_vol`
    (zero-mean, ``λ = 2/(span+1)``, ``min_periods = span``).

    ``close`` must be ordered by ``ts_open`` for one instrument. Where the panel
    has a gap the first post-gap return spans the gap; acceptable for a scale
    estimate (the gap bar itself is already an NaN label via the entry/exit rule).
    """
    return ewma_vol(close.to_frame("close"), span=span)["close"]


def forward_returns(
    bars: pd.DataFrame,
    horizon_bars: int,
    *,
    vol_scaled: bool = False,
    vol: pd.Series | None = None,
    timeframe: Timeframe = Timeframe.H1,
    calendar: TradingCalendar | None = None,
) -> pd.Series:
    """Execution-aware forward log return per (decision bar τ, instrument).

    Formula (alphaDesign.md §5.1), with ``h = horizon_bars`` and entry/exit at **session**
    opens on ``calendar`` (the next session after τ, and the open ``h`` sessions after that)::

        y_h(τ) = ln( O(session τ+1+h) / O(session τ+1) )

    On the 24/7 calendar (``calendar=None``, the default) a session hop is ``+ Δ`` with
    ``Δ = timeframe.ms``, so this is exactly ``ln( O(τ + (1 + h)·Δ) / O(τ + Δ) )`` —
    byte-identical to the prior fixed-offset implementation. On an XNYS daily calendar the
    hops skip weekends/holidays. Pass ``calendar=calendar_for(asset_class)`` on the equity
    path; leaving it ``None`` keeps the crypto contract.

    Vol-scaled variant (``vol_scaled=True``)::

        y~_h(τ) = y_h(τ) / ( sigma(τ) · sqrt(h) )

    where ``sigma(τ)`` is the per-bar EWMA volatility (span 168, zero-mean) of the
    instrument's log returns **at the decision bar τ** — bar τ's close is known at
    decision time ``τ + Δ``, so the scaling is point-in-time. Pass ``vol`` (a Series
    on the same ``(ts_open, instrument_id)`` MultiIndex) to supply sigma externally;
    otherwise it is computed from the ``close`` column. Non-positive or missing sigma
    yields NaN.

    Parameters
    ----------
    bars:
        Long panel with columns ``instrument_id``, ``ts_open`` (epoch-ms UTC int64),
        ``open`` (and ``close`` when sigma must be computed). One row per
        (instrument, bar); duplicates are an upstream bug and raise.
    horizon_bars:
        Holding period ``h`` in bars (> 0).

    Returns
    -------
    pd.Series
        Float series named ``fwd_ret_{h}`` (suffix ``_volscaled`` when scaled),
        indexed by the sorted ``(ts_open, instrument_id)`` MultiIndex — one entry
        per input bar row; NaN where the entry or exit bar is missing.
    """
    if horizon_bars <= 0:
        raise ValueError(f"horizon_bars must be > 0; got {horizon_bars}")
    missing = _REQUIRED_COLUMNS - set(bars.columns)
    if missing:
        raise ValueError(f"bars is missing required columns: {sorted(missing)}")
    need_close = vol_scaled and vol is None
    if need_close and "close" not in bars.columns:
        raise ValueError("bars must include 'close' to compute EWMA vol (or pass vol=...)")
    if not pd.api.types.is_integer_dtype(bars["ts_open"]):
        raise TypeError(f"ts_open must be int64 epoch-ms UTC; got dtype {bars['ts_open'].dtype}")
    if bars.duplicated(["instrument_id", "ts_open"]).any():
        raise ValueError("bars contains duplicate (instrument_id, ts_open) rows")
    opens_all = bars["open"].to_numpy(dtype=float)
    if not np.all(opens_all[np.isfinite(opens_all)] > 0.0):
        raise ValueError("bars contains non-positive open prices; log returns undefined")

    cal = calendar if calendar is not None else _DEFAULT_CALENDAR
    delta = timeframe.ms

    # The sleeve's expected session grid spanning the panel plus enough look-ahead that the
    # (1 + h)-session exit of the last decision bar resolves on the grid. On the 24/7 calendar
    # this is the contiguous ``+Δ`` grid, so ``grid[pos+1] == τ + Δ`` and
    # ``grid[pos+1+h] == τ + (1 + h)·Δ`` exactly (byte-identical crypto); on XNYS it skips
    # weekends/holidays. Entry/exit are then looked up against each instrument's own opens, so
    # a session the instrument did not print stays NaN (gap discipline preserved).
    ts_all = bars["ts_open"].to_numpy(dtype=np.int64)
    grid_end = int(ts_all.max()) + (horizon_bars + 2) * delta + _GRID_LOOKAHEAD_PAD_MS
    grid = np.asarray(
        cal.expected_bar_opens(int(ts_all.min()), grid_end, timeframe), dtype=np.int64
    )
    n_grid = grid.shape[0]

    pieces: list[pd.Series] = []
    vol_pieces: list[pd.Series] = []
    for instrument_id, group in bars.groupby("instrument_id", sort=True):
        ordered = group.sort_values("ts_open")
        ts = ordered["ts_open"].to_numpy(dtype=np.int64)
        opens = pd.Series(ordered["open"].to_numpy(dtype=float), index=ts)
        # Locate each decision bar on the session grid, then hop 1 and 1+h sessions forward.
        pos = np.searchsorted(grid, ts)
        on_grid = grid[np.minimum(pos, n_grid - 1)] == ts  # bar τ is itself a session
        entry_idx = pos + 1
        exit_idx = pos + 1 + horizon_bars
        sentinel = np.int64(-1)  # never a valid epoch-ms key → reindex → NaN
        entry_ts = np.where(
            on_grid & (entry_idx < n_grid), grid[np.minimum(entry_idx, n_grid - 1)], sentinel
        )
        exit_ts = np.where(
            on_grid & (exit_idx < n_grid), grid[np.minimum(exit_idx, n_grid - 1)], sentinel
        )
        entry = opens.reindex(entry_ts).to_numpy()
        exit_ = opens.reindex(exit_ts).to_numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            log_ret = np.log(exit_ / entry)
        index = pd.MultiIndex.from_arrays(
            [ts, np.full(len(ts), instrument_id)], names=["ts_open", "instrument_id"]
        )
        pieces.append(pd.Series(log_ret, index=index))
        if need_close:
            closes = pd.Series(ordered["close"].to_numpy(dtype=float), index=index)
            vol_pieces.append(_sigma_at_decision(closes))

    result: pd.Series = pd.concat(pieces).sort_index()
    name = f"fwd_ret_{horizon_bars}"

    if vol_scaled:
        sigma = pd.concat(vol_pieces).sort_index() if need_close else vol
        assert sigma is not None  # need_close xor vol given; mypy aid
        sigma_values = sigma.reindex(result.index).to_numpy(dtype=float, copy=True)
        sigma_values[~(sigma_values > 0.0)] = np.nan  # non-positive / NaN sigma → NaN label
        scaled = result.to_numpy() / (sigma_values * np.sqrt(float(horizon_bars)))
        result = pd.Series(scaled, index=result.index)
        name = f"{name}_volscaled"

    result.name = name
    return result
