"""Cost-honest, gap-aware triple-barrier meta-labels (alphaDesign.md §5.2-§5.3).

Each labeling event is a decision taken at the close of bar τ (availability ``τ + Δ``).
The position is entered at the **next open** ``O(τ + Δ)`` and held until the first of
three barriers is touched:

* a **profit-take** horizontal barrier ``up`` (always in the direction of ``side``),
* a **stop-loss** horizontal barrier ``dn`` (the adverse direction), or
* a **vertical** barrier ``H`` bars after entry — exited at the *next open*
  ``O(τ + (1 + H)·Δ)``, never an unobtainable close ``C_{τ+H}`` (leakageCritique
  finding 24).

The barrier half-width is the H-bar volatility forecast in log-return units,
``w = sigma_hat(τ)·sqrt(H)`` with ``sigma_hat(τ)`` the per-bar EWMA vol read at the decision bar
(point-in-time — bar τ's close is known at ``τ + Δ``). ``sigma_hat`` is computed on the
COMPLETE expected-bar grid per instrument (closes reindexed to
:func:`alphaforge.core.time.expected_bar_opens` before :func:`ewma_vol`), so a data
gap near τ neither inflates the barrier width nor lets later bars change an
already-resolved label — the width is truncation-invariant (leakageCritique
finding 8).

**Cost honesty (leakageCritique finding 11 — the whole point of this module).** The
gross trader-PnL log return ``ret_gross = s·ln(exit/p0)`` is a DIAGNOSTIC ONLY. The
label's economic truth nets out the round-trip frictions actually incurred over the
hold::

    ret = ret_gross - roundtrip_cost_frac - funding_cost_frac

where ``roundtrip_cost_frac = 2·(fee_frac(TAKER) + half_spread_frac)`` from the single
shared :class:`~alphaforge.costs.model.TransactionCostModel` (entry + exit; TAKER is
the conservative liquidity assumption for a barrier/stop exit). Market impact is
deliberately omitted at label time — order size is unknown here, so impact is a sizing
concern handled by the truth engine's fills, exactly as
:meth:`TransactionCostModel.oneway_cost_frac` documents. The classifier therefore
learns ``P(net win)``, not ``P(gross win)``.

**Funding sign convention (leakageCritique finding 3, cross-referencing
:mod:`alphaforge.features.library.carry`).** On Binance USDT-M perps a funding rate
``f > 0`` means **longs PAY shorts** at each settlement, so the per-settlement funding
PnL for a position of side ``s`` is ``- s·f`` (a long with ``f>0`` pays). The funding
COST subtracted from ``ret_gross`` is therefore ``+ s·f̂·n_funding``: a long (``s=+1``)
paying positive funding loses return, and a short (``s=-1``) receiving it gains. The
expectation ``f̂`` is the last funding rate published by the decision (``available_at
<= τ + Δ``) — using realized future rates would be lookahead (findings 6/18); it is
the RAW stored ``rate`` (the single negation lives in :mod:`carry`, never duplicated
here). ``n_funding`` is the count of *scheduled* settlements in the half-open hold
``[entry_ts, t1)`` (a settlement at entry is counted, at exit is not — leakageCritique
finding 17), from the deterministic
:meth:`~alphaforge.core.calendar.TradingCalendar.funding_events_in` clock (a clock is
allowed for COUNTING events, never for RATES).

**Gap-aware fills (leakageCritique finding 11(a)/(b)).** A resting stop or PT does not
fill at the barrier price when the bar *gapped through* it. A stop fills at the WORSE
of {barrier, bar open} for the trader (a gap-down through a long stop fills below the
stop); a PT fills at the barrier limit and never better than it. When both barriers are
touched within a single bar the path is unknown, so the production rule is the
CONSERVATIVE stop-first resolution (``touch = -1``).

Gap discipline: every entry/exit/path bar is fetched by exact ``ts_open`` arithmetic
(``+ k·Δ``), never positional ``shift``. A missing entry bar, a missing sigma_hat, or a
missing interior path bar yields a NaN-price sentinel row (``label_tb = touch = 0``,
NaN prices/returns) — gaps are NEVER bridged, because a live system could not have
traded a bar that did not print. Consumers drop sentinels on ``entry_price.isna()`` /
NaN ``t1`` (the contract :mod:`alphaforge.labeling.weights` relies on).

The label looks into the future by construction: it is a training/evaluation TARGET
ONLY and must never re-enter the feature path. This module never mutates its inputs.

**Cost-honesty bounds, but does not eliminate, overfit risk** (overfit-critique item
8): impact is omitted (optimistic on thin alts) and ``f̂`` is a flat-rate expectation
over the hold (label noise in a funding-regime flip). Label-space win-rate is a
development diagnostic — the binding economic check is the gated walk-forward net of
costs through the truth engine, never a barrier-label hit rate.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from alphaforge.core.calendar import TradingCalendar, calendar_for
from alphaforge.core.time import Timeframe
from alphaforge.core.types import Liquidity, MarketType
from alphaforge.features.library.vol import EWMA_VOL_SPAN, ewma_vol

if TYPE_CHECKING:
    from alphaforge.core.instruments import Instrument
    from alphaforge.costs.model import TransactionCostModel

__all__ = ["TripleBarrierConfig", "apply_triple_barrier"]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_INDEX_NAMES: Final[tuple[str, str]] = ("ts_open", "instrument_id")

_BAR_COLUMNS: Final[frozenset[str]] = frozenset(
    {"instrument_id", "ts_open", "open", "high", "low", "close"}
)
_EVENT_COLUMNS: Final[frozenset[str]] = frozenset({"ts", "instrument_id", "side"})

#: Output frame columns in canonical (alphaDesign §4.3) order with their dtypes.
#: ``t1`` is float64 (not the schema's nominal int64) so unresolved events carry a
#: NaN sentinel — the contract :mod:`alphaforge.labeling.weights` consumes via
#: ``t1.notna()`` then ``int(row["t1"])`` (resolved values are whole-number floats).
_OUTPUT_DTYPES: Final[dict[str, str]] = {
    "entry_ts": "int64",
    "entry_price": "float64",
    "t1": "float64",
    "exit_price": "float64",
    "ret_gross": "float64",
    "ret": "float64",
    "label_tb": "int8",
    "touch": "int8",
    "side": "int8",
    "meta_label": "int8",
    "vol_at_entry": "float64",
    "n_funding": "int8",
}


@dataclass(frozen=True, slots=True)
class TripleBarrierConfig:
    """Geometry and cost knobs for :func:`apply_triple_barrier`.

    Attributes:
        horizon_bars: Vertical barrier ``H`` in bars (default 72 = 3 days @ 1h).
        pt_mult: Profit-take barrier as a multiple of ``w = sigma_hat(τ)·sqrt(H)`` (> 0).
        sl_mult: Stop-loss barrier multiple of ``w`` (> 0). Symmetric defaults
            (both 1.0) make ~half of events touch a horizontal barrier under a
            diffusive null — informative without degenerating to all-vertical.
        vol_span: EWMA span for ``sigma_hat`` (default :data:`EWMA_VOL_SPAN` = 168).
        vertical_zero_band: At a vertical exit, ``label_tb = 0`` when
            ``|ret| < vertical_zero_band·w`` (a dead-zone around break-even). 0
            disables the band (every vertical gets a signed label).
        timeframe: Bar timeframe Δ (default 1h).
        cost_honest: When True, ``ret`` nets fees + half-spread + expected funding;
            ``ret_gross`` is always kept as a diagnostic. When False, ``ret ==
            ret_gross`` and ``funding`` may be omitted.
        use_numba: Opt-in JIT first-touch loop. The pure-numpy path is the contract
            and the default; the JIT path must be bit-identical (atol 0) and raises
            if numba is unavailable when explicitly requested.
    """

    horizon_bars: int = 72
    pt_mult: float = 1.0
    sl_mult: float = 1.0
    vol_span: int = EWMA_VOL_SPAN
    vertical_zero_band: float = 0.0
    timeframe: Timeframe = Timeframe.H1
    cost_honest: bool = True
    use_numba: bool = False

    def __post_init__(self) -> None:
        if self.horizon_bars <= 0:
            raise ValueError(f"horizon_bars must be > 0; got {self.horizon_bars}")
        if self.pt_mult <= 0.0:
            raise ValueError(f"pt_mult must be > 0; got {self.pt_mult}")
        if self.sl_mult <= 0.0:
            raise ValueError(f"sl_mult must be > 0; got {self.sl_mult}")
        if self.vol_span < 1:
            raise ValueError(f"vol_span must be >= 1; got {self.vol_span}")
        if self.vertical_zero_band < 0.0:
            raise ValueError(
                f"vertical_zero_band must be >= 0; got {self.vertical_zero_band}"
            )


def _validate_bars(bars: pd.DataFrame) -> None:
    """Validate the OHLC panel (columns, dtype, uniqueness, positive prices)."""
    missing = _BAR_COLUMNS - set(bars.columns)
    if missing:
        raise ValueError(f"bars is missing required columns: {sorted(missing)}")
    if not pd.api.types.is_integer_dtype(bars["ts_open"]):
        raise TypeError(
            f"ts_open must be int64 epoch-ms UTC; got dtype {bars['ts_open'].dtype}"
        )
    if bars.duplicated(["instrument_id", "ts_open"]).any():
        raise ValueError("bars contains duplicate (instrument_id, ts_open) rows")
    for col in ("open", "high", "low", "close"):
        values = bars[col].to_numpy(dtype=float)
        finite = values[np.isfinite(values)]
        if not np.all(finite > 0.0):
            raise ValueError(f"bars contains non-positive {col!r} prices; log returns undefined")


def _validate_events(events: pd.DataFrame) -> None:
    """Validate the events frame (columns, dtype, uniqueness, side domain)."""
    missing = _EVENT_COLUMNS - set(events.columns)
    if missing:
        raise ValueError(f"events is missing required columns: {sorted(missing)}")
    if not pd.api.types.is_integer_dtype(events["ts"]):
        raise TypeError(
            f"events.ts must be int64 epoch-ms UTC; got dtype {events['ts'].dtype}"
        )
    if events.duplicated(["ts", "instrument_id"]).any():
        raise ValueError("events contains duplicate (ts, instrument_id) rows")
    sides = events["side"].to_numpy()
    if not np.all(np.isin(sides, (-1, 1))):
        raise ValueError("events.side must be in {-1, +1}")


def _grid_sigma(close: pd.Series, ts: np.ndarray, span: int, step: int) -> pd.Series:
    """Per-bar EWMA sigma_hat on the COMPLETE expected-bar grid (leakageCritique finding 8).

    ``close``/``ts`` are one instrument's stored closes ordered by ``ts_open``. The
    closes are reindexed onto the gap-free grid ``[ts[0], ts[-1]]`` (step Δ) BEFORE
    :func:`ewma_vol`, so a gap-spanning return never widens the barrier and the sigma_hat at
    any τ is identical whether or not later bars exist (truncation-invariant). The
    result is reindexed back to the stored ``ts`` (gap slots have no event anyway).
    """
    grid = np.arange(int(ts[0]), int(ts[-1]) + step, step, dtype=np.int64)
    on_grid = pd.Series(close.to_numpy(dtype=float), index=ts).reindex(grid)
    sigma_grid = ewma_vol(on_grid.to_frame("close"), span=span)["close"]
    return sigma_grid.reindex(ts)


def _funding_asof(
    funding: pd.DataFrame, instrument_id: str, decision_ts: np.ndarray
) -> np.ndarray:
    """Last-known funding ``rate`` per decision instant for one instrument.

    Reuses the sanctioned backward as-of mechanics of
    :meth:`FeatureContext.funding_asof_join` (sort by ``available_at``,
    ``direction="backward"``, ``allow_exact_matches=True``): for each decision
    ``τ + Δ`` the value is the rate with ``available_at <= τ + Δ``, NaN before the
    first published settlement. The returned RAW ``rate`` is negated nowhere — the
    single funding-sign negation lives in the cost arithmetic (module docstring).
    """
    rows = funding[funding["instrument_id"] == instrument_id]
    if rows.empty:
        return np.full(len(decision_ts), np.nan, dtype=float)
    order = np.argsort(decision_ts, kind="stable")
    left = pd.DataFrame({"decision_ts": decision_ts[order]})
    right = rows[["rate", "available_at"]].sort_values("available_at", kind="stable")
    merged = pd.merge_asof(
        left,
        right,
        left_on="decision_ts",
        right_on="available_at",
        direction="backward",
        allow_exact_matches=True,
    )
    out = np.full(len(decision_ts), np.nan, dtype=float)
    out[order] = merged["rate"].to_numpy(dtype=float)
    return out


def _roundtrip_cost_frac(cost_model: TransactionCostModel, inst: Instrument) -> float:
    """Notional-independent round-trip cost: ``2·(fee(TAKER) + half_spread)``.

    Entry + exit (the ``2x``); TAKER is the conservative liquidity assumption for a
    barrier/stop exit. Impact is omitted (size unknown at label time) and latency
    lives in :meth:`TransactionCostModel.fill_price`, not the economic penalty —
    exactly as :meth:`TransactionCostModel.oneway_cost_frac` documents.
    """
    oneway = cost_model.fee_frac(inst, Liquidity.TAKER) + cost_model.half_spread_frac(inst)
    return 2.0 * oneway


def _scan_one_instrument(
    *,
    ts: np.ndarray,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    sigma: np.ndarray,
    event_ts: np.ndarray,
    event_side: np.ndarray,
    cfg: TripleBarrierConfig,
    calendar: TradingCalendar,
) -> dict[str, np.ndarray]:
    """Pure-numpy first-touch scan for one instrument (the labeling contract).

    ``ts``/``open_``/``high``/``low``/``sigma`` are the instrument's stored bars ordered
    by ``ts_open`` (``sigma`` is sigma_hat at each bar). ``event_ts``/``event_side`` are the
    decision τ and side of every event for this instrument. Returns geometry arrays
    (``entry_ts``, ``entry_price``, ``t1``, ``exit_price``, ``ret_gross``, ``label_tb``,
    ``touch``, ``vol_at_entry``) aligned to ``event_ts``; an unresolved event carries
    NaN prices / sentinel ``t1 = -1`` and ``label_tb = touch = 0``.

    Bar hops walk the ``calendar`` sessions, never a fixed ``+Δ``: the entry bar is
    ``calendar.next_bar_open(τ, tf)`` and each subsequent path/vertical bar is the next
    session open. For the 24/7 crypto calendar this reduces *exactly* to the prior
    ``τ + (1 + k)·Δ`` arithmetic (``next_bar_open(t, H1) == t + H1.ms``), so the crypto
    labels are byte-identical; for an XNYS session calendar a hold spanning a weekend
    hops Friday→Monday instead of falling into a phantom (missing) weekend slot.
    """
    tf = cfg.timeframe
    horizon = cfg.horizon_bars
    n = len(event_ts)

    # Exact ts_open -> positional index for O(1) "+k·Δ" lookups (no positional shift).
    pos_of: dict[int, int] = {int(t): i for i, t in enumerate(ts)}

    entry_ts = np.empty(n, dtype=np.int64)
    entry_price = np.full(n, np.nan, dtype=float)
    t1 = np.full(n, -1, dtype=np.int64)
    exit_price = np.full(n, np.nan, dtype=float)
    ret_gross = np.full(n, np.nan, dtype=float)
    label_tb = np.zeros(n, dtype=np.int8)
    touch = np.zeros(n, dtype=np.int8)
    vol_at_entry = np.full(n, np.nan, dtype=float)

    for e in range(n):
        tau = int(event_ts[e])
        side = int(event_side[e])
        # Entry at the next session open O(τ): +Δ on the 24/7 calendar, Fri->Mon on XNYS.
        ent_ts = calendar.next_bar_open(tau, tf)
        entry_ts[e] = ent_ts

        # The hold's session opens: entry, then the next ``horizon`` sessions. Path bar k
        # (k=1..horizon) is ``path_opens[k]``; the vertical bar is ``path_opens[horizon]``.
        # On 24/7 ``path_opens[k] == tau + (1 + k)·Δ`` exactly (byte-identical).
        path_opens = [ent_ts]
        cursor = ent_ts
        for _ in range(horizon):
            cursor = calendar.next_bar_open(cursor, tf)
            path_opens.append(cursor)

        # sigma_hat is read at the decision bar τ (PIT). sigma_hat NaN/non-positive => NaN label.
        tau_pos = pos_of.get(tau)
        sig = float(sigma[tau_pos]) if tau_pos is not None else np.nan
        vol_at_entry[e] = sig

        ent_pos = pos_of.get(ent_ts)
        if ent_pos is None or not (sig > 0.0):
            continue  # missing entry bar or unusable sigma_hat -> NaN sentinel row

        p0 = float(open_[ent_pos])
        entry_price[e] = p0
        w = sig * np.sqrt(float(horizon))
        if side > 0:
            up = p0 * np.exp(cfg.pt_mult * w)  # profit-take (above)
            dn = p0 * np.exp(-cfg.sl_mult * w)  # stop-loss (below)
        else:
            up = p0 * np.exp(cfg.sl_mult * w)  # stop-loss (above)
            dn = p0 * np.exp(-cfg.pt_mult * w)  # profit-take (below)

        resolved = False
        gapped = False
        for k in range(1, horizon + 1):
            bar_ts = path_opens[k]
            bpos = pos_of.get(bar_ts)
            if bpos is None:
                gapped = True  # interior path bar missing -> NaN (never bridge)
                break
            hi = float(high[bpos])
            lo = float(low[bpos])
            ok = float(open_[bpos])
            hit_up = hi >= up
            hit_dn = lo <= dn
            if not (hit_up or hit_dn):
                continue

            # Resolve which barrier (stop-first when both touched in one bar).
            if side > 0:
                stop_hit = hit_dn
                stop_lvl, pt_lvl = dn, up
            else:
                stop_hit = hit_up
                stop_lvl, pt_lvl = up, dn

            if stop_hit:  # stop (and possibly PT) -> conservative stop-first
                touch[e] = -1
                label_tb[e] = np.int8(-side)
                # Gap-aware: a stop fills at the WORSE of {barrier, open} for the trader.
                # WORSE => more adverse: for a long that is the lower price; for a short
                # the higher price. side·ln(px/p0) smaller is worse.
                if side > 0:
                    px = stop_lvl if ok >= stop_lvl else ok
                else:
                    px = stop_lvl if ok <= stop_lvl else ok
                exit_price[e] = px
            else:  # PT only -> resting limit, fills AT the barrier (never better)
                touch[e] = 1
                label_tb[e] = np.int8(side)
                exit_price[e] = pt_lvl
            t1[e] = bar_ts
            ret_gross[e] = side * np.log(exit_price[e] / p0)
            resolved = True
            break

        if gapped:
            # Interior bar missing: cannot have traded the hold -> NaN sentinel
            # (t1 stays -1, ret_gross stays NaN; scrub the entry price too).
            entry_price[e] = np.nan
            continue
        if resolved:
            continue

        # Vertical barrier: exit at the NEXT OPEN O(τ + (1+H)·Δ) = the H-th session open
        # after entry, never a close (the same instant as the last path bar above).
        vert_ts = path_opens[horizon]
        vpos = pos_of.get(vert_ts)
        if vpos is None:
            entry_price[e] = np.nan  # vertical bar missing -> NaN sentinel
            continue
        px = float(open_[vpos])
        t1[e] = vert_ts
        exit_price[e] = px
        touch[e] = 0
        rg = side * np.log(px / p0)
        ret_gross[e] = rg
        if abs(rg) < cfg.vertical_zero_band * w:
            label_tb[e] = np.int8(0)
        else:
            label_tb[e] = np.int8(1 if rg > 0.0 else -1)

    return {
        "entry_ts": entry_ts,
        "entry_price": entry_price,
        "t1": t1,
        "exit_price": exit_price,
        "ret_gross": ret_gross,
        "label_tb": label_tb,
        "touch": touch,
        "vol_at_entry": vol_at_entry,
    }


def apply_triple_barrier(
    bars: pd.DataFrame,
    events: pd.DataFrame,
    cfg: TripleBarrierConfig,
    *,
    cost_model: TransactionCostModel,
    instruments: Mapping[str, Instrument],
    funding: pd.DataFrame | None = None,
    vol: pd.Series | None = None,
) -> pd.DataFrame:
    """First-touch triple-barrier labels, COST-HONEST and gap-aware.

    See the module docstring for the full algorithm, sign conventions and leakage
    discipline. This function labels EXACTLY the events handed to it (dead-zone
    filtering of weak signals is the caller's job in :mod:`alphaforge.labeling.meta`).

    Parameters
    ----------
    bars:
        Long OHLC panel: ``instrument_id``, ``ts_open`` (int64 epoch-ms UTC),
        ``open``, ``high``, ``low``, ``close``. One row per (instrument, bar);
        duplicates, non-integer ``ts_open`` and non-positive prices raise. Never
        mutated.
    events:
        One row per labeling decision: ``ts`` (int64 epoch-ms = the decision bar τ's
        ``ts_open``), ``instrument_id``, ``side`` (int8 in {-1, +1}; a side-less
        primary run passes all +1). Duplicate ``(ts, instrument_id)`` raises.
    cfg:
        Geometry and cost knobs.
    cost_model:
        The single shared :class:`~alphaforge.costs.model.TransactionCostModel`
        (never reimplemented here).
    instruments:
        ``instrument_id -> Instrument`` for ``funding_interval_hours`` and market-type
        routing. A perp event whose instrument is absent raises ``KeyError`` (metadata
        is mandatory).
    funding:
        Funding-events frame (``ts_funding``, ``instrument_id``, ``rate``,
        ``available_at``; int64 ms except ``rate``). May be ``None`` only when
        ``cfg.cost_honest is False`` or the universe is spot-only; a perp with
        ``cost_honest`` and no funding row contributes ``E[funding] = 0`` (logged).
    vol:
        Optional externally-supplied per-bar sigma_hat on the ``(ts_open, instrument_id)``
        MultiIndex. When omitted, sigma_hat is computed on the complete expected-bar grid
        from ``close`` (span ``cfg.vol_span``). sigma_hat is read at the decision bar τ.

    Returns
    -------
    pd.DataFrame
        The §1.3 label frame indexed by the sorted ``(ts_open, instrument_id)``
        MultiIndex (``ts_open`` == decision τ), with the columns of
        :data:`_OUTPUT_DTYPES`. Unresolved events (missing entry / sigma_hat / path bar)
        are NaN-price sentinel rows (``label_tb = touch = meta_label = 0``, NaN
        prices/returns, ``entry_ts`` still populated); consumers drop them on
        ``entry_price.isna()``.
    """
    _validate_bars(bars)
    _validate_events(events)
    if cfg.use_numba:  # pragma: no cover - JIT path is opt-in and platform-gated
        raise NotImplementedError(
            "use_numba=True requested but numba is not available on this platform; "
            "the pure-numpy path is the bit-identical contract — leave use_numba=False"
        )
    if vol is not None and not isinstance(vol.index, pd.MultiIndex):
        raise ValueError("vol must be indexed by a (ts_open, instrument_id) MultiIndex")
    if cfg.cost_honest and funding is None:
        # Allowed only when no perp event needs funding; verified per-event below.
        _LOGGER.debug("cost_honest with funding=None; perps will use E[funding]=0")

    delta = cfg.timeframe.ms
    # Stable cross-instrument ordering for grouping; numpy scan per instrument.
    pieces: list[pd.DataFrame] = []
    for instrument_id, ev_group in events.groupby("instrument_id", sort=True):
        iid = str(instrument_id)
        if iid not in instruments:
            raise KeyError(f"no Instrument metadata for {iid!r} (required for labeling)")
        inst = instruments[iid]

        bar_group = bars[bars["instrument_id"] == iid].sort_values("ts_open")
        if bar_group.empty:
            ts = np.empty(0, dtype=np.int64)
            open_ = high = low = sigma = np.empty(0, dtype=float)
        else:
            ts = bar_group["ts_open"].to_numpy(dtype=np.int64)
            open_ = bar_group["open"].to_numpy(dtype=float)
            high = bar_group["high"].to_numpy(dtype=float)
            low = bar_group["low"].to_numpy(dtype=float)
            close = pd.Series(bar_group["close"].to_numpy(dtype=float), index=ts)
            if vol is not None:
                # Externally supplied sigma_hat must be on the full grid; reindex to τ rows.
                iid_level = vol.index.get_level_values("instrument_id")
                if (iid_level == iid).any():
                    supplied = vol.xs(iid, level="instrument_id")
                    sigma = supplied.reindex(ts).to_numpy(dtype=float)
                else:
                    sigma = np.full(len(ts), np.nan, dtype=float)
            else:
                sigma = _grid_sigma(close, ts, cfg.vol_span, delta).to_numpy(dtype=float)

        ev_sorted = ev_group.sort_values("ts")
        event_ts = ev_sorted["ts"].to_numpy(dtype=np.int64)
        event_side = ev_sorted["side"].to_numpy(dtype=np.int64)

        # The ONE calendar seam (already used at :534 for funding counting): the bar
        # walk hops its sessions instead of a fixed +Δ. Crypto resolves the 24/7
        # calendar, so the walk reduces to ``τ + (1 + k)·Δ`` and labels are byte-identical.
        cal = calendar_for(inst.asset_class)

        scan = _scan_one_instrument(
            ts=ts,
            open_=open_,
            high=high,
            low=low,
            sigma=sigma,
            event_ts=event_ts,
            event_side=event_side,
            cfg=cfg,
            calendar=cal,
        )

        # --- cost-honest net return + funding (per-instrument, vectorized) -----
        ret_gross = scan["ret_gross"]
        side_arr = event_side.astype(float)
        n_events = len(event_ts)
        n_funding = np.zeros(n_events, dtype=np.int64)
        funding_cost = np.zeros(n_events, dtype=float)

        is_perp = inst.market_type is MarketType.PERP
        if cfg.cost_honest:
            roundtrip = _roundtrip_cost_frac(cost_model, inst)
            if is_perp:
                interval = inst.funding_interval_hours
                assert interval is not None  # perps require it (Instrument invariant)
                # ``cal`` resolved above (the same calendar drives the bar walk);
                # availability stays pure-integer (τ + Δ), never a session hop.
                decision_ts = event_ts + delta
                f_hat = (
                    _funding_asof(funding, iid, decision_ts)
                    if funding is not None
                    else np.full(n_events, np.nan, dtype=float)
                )
                for e in range(n_events):
                    if scan["t1"][e] < 0:
                        continue  # unresolved -> no funding accrues to a NaN label
                    n_set = len(
                        cal.funding_events_in(
                            int(scan["entry_ts"][e]), int(scan["t1"][e]), interval
                        )
                    )
                    n_funding[e] = n_set
                    rate = f_hat[e]
                    if np.isnan(rate):
                        if n_set > 0:
                            _LOGGER.debug(
                                "no published funding rate as-of decision for %s; E[funding]=0", iid
                            )
                        rate = 0.0
                    # COST subtracted = + s·f̂·n_funding (long pays when f>0; carry.py).
                    funding_cost[e] = side_arr[e] * rate * n_set
            with np.errstate(invalid="ignore"):
                ret = ret_gross - roundtrip - funding_cost
        else:
            ret = ret_gross.copy()

        # meta_label = 1{ net ret > 0 }, on the SIDE-SIGNED net return (finding 2).
        meta_label = np.where(np.isnan(ret), 0, (ret > 0.0).astype(np.int8)).astype(np.int8)

        index = pd.MultiIndex.from_arrays(
            [event_ts, np.full(n_events, iid)], names=_INDEX_NAMES
        )
        frame = pd.DataFrame(
            {
                "entry_ts": scan["entry_ts"],
                "entry_price": scan["entry_price"],
                # sentinel t1 = -1 (unresolved) is surfaced to consumers as NaN.
                "t1": scan["t1"],
                "exit_price": scan["exit_price"],
                "ret_gross": ret_gross,
                "ret": ret,
                "label_tb": scan["label_tb"],
                "touch": scan["touch"],
                "side": event_side.astype(np.int8),
                "meta_label": meta_label,
                "vol_at_entry": scan["vol_at_entry"],
                "n_funding": np.clip(n_funding, 0, np.iinfo(np.int8).max).astype(np.int8),
            },
            index=index,
        )
        # Unresolved (sentinel t1 == -1) rows: surface t1 as NaN, scrub stale geometry.
        unresolved = frame["t1"].to_numpy() < 0
        if unresolved.any():
            frame["entry_price"] = frame["entry_price"].where(~unresolved, other=np.nan)
            frame["exit_price"] = frame["exit_price"].where(~unresolved, other=np.nan)
            frame["ret_gross"] = frame["ret_gross"].where(~unresolved, other=np.nan)
            frame["ret"] = frame["ret"].where(~unresolved, other=np.nan)
        pieces.append(frame)

    if not pieces:
        empty_index = pd.MultiIndex.from_arrays([[], []], names=_INDEX_NAMES)
        result = pd.DataFrame(
            {c: pd.Series([], dtype=dt) for c, dt in _OUTPUT_DTYPES.items()},
            index=empty_index,
        )
        return result

    result = pd.concat(pieces).sort_index()
    # t1 carries a -1 sentinel for unresolved rows; promote to a nullable-free float
    # only where the consumer expects NaN. We keep int64 t1 with -1 reinterpreted as
    # NaN via a float cast (weights.py reads t1.notna()).
    t1_float = result["t1"].astype("float64")
    t1_float[result["t1"].to_numpy() < 0] = np.nan
    result["t1"] = t1_float
    # entry_ts is always meaningful (the would-be entry bar); keep it int64.
    result["entry_ts"] = result["entry_ts"].astype("int64")
    result["side"] = result["side"].astype("int8")
    result["label_tb"] = result["label_tb"].astype("int8")
    result["touch"] = result["touch"].astype("int8")
    result["meta_label"] = result["meta_label"].astype("int8")
    result["n_funding"] = result["n_funding"].astype("int8")
    # Canonical column order.
    return result[list(_OUTPUT_DTYPES)]
