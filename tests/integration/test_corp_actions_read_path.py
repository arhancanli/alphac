"""Integration regression for the corporate-actions READ PATH (SPINE_ARC P1, §2.4).

The end-to-end proof that the split/dividend read path is wired and PIT-correct:
``PITDataReader.corporate_actions`` (masking on the stored ``available_at``, never
``ex_date``) → ``FeatureContext.corporate_actions`` (the ``_CA_COLUMNS`` projection) →
``equity_price._adjusted_close_panel`` → the registered equity price factors. Before
this arc the read path was absent and ``_adjusted_close_panel`` silently fell back to
RAW unadjusted close — a 2:1 split printed as a ~-69% (ln 0.5) reversal/momentum return.

This planted-split regression asserts the three load-bearing guarantees:

* (a) **No spurious split return at the ex bar** — the 12-1 momentum and 1-month
  reversal across the ex bar are ~0 once the split is folded (would be ~±0.69 raw).
* (b) **Split invisibility before ``available_at``** — a ``compute_history`` whose
  window ends BEFORE the split is knowable sees the RAW (unfolded) price, while a
  window extending past ``available_at`` sees the adjusted price (the per-decision-row
  PIT discipline, the funding-finding-18 trap in equity clothing).
* (c) **Fail-closed when the corp-actions surface is absent** — monkeypatching the
  ``corporate_actions`` getter off makes ``_adjusted_close_panel`` RAISE rather than
  silently feed raw prices to the factors (SPINE_ARC §2.3).

GRID NOTE (identical to tests/unit/test_factors_equity_price.py): the PIT-aware D1
engine (anchor_tf=D1 + XNYSCalendar) compute path is held behind a fail-closed engine
guard in this arc, so the lake is laid on the engine's default crypto H1 anchor grid —
one grid slot == one session bar. The corporate-action availability arithmetic in
``adjusted_close`` uses the explicit ``Timeframe.D1.ms`` lag (SPINE_ARC §2.4), so the
planted action's ``available_at``/``ex_date`` are set on the ``ts_open + D1.ms``
decision line. The read path itself (reader→context) is asset-class-agnostic, so this
exercises the exact production code that the equity sleeve will use.

Offline: a deterministic synthetic tmp lake.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa
import pytest

from alphaforge.core.errors import ConfigError
from alphaforge.core.instruments import InstrumentStore
from alphaforge.core.time import Timeframe
from alphaforge.data.schemas import CORPORATE_ACTIONS_SCHEMA, UNIVERSE_SCHEMA, Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.context import FeatureContext
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.library import equity_price as ep
from alphaforge.features.registry import default_registry

if TYPE_CHECKING:
    from collections.abc import Iterator

AAPL = "XNAS:CASH:AAPLUSD"
MSFT = "XNAS:CASH:MSFTUSD"
SPY = "ARCX:CASH:SPYUSD"
IDS = (AAPL, MSFT, SPY)

HOUR = 3_600_000  # engine anchor step; one slot == one session bar (see GRID NOTE)
DAY = Timeframe.D1.ms  # the explicit availability lag adjusted_close uses (SPINE_ARC §2.4)
T0 = 1_577_836_800_000  # 2020-01-01T00:00:00Z (aligned)
N_BARS = 300  # > max equity lookback (eq_mom = 253) + headroom

EX_K = 270  # the split goes ex at this grid slot
# The split is declared (knowable) early — bar k is knowable iff k*HOUR + DAY >=
# available_at. With DECL_K=20 every bar from slot 20 onward folds the split, so the
# 252/21-session factor windows ending well after the declaration are fully adjusted
# (the realistic "declared weeks/months ahead" case). The genuinely-unadjustable
# pre-declaration bars (k < ~20) are below every factor's warm-up start.
DECL_K = 20
AVAILABLE_AT = T0 + DECL_K * HOUR + DAY
EX_DATE = T0 + EX_K * HOUR


def _walk(seed: int, n: int, level: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return level * np.exp(np.cumsum(rng.normal(0.0, 0.01, n)))


def _raw_closes() -> dict[str, np.ndarray]:
    """Random-walk closes, then HALVE every close at/after the ex slot for AAPL only
    (a 2:1 split: the raw print drops ~50% on the ex bar)."""
    closes = {
        AAPL: _walk(11, N_BARS, 200.0),
        MSFT: _walk(12, N_BARS, 150.0),
        SPY: _walk(13, N_BARS, 400.0),
    }
    closes[AAPL][EX_K:] *= 0.5  # the as-traded 2:1 split halves the post-ex price
    return closes


def _ohlcv_table(closes: dict[str, np.ndarray]) -> pa.Table:
    iids: list[str] = []
    ts: list[int] = []
    px: list[float] = []
    qv: list[float] = []
    for iid, c in closes.items():
        n = len(c)
        iids.extend([iid] * n)
        ts.extend(T0 + k * HOUR for k in range(n))
        px.extend(float(v) for v in c)
        qv.extend(float(1_000_000.0 * v) for v in c)
    n_rows = len(iids)
    return pa.table(
        {
            "instrument_id": pa.array(iids, type=pa.string()),
            "ts_open": pa.array(ts, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array(px, type=pa.float64()),
            "high": pa.array([p * 1.001 for p in px], type=pa.float64()),
            "low": pa.array([p * 0.999 for p in px], type=pa.float64()),
            "close": pa.array(px, type=pa.float64()),
            "volume": pa.array([1000.0] * n_rows, type=pa.float64()),
            "quote_volume": pa.array(qv, type=pa.float64()),
            "n_trades": pa.array([42] * n_rows, type=pa.int64()),
            "quality_flags": pa.array([0] * n_rows, type=pa.int32()),
            "ingested_at": pa.array(
                [t + HOUR + 1000 for t in ts], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def _ca_table() -> pa.Table:
    """One AAPL 2:1 split: ratio 0.5, declared at AVAILABLE_AT, ex at EX_DATE."""
    return pa.table(
        {
            "instrument_id": [AAPL],
            "action_type": ["split"],
            "ex_date": pa.array([EX_DATE], type=pa.timestamp("ms", tz="UTC")),
            "available_at": pa.array([AVAILABLE_AT], type=pa.timestamp("ms", tz="UTC")),
            "ratio": pa.array([0.5], type=pa.float64()),
            "cash_amount": pa.array([None], type=pa.float64()),
            "ingested_at": pa.array([AVAILABLE_AT + 1000], type=pa.timestamp("ms", tz="UTC")),
        },
        schema=CORPORATE_ACTIONS_SCHEMA,
    )


def _universe_table() -> pa.Table:
    return pa.table(
        {
            "instrument_id": list(IDS),
            "effective_from": pa.array([T0] * 3, type=pa.timestamp("ms", tz="UTC")),
            "effective_to": pa.array([None] * 3, type=pa.timestamp("ms", tz="UTC")),
            "rank": pa.array([1, 2, 3], type=pa.int32()),
            "reason": ["enter_topN"] * 3,
        },
        schema=UNIVERSE_SCHEMA,
    )


@dataclass(frozen=True)
class Env:
    """The wired read path: the engine plus the raw components a test builds its own
    :class:`FeatureContext` from (so the integration probe never reaches into engine
    privates)."""

    engine: FeatureEngine
    reader: PITDataReader
    instruments: InstrumentStore
    universe: UniverseStore

    def context(self, ids: list[str], *, start: int, end: int) -> FeatureContext:
        return FeatureContext(
            reader=self.reader,
            instruments=self.instruments,
            universe=self.universe,
            instrument_ids=ids,
            start=start,
            end=end,
        )


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    tmp = tmp_path_factory.mktemp("corp_actions_read_path")
    paths = LakePaths(tmp / "lake")
    writer = LakeWriter(paths)
    writer.write(Dataset.OHLCV, _ohlcv_table(_raw_closes()))
    writer.write(Dataset.CORPORATE_ACTIONS, _ca_table())
    universe = UniverseStore(paths)
    universe.write_intervals(_universe_table())
    instruments = InstrumentStore(tmp / "instruments.db")
    reader = PITDataReader(paths)
    # Default (crypto) sleeve: H1 anchor grid, one slot == one session bar (GRID NOTE).
    yield Env(
        engine=FeatureEngine(reader, instruments, universe),
        reader=reader,
        instruments=instruments,
        universe=universe,
    )
    instruments.close()


class TestNoSpuriousSplitReturn:
    def test_reversal_across_ex_bar_is_not_split_garbage(self, env: Env) -> None:
        # (a) eq_rev_21 = -ln(C*_t / C*_{t-21}); without the fold, the window straddling
        # the ex bar carries ~ -ln(0.5) = +0.69 of pure split artifact. Folded, the
        # adjusted return is driven only by the random walk: |value| stays small.
        out = env.engine.compute_history(
            [default_registry().get("eq_rev_21")],
            list(IDS),
            start=T0 + 22 * HOUR,
            end=T0 + N_BARS * HOUR,
        )
        rev = out["eq_rev_21"]
        ex_ts = T0 + EX_K * HOUR
        # Rows whose 21-slot reversal window straddles the ex bar (knowable, post-decl).
        straddle = [ex_ts + k * HOUR for k in range(21)]
        vals = rev.loc[(straddle, AAPL)].to_numpy(dtype="float64")
        finite = vals[np.isfinite(vals)]
        assert finite.size > 0
        # A raw -50% split would put ~0.69 into these windows; the folded series is the
        # ~1% random walk — decisively below the split artifact magnitude.
        assert np.max(np.abs(finite)) < 0.2

    def test_momentum_across_ex_bar_is_clean(self, env: Env) -> None:
        # eq_mom_252_21 = ln(C*_{t-21}/C*_{t-252}); the long lookback spans the ex bar.
        # We assert on rows whose ENTIRE 252-slot window is in the knowable region
        # (t-252 >= DECL_K): both endpoints fold the split, so the split contributes a
        # cancelling 0.5 to numerator and denominator and the residual is the random
        # walk. (Rows reaching back before the declaration legitimately compare a
        # genuinely-unadjusted pre-announcement bar against an adjusted one — the
        # documented per-decision-row PIT consequence, not an artifact to assert away.)
        out = env.engine.compute_history(
            [default_registry().get("eq_mom_252_21")],
            list(IDS),
            start=T0 + (252 + DECL_K + 1) * HOUR,
            end=T0 + N_BARS * HOUR,
        )
        mom = out["eq_mom_252_21"].xs(AAPL, level="instrument_id").to_numpy(dtype="float64")
        finite = mom[np.isfinite(mom)]
        assert finite.size > 0
        # 12-1 momentum over a ~1%/bar walk stays well under the +0.69 split artifact.
        assert np.max(np.abs(finite)) < 0.4


class TestSplitInvisibleBeforeAvailableAt:
    def test_raw_before_declaration_adjusted_after(self, env: Env) -> None:
        # (b) The cross-window PIT assertion. We read the SAME pre-ex bar's adjusted
        # close from two windows whose `end` (= as_of) brackets the declaration:
        #   - window ending BEFORE available_at: the split is unknowable -> raw price.
        #   - window ending AT/AFTER available_at: knowable -> folded x0.5.
        # Asserted directly on the adjusted-close panel the read path produces.
        probe_k = DECL_K + 5  # a pre-ex bar at/after the declaration slot
        probe_ts = T0 + probe_k * HOUR
        raw_px = float(_raw_closes()[AAPL][probe_k])

        # Window ending strictly BEFORE the split is knowable: the reader masks it out.
        unknowable = env.context([AAPL], start=T0, end=AVAILABLE_AT - 1)
        assert unknowable.corporate_actions().empty  # available_at > as_of
        adj_unknowable = ep._adjusted_close_panel(unknowable)
        assert adj_unknowable.loc[probe_ts, AAPL] == pytest.approx(raw_px, rel=1e-12)

        # Window extending past available_at: the split is served and folds the pre-ex
        # probe bar (decision = probe_ts + DAY >= available_at) x0.5.
        knowable = env.context([AAPL], start=T0, end=T0 + N_BARS * HOUR)
        assert not knowable.corporate_actions().empty  # available_at <= as_of
        adj_knowable = ep._adjusted_close_panel(knowable)
        assert adj_knowable.loc[probe_ts, AAPL] == pytest.approx(raw_px * 0.5, rel=1e-12)


class TestFailClosedWhenSurfaceAbsent:
    def test_raise_when_corporate_actions_getter_off(self, env: Env) -> None:
        # (c) SPINE_ARC §2.3: with the corp-actions surface absent, the adjusted-close
        # panel must FAIL CLOSED, never silently return raw. A context proxy that lacks
        # corporate_actions stands in for any future context that forgot to wire it.
        ctx = env.context([AAPL], start=T0, end=T0 + N_BARS * HOUR)

        class _NoCAProxy:
            def __init__(self, inner: FeatureContext) -> None:
                self._inner = inner

            def panel(self, column: str = "close", tf: Timeframe = Timeframe.H1) -> object:
                return self._inner.panel(column, tf)

            # deliberately NO corporate_actions attribute

        with pytest.raises(ConfigError, match="corporate-actions surface"):
            ep._adjusted_close_panel(_NoCAProxy(ctx))  # type: ignore[arg-type]

    def test_empty_actions_passes_through_raw(self, env: Env) -> None:
        # The one legitimate raw pass-through: an instrument with NO actions in the
        # window (MSFT) yields the raw close panel unchanged (C* == C_raw).
        ctx = env.context([MSFT], start=T0, end=T0 + N_BARS * HOUR)
        assert ctx.corporate_actions().empty
        adj = ep._adjusted_close_panel(ctx)
        raw = ctx.panel("close")
        # No actions ⇒ the adjusted panel is bit-for-bit the raw panel (no phantom
        # split factor anywhere), so every close-to-close return is unchanged too.
        np.testing.assert_array_equal(
            adj[MSFT].to_numpy(dtype="float64"), raw[MSFT].to_numpy(dtype="float64")
        )
