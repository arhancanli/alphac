"""Sample weights for meta-label training (alphaDesign.md §5.4, AFML ch.4).

Triple-barrier labels overlap in time: an event opened at bar τ stays open until its
barrier-touch / vertical bar ``t1``, so consecutive events share future bars and are
therefore *not* independent observations. Feeding the GBM unit weights would let a
clump of overlapping, near-duplicate labels dominate the fit and inflate the effective
sample size. This module derives the AFML sample-weight decomposition that corrects
for that redundancy:

    sample_weight_i  =  attribution_i  ·  decay_i  ·  csdecorr_i

where

- **attribution** ``w̃_i = |Σ_t r_t / c_t|`` spreads each path bar's return over the
  number of events ``c_t`` concurrently claiming it (label *uniqueness*), then is
  rescaled to cross-event mean 1;
- **decay** is the optional López-de-Prado piecewise-linear time decay on the
  cumulative-uniqueness clock (newest event 1.0, oldest ``time_decay``);
- **csdecorr** ``1/√(n_t)`` is a cross-sectional de-correlation factor where ``n_t`` is
  the number of events firing at the *same decision timestamp across all instruments*.
  Concurrency above is deliberately *within-symbol* (cross-symbol time overlap is the
  CV purger's job); but ~40 symbols firing a regime-correlated event every bar are not
  40 independent samples, and purging does not fix *in-training* statistics. This is
  the fix mandated by leakageCritique finding 23 / overfit-critique item 6.

Doctrine carried from :mod:`alphaforge.labeling.forward_returns`:

- Spans are swept over the exact ``ts_open`` bar grid (``+ k·Δ`` arithmetic via
  :func:`alphaforge.core.time.expected_bar_opens`), never positional ``shift``. A bar
  that is missing from the panel was never tradable, so it does **not** increment
  concurrency and does **not** contribute return attribution — gaps are never bridged.
- These are *point-in-time* functions of an already-resolved label frame; they look
  into the future only insofar as ``t1`` does, and like the labels themselves the
  resulting weights are a training artifact, never a feature.
- Inputs are never mutated.

All four functions operate on the §1.3 label frame indexed by the sorted
``(ts_open, instrument_id)`` MultiIndex (``ts_open`` == the decision bar τ), needing at
least the ``entry_ts`` and ``t1`` columns; NaN-price (un-tradable) events are dropped
up front so weights are emitted only for live labels.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd

from alphaforge.core.time import Timeframe

__all__ = [
    "attribution_weights",
    "average_uniqueness",
    "concurrency",
    "sample_weights",
]

_INDEX_NAMES: Final[tuple[str, str]] = ("ts_open", "instrument_id")
_SPAN_COLUMNS: Final[frozenset[str]] = frozenset({"entry_ts", "t1"})


def _validate_event_frame(events: pd.DataFrame) -> None:
    """Fail loud on a malformed label frame (programming error upstream)."""
    missing = _SPAN_COLUMNS - set(events.columns)
    if missing:
        raise ValueError(f"events is missing required columns: {sorted(missing)}")
    if list(events.index.names) != list(_INDEX_NAMES):
        raise ValueError(
            f"events must be indexed by {list(_INDEX_NAMES)}; got {list(events.index.names)}"
        )
    if events.index.duplicated().any():
        raise ValueError("events contains duplicate (ts_open, instrument_id) rows")


def _resolved(events: pd.DataFrame) -> pd.DataFrame:
    """Subset to live events with an integer span; un-tradable rows carry a NaN ``t1``.

    The triple-barrier frame emits NaN-price / NaN-``t1`` sentinel rows when an entry,
    vol, or path bar was unavailable (forward_returns gap discipline). Such rows have no
    span to sweep, so they earn no weight and are dropped here rather than coerced.
    """
    mask = events["t1"].notna() & events["entry_ts"].notna()
    return events.loc[mask]


def _event_arrays(
    resolved: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Decompose the resolved frame into parallel numpy arrays for a typed sweep.

    Returns ``(decision_ts, instrument_id, entry_ts, t1)`` — avoiding ``iterrows`` keeps
    the integer index/columns from collapsing to ``Hashable``/``object`` under
    ``mypy --strict`` and is the faster path over a long event panel.
    """
    decision_ts = resolved.index.get_level_values("ts_open").to_numpy(dtype=np.int64)
    instrument_id = resolved.index.get_level_values("instrument_id").to_numpy()
    entry_ts = resolved["entry_ts"].to_numpy(dtype=np.int64)
    t1 = resolved["t1"].to_numpy(dtype=np.int64)
    return decision_ts, instrument_id, entry_ts, t1


def _span_opens(entry_ts: int, t1: int, step: int) -> np.ndarray:
    """Aligned bar opens of the *inclusive* span ``[entry_ts, t1]`` on the Δ grid.

    The span runs from the entry bar through (and including) the exit bar ``t1``; the
    reference grid is exact ``+ k·Δ`` arithmetic (``expected_bar_opens`` is half-open,
    so the upper bound is ``t1 + step``). Whether each grid slot actually printed is
    resolved against the panel by the caller — a missing slot does not count.
    """
    return np.arange(entry_ts, t1 + step, step, dtype=np.int64)


def concurrency(events: pd.DataFrame, *, timeframe: Timeframe = Timeframe.H1) -> pd.Series:
    """Per-bar label concurrency ``c_t`` (AFML ch.4.3), within each instrument.

    ``c_t`` is the number of events whose inclusive span ``[entry_ts_i, t1_i]`` covers
    bar ``t``::

        c_t = Σ_i 1{ t ∈ [entry_ts_i, t1_i] }      (same instrument only)

    Built by sweeping every event's span over the exact ``ts_open`` grid (``+ k·Δ``),
    so two events overlapping by one bar each see ``c = 2`` on that shared bar and
    ``c = 1`` elsewhere. The sweep is *within-symbol*: an event's span only increments
    bars of its own instrument (cross-symbol commonality is handled by the
    cross-sectional de-correlation factor in :func:`sample_weights`, not here).

    Parameters
    ----------
    events:
        §1.3 label frame on the ``(ts_open, instrument_id)`` MultiIndex with ``entry_ts``
        and ``t1`` columns (int64 epoch-ms). Un-tradable (NaN-``t1``) rows are skipped.
    timeframe:
        Bar timeframe Δ for the grid arithmetic; must match the label frame's bars.

    Returns
    -------
    pd.Series
        Int64 series named ``concurrency`` indexed by the sorted
        ``(ts_open, instrument_id)`` MultiIndex of every bar touched by at least one
        span. The count is keyed by **bar** ``ts_open`` (not the decision τ), so it
        spans entry → exit bars and is the denominator the other functions consume.
    """
    _validate_event_frame(events)
    resolved = _resolved(events)
    step = timeframe.ms

    _, instrument_id, entry_ts, t1 = _event_arrays(resolved)
    counts: dict[tuple[int, str], int] = {}
    for iid, e0, e1 in zip(instrument_id, entry_ts, t1, strict=True):
        for bar_ts in _span_opens(int(e0), int(e1), step):
            key = (int(bar_ts), str(iid))
            counts[key] = counts.get(key, 0) + 1

    if not counts:
        return pd.Series(
            [], index=pd.MultiIndex.from_arrays([[], []], names=_INDEX_NAMES),
            dtype="int64", name="concurrency",
        )
    index = pd.MultiIndex.from_tuples(sorted(counts), names=_INDEX_NAMES)
    values = [counts[key] for key in index]
    return pd.Series(values, index=index, dtype="int64", name="concurrency")


def average_uniqueness(
    events: pd.DataFrame, conc: pd.Series, *, timeframe: Timeframe = Timeframe.H1
) -> pd.Series:
    """Average label uniqueness ``ū_i`` per event (AFML ch.4.3).

    Over the event's inclusive span, uniqueness is the mean reciprocal concurrency::

        ū_i = (1 / n_i) · Σ_{t ∈ [entry_ts_i, t1_i]} 1 / c_t

    where ``n_i`` is the number of bars of the span that actually printed (a gap bar
    has no ``c_t`` entry and is excluded from both the sum and ``n_i``). An event that
    never overlaps another has ``c_t ≡ 1`` ⇒ ``ū = 1``; two events that fully overlap on
    equal spans each have ``c_t ≡ 2`` ⇒ ``ū = ½``.

    Parameters
    ----------
    events:
        §1.3 label frame (see :func:`concurrency`).
    conc:
        The per-bar concurrency series from :func:`concurrency` on the same frame.
    timeframe:
        Bar timeframe Δ; must match ``conc``.

    Returns
    -------
    pd.Series
        Float64 series named ``avg_uniqueness`` in ``(0, 1]``, indexed by the sorted
        decision ``(ts_open, instrument_id)`` MultiIndex of the resolved events.
    """
    _validate_event_frame(events)
    resolved = _resolved(events)
    step = timeframe.ms
    inv_c = _inverse_concurrency(conc)

    decision_ts, instrument_id, entry_ts, t1 = _event_arrays(resolved)
    out: dict[tuple[int, str], float] = {}
    for d_ts, iid, e0, e1 in zip(decision_ts, instrument_id, entry_ts, t1, strict=True):
        contribs = [
            inv_c[(int(bar_ts), str(iid))]
            for bar_ts in _span_opens(int(e0), int(e1), step)
            if (int(bar_ts), str(iid)) in inv_c
        ]
        out[(int(d_ts), str(iid))] = float(np.mean(contribs)) if contribs else np.nan
    return _to_series(out, name="avg_uniqueness")


def attribution_weights(
    events: pd.DataFrame,
    returns: pd.Series,
    conc: pd.Series,
    *,
    time_decay: float = 0.75,
    timeframe: Timeframe = Timeframe.H1,
) -> pd.Series:
    """Return-attribution sample weights with optional time decay (AFML ch.4.4/4.5).

    Each event is credited with the magnitude of the return it can claim, splitting
    every path bar's return across the events concurrently holding it::

        w̃_i = | Σ_{t ∈ [entry_ts_i, t1_i]} r_t / c_t |
        w_i = w̃_i · N / Σ_j w̃_j                       (cross-event mean 1)

    ``r_t`` are the per-bar (open→open) log returns supplied in ``returns`` on the
    ``(ts_open, instrument_id)`` bar grid; a span bar missing from ``returns`` or
    ``conc`` contributes nothing (gap discipline). A flat (zero-return) span yields
    ``w̃ = 0``.

    **Time decay** (``time_decay = d`` ∈ ``[0, 1]``, ``d = 1`` disables): after the
    mean-1 normalization, weights are scaled by a piecewise-linear factor on the
    *cumulative-uniqueness clock* ``x_i ∈ [0, 1]`` (events sorted oldest→newest by
    decision time, cumulative ``ū`` normalized to its max so the newest reaches 1.0)::

        decay_i = d + (1 - d) · x_i

    so the newest event keeps factor 1.0 and the oldest gets ``d`` (the default 0.75).
    The product is **not** re-normalized, preserving that documented newest/oldest
    relationship.

    Returns
    -------
    pd.Series
        Float64 series named ``attribution_weight`` (≥ 0), indexed by the sorted
        decision ``(ts_open, instrument_id)`` MultiIndex of the resolved events.
    """
    if not 0.0 <= time_decay <= 1.0:
        raise ValueError(f"time_decay must be in [0, 1]; got {time_decay}")
    _validate_event_frame(events)
    resolved = _resolved(events)
    step = timeframe.ms

    inv_c = _inverse_concurrency(conc)
    ret_map = _bar_map(returns)
    uniq = average_uniqueness(events, conc, timeframe=timeframe)

    decision_ts, instrument_id, entry_ts, t1 = _event_arrays(resolved)
    raw: dict[tuple[int, str], float] = {}
    for d_ts, iid, e0, e1 in zip(decision_ts, instrument_id, entry_ts, t1, strict=True):
        attribution = 0.0
        for bar_ts in _span_opens(int(e0), int(e1), step):
            key = (int(bar_ts), str(iid))
            r = ret_map.get(key)
            if r is not None and key in inv_c and np.isfinite(r):
                attribution += r * inv_c[key]
        raw[(int(d_ts), str(iid))] = abs(attribution)

    weights = _to_series(raw, name="attribution_weight")
    total = float(weights.sum())
    if total > 0.0:
        weights = weights * (float(len(weights)) / total)

    if time_decay < 1.0:
        weights = weights * _time_decay_factor(uniq, decay=time_decay)
    weights.name = "attribution_weight"
    return weights


def sample_weights(
    events: pd.DataFrame,
    bars: pd.DataFrame,
    *,
    time_decay: float = 0.75,
    timeframe: Timeframe = Timeframe.H1,
) -> pd.Series:
    """End-to-end ``sample_weight`` composer for the §4.3 training table (AFML ch.4).

    Chains the four ingredients into the persisted training weight:

    1. per-bar **open→open** log returns ``r_t`` from ``bars`` (the execution-contract
       return, gap-safe via exact ``+ Δ`` lookup — a bar whose successor is missing has
       NaN return and earns no attribution);
    2. within-symbol **concurrency** ``c_t`` (:func:`concurrency`);
    3. return **attribution** rescaled to mean 1, times the piecewise-linear **time
       decay** (:func:`attribution_weights`);
    4. the cross-sectional **de-correlation** factor ``1/√(n_t)`` where ``n_t`` is the
       number of events at the same decision timestamp across **all** instruments
       (leakageCritique finding 23 / overfit item 6): ~40 regime-correlated symbols
       firing together each bar are not 40 independent samples, and CV purging does not
       fix in-training statistics. Applied last (after decay), so the documented
       newest-1.0/oldest-``d`` *temporal* relationship is preserved within a single
       timestamp while genuinely concurrent cross-sectional clumps are down-weighted.

    The result is intentionally **not** re-normalized after steps 3-4, matching the
    weights consumed by ``HistGBMMetaModel.fit`` (so the effective-sample floor there
    reads true magnitudes, not a re-inflated mean-1 set).

    Parameters
    ----------
    events:
        §1.3 label frame on the ``(ts_open, instrument_id)`` MultiIndex; needs
        ``entry_ts`` and ``t1``.
    bars:
        Long OHLC panel (``instrument_id``, ``ts_open`` int64, ``open``) the spans were
        labeled against, for the per-bar return series. Never mutated.
    time_decay:
        Decay floor ``d`` (newest 1.0, oldest ``d``); ``1.0`` disables decay.
    timeframe:
        Bar timeframe Δ for all grid arithmetic.

    Returns
    -------
    pd.Series
        Float64 series named ``sample_weight`` (≥ 0, NaN-free for resolved events),
        indexed by the sorted decision ``(ts_open, instrument_id)`` MultiIndex.
    """
    _validate_event_frame(events)
    returns = _bar_open_returns(bars, timeframe=timeframe)
    conc = concurrency(events, timeframe=timeframe)
    weights = attribution_weights(
        events, returns, conc, time_decay=time_decay, timeframe=timeframe
    )
    weights = weights * _cross_sectional_decorr(weights.index)
    weights.name = "sample_weight"
    return weights


# --------------------------------------------------------------------------- helpers


def _bar_map(series: pd.Series) -> dict[tuple[int, str], float]:
    """Float lookup keyed by ``(ts_open:int, instrument_id:str)`` from a bar-grid Series.

    Pulls the MultiIndex levels as numpy arrays (rather than unpacking each Hashable
    key, which collapses to ``object`` under ``mypy --strict``).
    """
    ts = series.index.get_level_values("ts_open").to_numpy(dtype=np.int64)
    iid = series.index.get_level_values("instrument_id").to_numpy()
    vals = series.to_numpy(dtype=float)
    return {(int(t), str(s)): float(v) for t, s, v in zip(ts, iid, vals, strict=True)}


def _inverse_concurrency(conc: pd.Series) -> dict[tuple[int, str], float]:
    """``1 / c_t`` lookup keyed by ``(ts_open:int, instrument_id:str)``."""
    return {key: 1.0 / val for key, val in _bar_map(conc).items()}


def _to_series(data: dict[tuple[int, str], float], *, name: str) -> pd.Series:
    """Build a float64 Series on the sorted ``(ts_open, instrument_id)`` MultiIndex."""
    if not data:
        return pd.Series(
            [], index=pd.MultiIndex.from_arrays([[], []], names=_INDEX_NAMES),
            dtype="float64", name=name,
        )
    index = pd.MultiIndex.from_tuples(sorted(data), names=_INDEX_NAMES)
    return pd.Series([data[key] for key in index], index=index, dtype="float64", name=name)


def _time_decay_factor(uniq: pd.Series, *, decay: float) -> pd.Series:
    """Piecewise-linear López-de-Prado decay on the cumulative-uniqueness clock.

    Events are ordered oldest→newest by decision time; the cumulative sum of average
    uniqueness ``ū`` forms a monotone clock normalized to its maximum (newest = 1.0),
    so the factor is ``decay + (1 - decay)·x``. Returned aligned to ``uniq``'s index.
    """
    ordered = uniq.sort_index()
    cum = ordered.fillna(0.0).cumsum()
    total = float(cum.iloc[-1]) if len(cum) else 0.0
    clock = cum / total if total > 0.0 else pd.Series(1.0, index=ordered.index)
    factor = decay + (1.0 - decay) * clock
    return factor.reindex(uniq.index)


def _cross_sectional_decorr(index: pd.Index) -> pd.Series:
    """``1/√(n_t)`` per event, ``n_t`` = events sharing the decision timestamp τ.

    The count is purely cross-sectional (over ``ts_open``, across every instrument), so
    a single isolated event at its timestamp keeps factor 1.0 and a bar where 40
    symbols fire together each get ``1/√40``. See :func:`sample_weights` for why.
    """
    decision_ts = index.get_level_values("ts_open").to_numpy()
    _, inverse, counts = np.unique(decision_ts, return_inverse=True, return_counts=True)
    n_t = counts[inverse].astype(float)
    return pd.Series(1.0 / np.sqrt(n_t), index=index, dtype="float64")


def _bar_open_returns(bars: pd.DataFrame, *, timeframe: Timeframe) -> pd.Series:
    """Per-bar open→open log returns on the ``(ts_open, instrument_id)`` grid.

    ``r_t = ln( O(t + Δ) / O(t) )`` matches the execution contract (a bar's realized
    return is the move between the open you could enter at and the next open). The next
    open is fetched by exact ``+ Δ`` arithmetic; a missing successor bar yields a NaN
    return that earns no attribution. ``bars`` is never mutated.
    """
    required = {"instrument_id", "ts_open", "open"} - set(bars.columns)
    if required:
        raise ValueError(f"bars is missing required columns: {sorted(required)}")
    if not pd.api.types.is_integer_dtype(bars["ts_open"]):
        raise TypeError(f"ts_open must be int64 epoch-ms UTC; got dtype {bars['ts_open'].dtype}")
    if bars.duplicated(["instrument_id", "ts_open"]).any():
        raise ValueError("bars contains duplicate (instrument_id, ts_open) rows")

    step = timeframe.ms
    pieces: list[pd.Series] = []
    for instrument_id, group in bars.groupby("instrument_id", sort=True):
        ordered = group.sort_values("ts_open")
        ts = ordered["ts_open"].to_numpy(dtype=np.int64)
        opens = pd.Series(ordered["open"].to_numpy(dtype=float), index=ts)
        nxt = opens.reindex(ts + step).to_numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            log_ret = np.log(nxt / opens.to_numpy())
        idx = pd.MultiIndex.from_arrays(
            [ts, np.full(len(ts), instrument_id)], names=_INDEX_NAMES
        )
        pieces.append(pd.Series(log_ret, index=idx))
    if not pieces:
        return pd.Series(
            [], index=pd.MultiIndex.from_arrays([[], []], names=_INDEX_NAMES),
            dtype="float64",
        )
    result: pd.Series = pd.concat(pieces).sort_index()
    return result
