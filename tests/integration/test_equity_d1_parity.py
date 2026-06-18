"""Equity D1 batch-vs-as-of parity on the REAL XNYS session grid (S8 — the permanent
regression guard that replaced ``FeatureEngine._guard_equity_unverified``).

The guard fail-closed on EQUITY/D1 specs until the calendar-aware as-of window +
``forward_returns``/blend session hops were verified. It is LIFTED, and this test is the
contract that keeps it honest: an EQUITY ``FeatureEngine`` (D1 anchor + XNYS calendar) must
produce ``compute_history`` (one batch pass over years) == ``compute_asof`` (the live
minimal window) bit-for-bit (atol=0) at every sampled decision — including samples whose
decision bar is reached across a weekend. A future edit that re-breaks the session-hop
window arithmetic (or the split-only adjustment) fails here instead of silently shipping
wrong equity factors.

Unlike ``test_corp_actions_read_path`` (which stands H1 slots in for sessions on the crypto
engine), this writes bars on the ACTUAL ``XNYSCalendar`` session opens to ``OHLCV_1D`` and
runs the real D1 + XNYS engine, so the weekend/holiday hops are genuinely exercised.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa
import pytest

import alphaforge.features.library  # noqa: F401  (registers the @feature factories)
from alphaforge.core.calendar import calendar_for
from alphaforge.core.time import Timeframe, parse_utc
from alphaforge.core.types import AssetClass
from alphaforge.data.schemas import CORPORATE_ACTIONS_SCHEMA, UNIVERSE_SCHEMA, Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.parity import verify_parity
from alphaforge.features.registry import default_registry

if TYPE_CHECKING:
    from collections.abc import Iterator

    from alphaforge.core.instruments import InstrumentStore

AAPL = "XUSE:CASH:AAPLUSD"
MSFT = "XUSE:CASH:MSFTUSD"
NVDA = "XUSE:CASH:NVDAUSD"
JPM = "XUSE:CASH:JPMUSD"
IDS = (AAPL, MSFT, NVDA, JPM)

DAY = Timeframe.D1.ms
SPLIT_IDX = 250  # NVDA goes 2:1 ex at this session; declared SPLIT_DECL_IDX earlier
SPLIT_DECL_IDX = 230


def _sessions() -> list[int]:
    """~330 real XNYS session opens (epoch ms) — comfortably > the max equity lookback
    (eq_rev_resid_21 = 274) plus headroom for the sampled decisions."""
    cal = calendar_for(AssetClass.EQUITY)
    lo = parse_utc("2021-01-04T00:00:00Z")
    hi = parse_utc("2022-05-01T00:00:00Z")
    return list(cal.expected_bar_opens(lo, hi, Timeframe.D1))


def _walk(seed: int, n: int, level: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return level * np.exp(np.cumsum(rng.normal(0.0, 0.012, n)))


def _ohlcv_1d(sessions: list[int]) -> pa.Table:
    n = len(sessions)
    closes = {
        AAPL: _walk(1, n, 170.0),
        MSFT: _walk(2, n, 250.0),
        NVDA: _walk(3, n, 500.0),
        JPM: _walk(4, n, 140.0),
    }
    closes[NVDA][SPLIT_IDX:] *= 0.5  # as-traded 2:1 split halves the post-ex print
    iids: list[str] = []
    ts: list[int] = []
    px: list[float] = []
    for iid, c in closes.items():
        iids.extend([iid] * n)
        ts.extend(sessions)
        px.extend(float(v) for v in c)
    n_rows = len(iids)
    return pa.table(
        {
            "instrument_id": pa.array(iids, type=pa.string()),
            "ts_open": pa.array(ts, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array(px, type=pa.float64()),
            "high": pa.array([p * 1.001 for p in px], type=pa.float64()),
            "low": pa.array([p * 0.999 for p in px], type=pa.float64()),
            "close": pa.array(px, type=pa.float64()),
            "volume": pa.array([1_000_000.0] * n_rows, type=pa.float64()),
            "quote_volume": pa.array([p * 1_000_000.0 for p in px], type=pa.float64()),
            "n_trades": pa.array([5000] * n_rows, type=pa.int64()),
            "quality_flags": pa.array([0] * n_rows, type=pa.int32()),
            "ingested_at": pa.array(
                [t + DAY + 1000 for t in ts], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def _ca_table(sessions: list[int]) -> pa.Table:
    """One NVDA 2:1 split (ratio 0.5), declared at SPLIT_DECL_IDX, ex at SPLIT_IDX."""
    return pa.table(
        {
            "instrument_id": [NVDA],
            "action_type": ["split"],
            "ex_date": pa.array([sessions[SPLIT_IDX]], type=pa.timestamp("ms", tz="UTC")),
            "available_at": pa.array(
                [sessions[SPLIT_DECL_IDX] + DAY], type=pa.timestamp("ms", tz="UTC")
            ),
            "ratio": pa.array([0.5], type=pa.float64()),
            "cash_amount": pa.array([None], type=pa.float64()),
            "ingested_at": pa.array(
                [sessions[SPLIT_DECL_IDX] + DAY + 1000], type=pa.timestamp("ms", tz="UTC")
            ),
        },
        schema=CORPORATE_ACTIONS_SCHEMA,
    )


def _universe(sessions: list[int]) -> pa.Table:
    return pa.table(
        {
            "instrument_id": list(IDS),
            "effective_from": pa.array([sessions[0]] * len(IDS), type=pa.timestamp("ms", tz="UTC")),
            "effective_to": pa.array([None] * len(IDS), type=pa.timestamp("ms", tz="UTC")),
            "rank": pa.array(list(range(1, len(IDS) + 1)), type=pa.int32()),
            "reason": ["enter_topN"] * len(IDS),
        },
        schema=UNIVERSE_SCHEMA,
    )


@pytest.fixture(scope="module")
def equity_env(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[FeatureEngine, list[int]]]:
    from alphaforge.core.instruments import InstrumentStore

    sessions = _sessions()
    tmp = tmp_path_factory.mktemp("equity_d1_parity")
    paths = LakePaths(tmp / "lake")
    writer = LakeWriter(paths)
    writer.write(Dataset.OHLCV_1D, _ohlcv_1d(sessions))
    writer.write(Dataset.CORPORATE_ACTIONS, _ca_table(sessions))
    universe = UniverseStore(paths)
    universe.write_intervals(_universe(sessions))
    instruments: InstrumentStore = InstrumentStore(tmp / "instruments.db")
    reader = PITDataReader(paths)
    engine = FeatureEngine(reader, instruments, universe, asset_class=AssetClass.EQUITY)
    yield engine, sessions
    instruments.close()


def test_equity_d1_engine_resolves_the_xnys_sleeve(
    equity_env: tuple[FeatureEngine, list[int]],
) -> None:
    engine, _ = equity_env
    assert engine.anchor_tf is Timeframe.D1
    assert type(engine.calendar).__name__ == "XNYSCalendar"


def test_equity_d1_batch_asof_parity_exact(
    equity_env: tuple[FeatureEngine, list[int]],
) -> None:
    """compute_history == compute_asof bit-for-bit (atol=0) for every equity price factor
    at decisions sampled deep in the window — across weekends and past the split."""
    engine, sessions = equity_env
    reg = default_registry()
    specs = [
        reg.get(n)
        for n in ("eq_mom_252_21", "eq_rev_21", "eq_lowvol_252", "eq_bab_252", "eq_rev_resid_21")
    ]
    # Decision samples (T): floor_bar(T - Δ) lands on the chosen session, all > the deepest
    # lookback (274) and bracketing the split ex at SPLIT_IDX=250.
    samples = [sessions[i] + DAY for i in (290, 305, 320, len(sessions) - 1)]
    report = verify_parity(engine, specs, list(IDS), samples, history_start=sessions[0])
    for spec in specs:
        r = report.result(spec.name)
        assert r.n_points > 0, f"{spec.name}: no points compared"
        assert r.passed, (
            f"{spec.name}: equity D1 batch-vs-asof parity broke "
            f"(max_abs_diff={r.max_abs_diff!r}, mismatched={r.n_mismatched}/{r.n_points})"
        )
    assert report.passed
