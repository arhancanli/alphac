"""Phase-6 cross-fix observability integration test — the operator's confession.

The honesty fixes (F-A persistent ladder across legs; F-D/F-E per-bar
observability counters) only matter if the counters they emit actually
POPULATE through the full strategy -> engine -> walk-forward seam and survive
into ``walkforward.json``. This module drives the real
:class:`~alphaforge.analytics.walkforward.WalkForwardRunner` over a synthetic
tmp_path lake whose price path is engineered to exercise the two confessions
the adversarial review demanded be visible:

* **A leg that HALTS (F-A + F-E).** One test leg crashes the longed (highest
  mu_ann) instrument and spikes the shorted (lowest mu_ann) one, so the
  rank/inverse-vol book draws down past ``dd_flat_halt`` (15%) from its true
  running high-water mark. That leg's per-leg ``risk_counters`` must show
  ``bars_halted_flat > 0``, and -- the core F-A claim -- because ONE strategy
  is reused across legs (the ladder persists), the halt does NOT reset at the
  next leg boundary: the FLAT_HALTED state is absorbing, so once a later leg
  inherits a halted ladder it stays halted (only a human ``rearm()`` exits).
  A fresh-per-leg ladder (the old optimistic behaviour) would have silently
  resurrected the book.

* **A leg with a STALE/missing signal (F-E).** A signal source that returns an
  empty frame for one leg's window leaves the strategy with no fresh mu within
  ``staleness_max_bars``, so that leg HOLDS on every bar: its
  ``hold_stale_signal`` counter must be strictly positive and distinguishable
  from healthy ``hold_between_rebalance`` holding.

Both runs assert the per-leg AND aggregate ``risk_counters`` blocks are present
in the persisted ``walkforward.json`` (the JSON is the artifact the operator
reads). Offline, tmp_path only -- never ./data or ./var.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pyarrow as pa

from alphaforge.analytics.walkforward import WalkForwardRunner
from alphaforge.config.settings import Settings
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.costs import TransactionCostModel
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore

if TYPE_CHECKING:
    from pathlib import Path

    from alphaforge.core.time import Ms

HOUR = 3_600_000
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z, 1h/8h aligned
# 4 ids so the rank allocator's K = min(10, N // 4) = 1: it longs the highest
# mu_ann name and shorts the lowest, giving a directional book to crash.
IDS = tuple(f"BINANCE:PERP:{b}USDT" for b in ("AAA", "BBB", "CCC", "DDD"))
LONGED = IDS[3]  # highest mu_ann (see _MuSource below) -> the long leg
SHORTED = IDS[0]  # lowest mu_ann -> the short leg

# Walk-forward layout: 300 warm-up bars, 200-bar test legs.
_TRAIN, _TEST = 300, 200
_N_BARS = 1_300  # 300 warm + 5 full 200-bar legs -> the crash lands in leg 2.
# The crash window (in absolute bar index): inside the THIRD test leg
# [300 + 2*200, 300 + 3*200) = [700, 900).
_CRASH_START = 720
_CRASH_END = 770


def _price_path() -> dict[str, np.ndarray]:
    """Per-id close paths: flat-ish until a sharp divergence in test leg 2.

    The longed name (DDD) crashes ~85% over a sharp crash window and the
    shorted name (AAA) spikes ~85%; the two middle names drift mildly. A
    sharp, deep divergence on a directional book draws equity well past the
    15% flat-halt threshold before the HALF_GROSS de-gross can fully dampen it.
    """
    n = _N_BARS
    base = {iid: np.full(n, 100.0, dtype=np.float64) for iid in IDS}
    # mild deterministic drift on the two middle names so the cross-section is
    # non-degenerate (positive variance) without moving equity much.
    t = np.arange(n, dtype=np.float64)
    base[IDS[1]] = 100.0 + 5.0 * np.sin(t / 50.0)
    base[IDS[2]] = 100.0 + 5.0 * np.cos(t / 50.0)
    # Give the longed/shorted names small wiggle pre-crash for finite variance.
    base[LONGED] = 100.0 + 2.0 * np.sin(t / 37.0)
    base[SHORTED] = 100.0 + 2.0 * np.cos(t / 37.0)
    # The engineered divergence over the crash window (smooth ramp, sustained).
    idx = np.arange(_CRASH_START, _CRASH_END)
    frac = (idx - _CRASH_START + 1) / (_CRASH_END - _CRASH_START)
    base[LONGED][_CRASH_START:_CRASH_END] = 100.0 * (1.0 - 0.85 * frac)
    base[LONGED][_CRASH_END:] = base[LONGED][_CRASH_END - 1]
    base[SHORTED][_CRASH_START:_CRASH_END] = 100.0 * (1.0 + 0.85 * frac)
    base[SHORTED][_CRASH_END:] = base[SHORTED][_CRASH_END - 1]
    return base


def _ohlcv_table(per_inst: dict[str, np.ndarray]) -> pa.Table:
    iids: list[str] = []
    ts: list[int] = []
    opens: list[float] = []
    closes: list[float] = []
    for iid, close in per_inst.items():
        n = len(close)
        iids.extend([iid] * n)
        ts.extend(T0 + k * HOUR for k in range(n))
        opens.append(float(close[0]))
        opens.extend(float(v) for v in close[:-1])
        closes.extend(float(v) for v in close)
    n_rows = len(iids)
    return pa.table(
        {
            "instrument_id": pa.array(iids, type=pa.string()),
            "ts_open": pa.array(ts, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array(opens, type=pa.float64()),
            "high": pa.array([v * 1.001 for v in closes], type=pa.float64()),
            "low": pa.array([v * 0.999 for v in closes], type=pa.float64()),
            "close": pa.array(closes, type=pa.float64()),
            "volume": pa.array([100.0] * n_rows, type=pa.float64()),
            "quote_volume": pa.array([1.0e7] * n_rows, type=pa.float64()),
            "n_trades": pa.array([42] * n_rows, type=pa.int64()),
            "quality_flags": pa.array([0] * n_rows, type=pa.int32()),
            "ingested_at": pa.array(
                [t + HOUR + 1000 for t in ts], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def _instrument(instrument_id: str) -> Instrument:
    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base=instrument_id.split(":")[2].removesuffix("USDT"),
        quote="USDT",
        tick_size=0.01,
        lot_size=0.0001,
        min_qty=0.0001,
        min_notional=5.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=T0 - 365 * 24 * HOUR,
        delisted_ts=None,
    )


class _MuSource:
    """A constant-mu_ann SignalSource giving a stable directional rank book.

    mu_ann increases with the id index, so DDD (index 3) is always the longed
    name and AAA (index 0) the shorted name. Distinct values keep the ranking
    unambiguous across rebalances.
    """

    def compute_research(self, start: Ms, end: Ms) -> pd.DataFrame:
        opens = list(range(start, end, HOUR))
        rows: list[dict[str, object]] = []
        for k, iid in enumerate(IDS):
            mu = 0.05 * float(k - 1.5)  # -0.075, -0.025, +0.025, +0.075
            for ts_open in opens:
                rows.append({"ts_open": ts_open, "instrument_id": iid, "mu_ann": mu})
        return pd.DataFrame(rows).set_index(["ts_open", "instrument_id"]).sort_index()


class _StaleForOneLegSource:
    """Like :class:`_MuSource` but returns an EMPTY frame for the second test
    leg's research window, simulating a dead/stale signal feed for that leg.

    The runner calls ``compute_research(train_start, test_end)`` once per leg;
    leg 1's test span is [300 + 200, 300 + 400) so its train_start is
    max(T0, (300+200-300)*HOUR) -> we key on the test_end to pick the leg.
    """

    _STALE_TEST_END = T0 + (_TRAIN + 2 * _TEST) * HOUR  # leg 1's test_end

    def compute_research(self, start: Ms, end: Ms) -> pd.DataFrame:
        if end == self._STALE_TEST_END:
            # Empty (no rows) -> the strategy finds no fresh mu and HOLDS the
            # whole leg on hold_stale_signal.
            return (
                pd.DataFrame({"ts_open": [], "instrument_id": [], "mu_ann": []})
                .astype({"ts_open": "int64", "instrument_id": "object", "mu_ann": "float64"})
                .set_index(["ts_open", "instrument_id"])
            )
        return _MuSource().compute_research(start, end)


def _write_lake(tmp: Path) -> tuple[PITDataReader, InstrumentStore, UniverseStore]:
    paths = LakePaths(tmp / "lake")
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(_price_path()))
    universe = UniverseStore(paths)
    universe.write_intervals(
        pa.table(
            {
                "instrument_id": pa.array(list(IDS), type=pa.string()),
                "effective_from": pa.array([T0] * len(IDS), type=pa.timestamp("ms", tz="UTC")),
                "effective_to": pa.array([None] * len(IDS), type=pa.timestamp("ms", tz="UTC")),
                "rank": pa.array([1] * len(IDS), type=pa.int32()),
                "reason": pa.array(["enter_top40"] * len(IDS), type=pa.string()),
            }
        )
    )
    store = InstrumentStore(tmp / "ops.sqlite")
    for iid in IDS:
        store.upsert(_instrument(iid), as_of=T0 - 365 * 24 * HOUR)
    return PITDataReader(paths), store, universe


_EXPECTED_COUNTER_KEYS = {
    "n_rebalances",
    "n_fallback_used",
    "hold_between_rebalance",
    "hold_stale_signal",
    "hold_cov_cold_start",
    "hold_degenerate_xsection",
    "bars_halted_flat",
    "bars_half_gross",
}


def _make_runner(
    reader: PITDataReader,
    store: InstrumentStore,
    universe: UniverseStore,
    signal_service: object,
) -> WalkForwardRunner:
    from alphaforge.backtest import StaticCostInputs

    return WalkForwardRunner(
        reader,
        store,
        universe,
        TransactionCostModel.from_settings(Settings()),
        signal_service,  # type: ignore[arg-type]
        Settings(),
        cost_inputs=StaticCostInputs(adv_quote=1.0e9, sigma_daily=0.05),
    )


def test_halting_leg_confesses_and_ladder_does_not_reset(tmp_path: Path) -> None:
    """F-A + F-E: a leg that crashes past dd_flat_halt shows bars_halted_flat>0
    in its per-leg counters, the halt is visible in walkforward.json, and the
    persisted ladder keeps the run halted afterwards (no per-leg reset)."""
    reader, store, universe = _write_lake(tmp_path)
    out = tmp_path / "wf_halt"
    try:
        result = _make_runner(reader, store, universe, _MuSource()).run(
            T0,
            T0 + _N_BARS * HOUR,
            train_bars=_TRAIN,
            test_bars=_TEST,
            rebalance_bars=24,
            cov_min_periods=120,
            out_dir=out,
        )
    finally:
        store.close()

    # Some leg halted: bars_halted_flat fired (the crash drew the book down
    # past the 15% flat-halt threshold from the true running HWM).
    per_leg_halts = [int(leg.risk_counters["bars_halted_flat"]) for leg in result.legs]
    assert sum(per_leg_halts) > 0, f"no leg halted; per-leg halts = {per_leg_halts}"
    first_halt_leg = next(i for i, h in enumerate(per_leg_halts) if h > 0)

    # F-A: FLAT_HALTED is absorbing and the ladder PERSISTS across legs, so once
    # a leg halts every later leg inherits the halt -- it never silently resets.
    # (A fresh-per-leg ladder would reseed the HWM at the boundary and resurrect
    # the book: the dishonest, optimistic curve this fix closes.)
    assert result.legs[-1].leg > first_halt_leg, "need a leg after the first halt to prove no reset"
    for leg in result.legs[first_halt_leg + 1 :]:
        rc = leg.risk_counters
        # A halted ladder forces an all-zero book every bar: the leg is entirely
        # halts, with no fresh rebalances (n_rebalances stays 0 for the leg).
        assert int(rc["bars_halted_flat"]) > 0, (
            f"leg {leg.leg} after the halt did not stay halted -> ladder reset (F-A regression)"
        )
        assert int(rc["n_rebalances"]) == 0, (
            f"leg {leg.leg} rebalanced after a halt -> ladder resurrected (F-A regression)"
        )

    # The aggregate confession also shows the halt.
    agg = result.config["risk_counters"]
    assert isinstance(agg, dict)
    assert int(agg["bars_halted_flat"]) > 0

    # walkforward.json carries per-leg AND aggregate risk_counters.
    meta = json.loads((out / "walkforward.json").read_text(encoding="utf-8"))
    assert set(meta["config"]["risk_counters"]) == _EXPECTED_COUNTER_KEYS
    assert int(meta["config"]["risk_counters"]["bars_halted_flat"]) > 0
    json_halts = 0
    for leg_row in meta["legs"]:
        assert set(leg_row["risk_counters"]) == _EXPECTED_COUNTER_KEYS
        json_halts += int(leg_row["risk_counters"]["bars_halted_flat"])
    assert json_halts == sum(per_leg_halts)
    # Per-leg deltas sum to the aggregate (load_leg never resets counters, F-A).
    for key in _EXPECTED_COUNTER_KEYS:
        per_leg_sum = sum(int(row["risk_counters"][key]) for row in meta["legs"])
        assert per_leg_sum == int(meta["config"]["risk_counters"][key])


def test_stale_signal_leg_confesses_hold_stale(tmp_path: Path) -> None:
    """F-E: a leg whose signal feed went dead HOLDS on hold_stale_signal, a
    counter distinct from healthy hold_between_rebalance, and surfaced in JSON."""
    reader, store, universe = _write_lake(tmp_path)
    out = tmp_path / "wf_stale"
    try:
        result = _make_runner(reader, store, universe, _StaleForOneLegSource()).run(
            T0,
            T0 + _N_BARS * HOUR,
            train_bars=_TRAIN,
            test_bars=_TEST,
            rebalance_bars=24,
            cov_min_periods=120,
            out_dir=out,
        )
    finally:
        store.close()

    # The stale leg (leg index 1) holds every bar on a dead feed.
    stale_leg = result.legs[1]
    assert int(stale_leg.risk_counters["hold_stale_signal"]) > 0, (
        "the dead-feed leg did not record hold_stale_signal"
    )
    # That leg did not rebalance (no fresh mu ever arrived).
    assert int(stale_leg.risk_counters["n_rebalances"]) == 0
    # A healthy leg (leg 0) trades and does NOT read as stale -- the two holds
    # are distinguishable (the whole point of F-E).
    healthy = result.legs[0]
    assert int(healthy.risk_counters["n_rebalances"]) > 0
    assert int(healthy.risk_counters["hold_stale_signal"]) == 0

    # JSON carries the stale confession.
    meta = json.loads((out / "walkforward.json").read_text(encoding="utf-8"))
    assert set(meta["config"]["risk_counters"]) == _EXPECTED_COUNTER_KEYS
    assert int(meta["config"]["risk_counters"]["hold_stale_signal"]) > 0
    assert int(meta["legs"][1]["risk_counters"]["hold_stale_signal"]) > 0
