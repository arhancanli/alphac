"""End-to-end Phase 4 deployed path on a synthetic lake.

One pipeline, exactly as research and live consume it (leakage finding 3 — ONE
feature framework on the deployed path):

    engine.compute_history (registered directional specs, PIT lake)
        → CSPipeline (winsorize_mad → cs_zscore) under the universe mask
        → times FeatureSpec.direction
        → execution-aware forward returns (alphaDesign.md §5.1)
        → rank_ic over universe members         ⇒ finite IC series + summary

and the live half of the same path:

    engine.compute_asof at sampled decision instants
        → the SAME CSPipeline under the SAME mask

must reproduce the research rows EXACTLY (the directional CS specs used here are
all finite-window: parity atol = 0, and deterministic per-timestamp CS stats on
identical inputs are bit-identical).

A planted non-member instrument sits in the lake throughout: the mask must keep it
out of every cross-sectional statistic (its processed values are all NaN) without
disturbing the members.

Offline; tmp_path lake only; deterministic (seeded rng).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

import alphaforge.features.library  # noqa: F401  — registers the factor library
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.cross_section import CSPipeline
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.registry import default_registry
from alphaforge.labeling import forward_returns
from alphaforge.validation import ic_summary, non_overlapping, rank_ic

if TYPE_CHECKING:
    from collections.abc import Iterator

    from alphaforge.features.spec import FeatureSpec

HOUR = 3_600_000
MIN5 = 300_000
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z (1h- and 8h-aligned)
N_BARS = 900
HORIZON = 24

MEMBERS = tuple(f"BINANCE:PERP:{base}USDT" for base in ("BTC", "ETH", "SOL", "ADA", "DOGE", "LTC"))
OUTSIDER = "BINANCE:PERP:EVLUSDT"  # in the lake, NEVER in the universe
ALL_IDS = [*MEMBERS, OUTSIDER]

# Directional cross-sectional specs whose lookbacks fit a 900-bar lake; all
# finite-window (parity atol = 0 ⇒ the live CS rows must be bit-identical).
SPEC_NAMES = ("mom_xs_168_24", "mom_xs_504_48", "carry_fund_21", "carry_fund_90")

# Distinct constant funding rates => a real, stable carry cross-section.
RATES = {iid: 1.0e-5 * (k + 1) for k, iid in enumerate(ALL_IDS)}

SAMPLE_BARS = (800, 850, 899)  # decision bars with full history for every spec


def _closes(seed: int, n: int, level: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.asarray(level * np.exp(np.cumsum(rng.normal(0.0, 0.005, n))))


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
        opens.extend(float(v) for v in close[:-1])  # open = previous close
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
            "volume": pa.array([10.0] * n_rows, type=pa.float64()),
            "quote_volume": pa.array([1.0e6] * n_rows, type=pa.float64()),
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
        tick_size=0.1,
        lot_size=0.001,
        min_qty=0.001,
        min_notional=5.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=T0 - 365 * 24 * HOUR,
        delisted_ts=None,
    )


@dataclass(frozen=True)
class Env:
    engine: FeatureEngine
    closes: dict[str, np.ndarray]


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    tmp = tmp_path_factory.mktemp("phase4_deployed_path")
    paths = LakePaths(tmp / "lake")
    writer = LakeWriter(paths)
    closes = {iid: _closes(100 + k, N_BARS, 50.0 * (k + 1)) for k, iid in enumerate(ALL_IDS)}
    writer.write(Dataset.OHLCV, _ohlcv_table(closes))

    funding_rows = [
        (iid, T0 + j * 8 * HOUR, RATES[iid], T0 + j * 8 * HOUR + MIN5)
        for iid in ALL_IDS
        for j in range(N_BARS // 8)
    ]
    writer.write(
        Dataset.FUNDING,
        pa.table(
            {
                "instrument_id": pa.array([r[0] for r in funding_rows], type=pa.string()),
                "ts_funding": pa.array(
                    [r[1] for r in funding_rows], type=pa.timestamp("ms", tz="UTC")
                ),
                "rate": pa.array([r[2] for r in funding_rows], type=pa.float64()),
                "available_at": pa.array(
                    [r[3] for r in funding_rows], type=pa.timestamp("ms", tz="UTC")
                ),
                "ingested_at": pa.array(
                    [r[3] + 1_000 for r in funding_rows], type=pa.timestamp("ms", tz="UTC")
                ),
            }
        ),
    )

    universe = UniverseStore(paths)
    universe.write_intervals(
        pa.table(
            {
                "instrument_id": pa.array(list(MEMBERS), type=pa.string()),
                "effective_from": pa.array([T0] * len(MEMBERS), type=pa.timestamp("ms", tz="UTC")),
                "effective_to": pa.array([None] * len(MEMBERS), type=pa.timestamp("ms", tz="UTC")),
                "rank": pa.array([1] * len(MEMBERS), type=pa.int32()),
                "reason": pa.array(["enter_top40"] * len(MEMBERS), type=pa.string()),
            }
        )
    )

    instruments = InstrumentStore(tmp / "instruments.db")
    for iid in ALL_IDS:
        instruments.upsert(_instrument(iid), as_of=T0 - 1000)

    engine = FeatureEngine(PITDataReader(paths), instruments, universe)
    yield Env(engine=engine, closes=closes)
    instruments.close()


def _specs() -> list[FeatureSpec]:
    return [default_registry().get(name) for name in SPEC_NAMES]


def _member_mask(index: pd.MultiIndex) -> pd.Series:
    members = index.get_level_values("instrument_id").isin(MEMBERS)
    return pd.Series(members, index=index)


def _signal_history(env: Env) -> pd.DataFrame:
    """The research half: compute_history → CS pipeline under the mask → direction sign."""
    specs = _specs()
    raw = env.engine.compute_history(specs, ALL_IDS, start=T0, end=T0 + N_BARS * HOUR)
    processed = CSPipeline().apply(raw, _member_mask(raw.index))
    directions = pd.Series({s.name: float(s.direction) for s in specs})
    return processed.mul(directions, axis="columns")


def _bars_long(env: Env) -> pd.DataFrame:
    """Long bars frame for the §5.1 label (eval-only; built from the planted lake)."""
    frames = [
        pd.DataFrame(
            {
                "instrument_id": iid,
                "ts_open": np.arange(N_BARS, dtype=np.int64) * HOUR + T0,
                "open": np.concatenate(([close[0]], close[:-1])),
                "close": close,
            }
        )
        for iid, close in env.closes.items()
    ]
    return pd.concat(frames, ignore_index=True)


class TestResearchPath:
    def test_rank_ic_finite_through_the_full_chain(self, env: Env) -> None:
        signal = _signal_history(env)
        fwd = forward_returns(_bars_long(env), HORIZON)
        mask = _member_mask(signal.index)
        for name in SPEC_NAMES:
            ic = rank_ic(signal[name], fwd, mask)
            finite = ic.dropna()
            assert len(finite) > 100, f"{name}: too few defined IC points ({len(finite)})"
            assert ((finite >= -1.0) & (finite <= 1.0)).all()
            summary = ic_summary(non_overlapping(ic.dropna(), HORIZON), lags=6)
            assert summary.n > 5
            assert math.isfinite(summary.mean)

    def test_non_member_is_nan_after_cs_processing(self, env: Env) -> None:
        signal = _signal_history(env)
        outsider_rows = signal.xs(OUTSIDER, level="instrument_id")
        assert outsider_rows.isna().all().all()  # masked BEFORE any CS statistic

    def test_members_have_real_signal_rows(self, env: Env) -> None:
        signal = _signal_history(env)
        ts = T0 + SAMPLE_BARS[0] * HOUR
        cross_section = signal.xs(ts, level="ts_open").loc[list(MEMBERS)]
        assert np.isfinite(cross_section.to_numpy(dtype=float)).all()
        # z-scored cross-sections are centered over the members.
        np.testing.assert_allclose(cross_section.mean(axis=0).to_numpy(), 0.0, atol=1e-12)


class TestLiveParityThroughDeployedPath:
    def test_compute_asof_plus_cs_pipeline_reproduces_history_exactly(self, env: Env) -> None:
        specs = _specs()
        signal_hist = _signal_history(env)
        directions = pd.Series({s.name: float(s.direction) for s in specs})
        for k in SAMPLE_BARS:
            t_star = T0 + k * HOUR
            live_raw = env.engine.compute_asof(specs, ALL_IDS, as_of=t_star + HOUR)
            assert isinstance(live_raw.index, pd.MultiIndex)
            live_signal = (
                CSPipeline()
                .apply(live_raw, _member_mask(live_raw.index))
                .mul(directions, axis="columns")
            )
            hist_rows = signal_hist.loc[[t_star]]
            pd.testing.assert_frame_equal(
                live_signal.sort_index(),
                hist_rows.sort_index(),
                check_exact=True,  # finite-window specs: the deployed path is bit-identical
            )
