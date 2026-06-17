"""FeatureEngine — one function body, two windows: batch history and live as-of.

The anti-skew core (dataDesign.md §7.1, leakage finding 3): research/backtest calls
:meth:`FeatureEngine.compute_history` (one vectorized pass over years), the live loop
calls :meth:`FeatureEngine.compute_asof` (minimal window sized by
``max(lookback_bars)``). Both build a :class:`~alphaforge.features.context.FeatureContext`
and execute the IDENTICAL registered function objects; the only difference is the
window of PIT data placed in the context. Skew therefore reduces to window-boundary
bugs, which :mod:`alphaforge.features.parity` catches mechanically — parity is the
contract: at the same timestamp, finite-window features must agree bit-for-bit
(atol=0) and EWMA-family features to 1e-9 relative.

Why a single batch read at ``as_of = end`` stays PIT per-timestamp inside the window:
prices/volume are uniformly available (a bar available at its close is available
forever after), funding is handled per-row by
:meth:`~alphaforge.features.context.FeatureContext.funding_asof_join` on the stored
``available_at``, and quality flags — the one surface whose state genuinely depends on
the evaluation time — are not consumed by v1 library features and carry an explicit
per-row lagging contract in the context docs for anything that ever does.

Anchor timeframe: v1 features are valued on the 1h grid (alphaDesign.md conventions);
``lookback_bars`` and the engine's window arithmetic are in 1h bars. Features may
still read 4h/1d bars through ``ctx.bars(tf)`` within the same time window.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pandas as pd

from alphaforge.config.sleeve import CRYPTO_PERP_SLEEVE
from alphaforge.core.calendar import TradingCalendar, calendar_for
from alphaforge.core.time import Ms, Timeframe, bar_open_for_decision
from alphaforge.core.types import AssetClass
from alphaforge.features.context import FeatureContext

if TYPE_CHECKING:
    from collections.abc import Sequence

    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.spec import FeatureSpec

__all__ = ["ANCHOR_TIMEFRAME", "FeatureEngine"]

#: The crypto sleeve's anchor timeframe, re-exported for the un-migrated importers
#: (``signals/service.py``, ``features/parity.py``, ``research/ic_report.py``) until
#: they resolve their anchor through :func:`~alphaforge.config.sleeve.sleeve_for`. It
#: is defined as ``CRYPTO_PERP_SLEEVE.anchor_tf`` (``Timeframe.H1``) so the symbol IS
#: the crypto default — byte-identical to the old module constant — and the engine
#: itself no longer reads it (it reads its per-instance ``_anchor_tf``).
ANCHOR_TIMEFRAME: Final[Timeframe] = CRYPTO_PERP_SLEEVE.anchor_tf
"""The crypto sleeve's anchor TF (``Timeframe.H1``); ``lookback_bars`` counts bars of
the per-sleeve anchor timeframe (this constant is the crypto default)."""


class FeatureEngine:
    """Computes registered features over PIT windows (see module docstring).

    The engine is valued on its sleeve's **anchor timeframe** and builds every grid
    from the sleeve's :class:`~alphaforge.core.calendar.TradingCalendar`. The defaults
    (``anchor_tf=H1``, the 24/7 crypto calendar) reproduce the old hard-coded
    ``ANCHOR_TIMEFRAME``/``expected_bar_opens`` behavior bit-for-bit; the equity sleeve
    passes ``anchor_tf=D1`` + ``asset_class=EQUITY`` so the grid is XNYS sessions.
    """

    def __init__(
        self,
        reader: PITDataReader,
        instruments: InstrumentStore,
        universe: UniverseStore,
        *,
        anchor_tf: Timeframe = Timeframe.H1,
        asset_class: AssetClass = AssetClass.CRYPTO_PERP,
        calendar: TradingCalendar | None = None,
    ) -> None:
        self._reader = reader
        self._instruments = instruments
        self._universe = universe
        # The sleeve resolution: anchor TF + calendar + asset class. Defaults are the
        # crypto sleeve (H1 + 24/7), byte-identical to the old module constant. The
        # calendar may be passed explicitly or resolved from ``asset_class`` here.
        self._anchor_tf = anchor_tf
        self._asset_class = asset_class
        self._calendar = calendar if calendar is not None else calendar_for(asset_class)

    def compute_history(
        self,
        specs: Sequence[FeatureSpec],
        instrument_ids: Sequence[str],
        *,
        start: Ms,
        end: Ms,
    ) -> pd.DataFrame:
        """Batch pass: all specs over the full grid of ``[start, end)``.

        One PIT context is built with window ``[start - max_lookback·Δ, end)`` and
        ``as_of = end`` — the headroom warms up every spec's window so values at
        ``start`` are already real (provided the lake has the history). Returns a
        float64 frame: MultiIndex ``(ts_open: int64 epoch ms, instrument_id)`` =
        the COMPLETE expected 1h grid of ``[start, end)`` x requested instruments
        (deterministic shape — grid slots without data are NaN rows), one column
        per spec in input order. NaN wherever history is insufficient.

        The value at ``(t, i)`` is a pure function of data available at the bar
        close ``t + Δ`` — equal, by the parity contract, to what
        :meth:`compute_asof` produces live at that instant.
        """
        checked_specs, ids = _checked(specs, instrument_ids)
        self._guard_equity_unverified()
        if end <= start:
            raise ValueError(f"compute_history requires end > start, got [{start}, {end})")
        tf = self._anchor_tf
        max_lookback = max(s.lookback_bars for s in checked_specs)
        ctx = FeatureContext(
            reader=self._reader,
            instruments=self._instruments,
            universe=self._universe,
            instrument_ids=ids,
            start=start - max_lookback * tf.ms,
            end=end,
            calendar=self._calendar,
            asset_class=self._asset_class,
        )
        grid = self._calendar.expected_bar_opens(start, end, tf)
        target = pd.MultiIndex.from_product([grid, ids], names=("ts_open", "instrument_id"))
        return _compute(ctx, checked_specs, target)

    def compute_asof(
        self,
        specs: Sequence[FeatureSpec],
        instrument_ids: Sequence[str],
        *,
        as_of: Ms,
    ) -> pd.DataFrame:
        """Live pass: one row per instrument at the last bar available at ``as_of``.

        The decision bar is ``t* = bar_open_for_decision(as_of, 1h)`` (greatest
        ``ts_open`` with ``ts_open + Δ <= as_of``). The context window is the
        MINIMAL one: exactly ``max(lookback_bars)`` grid slots ending at ``t*``,
        i.e. ``[t* - (L_max - 1)·Δ, t* + Δ)`` with ``as_of = t* + Δ`` — the live
        path proves, every bar, that the declared lookbacks are sufficient.
        Returns a float64 frame indexed by ``(t*, instrument_id)`` for ALL
        requested instruments (NaN row where an instrument has no data), one
        column per spec in input order.

        PARITY IS THE CONTRACT: this result must equal :meth:`compute_history`
        at the same ``t*`` — exactly (atol=0) for finite-window specs; to 1e-9
        relative for EWMA-family specs (documented truncation convention,
        ``lookback_bars >= 10·span``). Enforced by
        :func:`alphaforge.features.parity.verify_parity` in CI and ops.
        """
        checked_specs, ids = _checked(specs, instrument_ids)
        self._guard_equity_unverified()
        tf = self._anchor_tf
        max_lookback = max(s.lookback_bars for s in checked_specs)
        t_star = bar_open_for_decision(as_of, tf)
        ctx = FeatureContext(
            reader=self._reader,
            instruments=self._instruments,
            universe=self._universe,
            instrument_ids=ids,
            start=t_star - (max_lookback - 1) * tf.ms,
            end=t_star + tf.ms,
            calendar=self._calendar,
            asset_class=self._asset_class,
        )
        target = pd.MultiIndex.from_product([[t_star], ids], names=("ts_open", "instrument_id"))
        return _compute(ctx, checked_specs, target)

    def _guard_equity_unverified(self) -> None:
        """Fail-closed on EQUITY/D1 specs until the equity spine is verified in this arc.

        The calendar-aware grid (batch) and the corp-actions read path are wired, but
        the equity as-of *window* arithmetic and the ``forward_returns`` /
        ``estimate_blend_weights`` session hops are NOT yet verified (SPINE_ARC §3.1,
        §3.6, §8). Rather than silently compute equity features on a partially-migrated
        path, the engine refuses EQUITY/D1 specs loudly. CRYPTO_PERP/H1 never trips it,
        so the crypto path is unchanged. Removed once the equity E2E parity is green.
        """
        if self._asset_class is AssetClass.EQUITY or self._anchor_tf is Timeframe.D1:
            raise NotImplementedError(
                "FeatureEngine rejects EQUITY/D1 specs in this arc: the calendar-aware "
                "spine is wired but the equity as-of window + forward_returns/blend "
                "session hops are not yet verified; refusing to silently compute on a "
                "partially-migrated path (SPINE_ARC §4)."
            )


def _checked(
    specs: Sequence[FeatureSpec], instrument_ids: Sequence[str]
) -> tuple[list[FeatureSpec], list[str]]:
    """Validate and normalize the (specs, instrument_ids) pair."""
    spec_list = list(specs)
    if not spec_list:
        raise ValueError("at least one FeatureSpec is required")
    seen: set[str] = set()
    for spec in spec_list:
        if spec.name in seen:
            raise ValueError(f"duplicate spec name {spec.name!r} in compute request")
        seen.add(spec.name)
    ids = list(dict.fromkeys(instrument_ids))
    if not ids:
        raise ValueError("at least one instrument_id is required")
    return spec_list, ids


def _compute(ctx: FeatureContext, specs: list[FeatureSpec], target: pd.MultiIndex) -> pd.DataFrame:
    """Run each spec's fn on ``ctx``, validate output shape, align to ``target``.

    Alignment by reindex: rows the fn emitted outside the target (the warm-up
    headroom) are dropped; target rows the fn omitted become NaN. Output dtype is
    forced to float64 so parity comparisons are exact.
    """
    columns: dict[str, pd.Series] = {}
    for spec in specs:
        out = spec.fn(ctx, spec)
        if not isinstance(out, pd.Series):
            raise TypeError(
                f"feature {spec.name!r} returned {type(out).__name__}; the FeatureFn "
                "contract requires a pandas Series"
            )
        if out.index.nlevels != 2:
            raise ValueError(
                f"feature {spec.name!r} returned a {out.index.nlevels}-level index; "
                "the contract is a 2-level (ts_open, instrument_id) MultiIndex"
            )
        if out.index.has_duplicates:
            raise ValueError(
                f"feature {spec.name!r} returned duplicate (ts_open, instrument_id) index entries"
            )
        aligned = out.astype("float64").rename(spec.name)
        aligned.index = aligned.index.set_names(["ts_open", "instrument_id"])
        columns[spec.name] = aligned.reindex(target)
    return pd.DataFrame(columns, index=target)
