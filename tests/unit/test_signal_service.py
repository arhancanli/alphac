"""Seam tests for alphaforge.signals.service.SignalService on a synthetic lake.

The deployed-path pattern of tests/integration/test_phase4_deployed_path.py,
extended through the alpha→portfolio seam:

* research chain shape/NaN discipline (PIT mask: a planted non-member instrument
  never enters any cross-section),
* THE mu_ann contract (finding 2): the service's mu_ann column equals
  ``ic_target · sigma_hat · sqrt(h) · alpha_blend · (8760/h)`` with sigma_hat
  recomputed independently from the planted closes, and stays inside the
  optimizer's |mu_ann| < 3 band,
* walk-forward weights: rows normalized, cold-start row equal, and — the
  end-to-end lag regression — shortening the window by one grid step leaves all
  common weight rows IDENTICAL (later data cannot reach earlier weights),
* research-vs-live parity at three decision instants: ``on_bar_close`` must
  reproduce the research rows (1e-9 relative; sigma_hat is EWMA-family).

Offline; tmp_path lake only; deterministic (seeded rng).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import patch

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.config.settings import SignalsCfg
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.context import long_series
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.library.vol import ewma_vol
from alphaforge.features.registry import FeatureRegistry
from alphaforge.features.spec import Family, FeatureSpec
from alphaforge.signals.blending import BlendWeights
from alphaforge.signals.service import SignalService

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from alphaforge.features.context import FeatureContext

HOUR = 3_600_000
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z
N_BARS = 840
H = 72  # == SignalsCfg().horizon_bars — asserted in the fixture

MEMBERS = tuple(f"BINANCE:PERP:{b}USDT" for b in ("BTC", "ETH", "SOL", "ADA", "DOGE", "LTC"))
OUTSIDER = "BINANCE:PERP:EVLUSDT"  # in the lake, NEVER in the universe
ALL_IDS = [*MEMBERS, OUTSIDER]

START = T0 + 240 * HOUR  # alpha_slow (97 bars) and sigma (169 bars) are warm here
END = T0 + N_BARS * HOUR
SAMPLE_BARS = (600, 700, 839)  # decision bars for the parity sweep
ALPHAS = ("alpha_fast", "alpha_slow")


def test_factorized_membership_mask_matches_half_open_interval_semantics() -> None:
    """Integer factorization is an exact replacement for repeated string comparisons."""
    a = "BINANCE:PERP:AAAUSDT"
    b = "BINANCE:PERP:BBBUSDT"
    c = "BINANCE:PERP:CCCUSDT"
    timestamps = [T0, T0 + HOUR, T0 + 2 * HOUR, T0 + 3 * HOUR]
    index = pd.MultiIndex.from_product(
        [timestamps, [a, b]], names=["ts_open", "instrument_id"]
    )
    # A has two disjoint spans, B has one bounded span, and C is absent from
    # the panel. The exact endpoints exercise [effective_from, effective_to).
    intervals = (
        [a, a, b, c],
        [T0, T0 + 3 * HOUR, T0 + HOUR, T0],
        [T0 + HOUR, None, T0 + 3 * HOUR, None],
    )
    service = object.__new__(SignalService)
    with patch.object(SignalService, "_intervals", return_value=intervals):
        observed = service._membership_mask(index)
    expected = pd.Series(
        [True, False, False, True, False, True, True, False],
        index=index,
    )
    pd.testing.assert_series_equal(observed, expected, check_exact=True)


def test_factorized_membership_mask_matches_legacy_algorithm_randomized() -> None:
    """Regression oracle: factorized IDs reproduce the former object-compare mask exactly."""
    rng = np.random.default_rng(20260823)
    ids = [f"BINANCE:PERP:R{value:02d}USDT" for value in range(12)]
    timestamps = np.arange(T0, T0 + 240 * HOUR, HOUR, dtype=np.int64)
    index = pd.MultiIndex.from_product(
        [timestamps, ids[:10]], names=["ts_open", "instrument_id"]
    )
    interval_ids: list[str] = []
    starts: list[int] = []
    ends: list[int | None] = []
    for iid in ids:
        for _ in range(3):
            start_offset = int(rng.integers(0, 180))
            width = int(rng.integers(1, 50))
            interval_ids.append(iid)
            starts.append(T0 + start_offset * HOUR)
            ends.append(T0 + min(240, start_offset + width) * HOUR)
    intervals = (interval_ids, starts, ends)
    ts = index.get_level_values("ts_open").to_numpy(dtype=np.int64)
    inst = index.get_level_values("instrument_id").to_numpy()
    legacy = np.zeros(len(index), dtype=bool)
    for iid, start, end in zip(*intervals, strict=True):
        in_span = ts >= start if end is None else (ts >= start) & (ts < end)
        legacy |= in_span & (inst == iid)

    service = object.__new__(SignalService)
    with patch.object(SignalService, "_intervals", return_value=intervals):
        observed = service._membership_mask(index)
    np.testing.assert_array_equal(observed.to_numpy(), legacy)


def _xret_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """w-bar log return on the complete grid (test alpha; gaps stay NaN)."""
    close = ctx.panel("close")
    window = int(spec.params["window"])
    out: pd.DataFrame = np.log(close / close.shift(window))  # type: ignore[assignment]
    return long_series(out, name=spec.name)


def _registry() -> FeatureRegistry:
    """Fresh registry with two tiny directional CS alphas (finite-window)."""
    reg = FeatureRegistry()

    def alpha_fast() -> FeatureSpec:
        window = 24
        return FeatureSpec(
            name="alpha_fast",
            family=Family.MOMENTUM,
            direction=1,
            cross_sectional=True,
            lookback_bars=window + 1,
            params={"window": window},
            fn=_xret_fn,
        )

    def alpha_slow() -> FeatureSpec:
        window = 96
        return FeatureSpec(
            name="alpha_slow",
            family=Family.REVERSAL,
            direction=-1,  # exercises the direction multiply through the seam
            cross_sectional=True,
            lookback_bars=window + 1,
            params={"window": window},
            fn=_xret_fn,
        )

    reg.register(alpha_fast)
    reg.register(alpha_slow)
    return reg


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
    service: SignalService
    closes: dict[str, np.ndarray]
    research: pd.DataFrame
    weights: BlendWeights
    cfg: SignalsCfg


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    tmp = tmp_path_factory.mktemp("signal_service")
    paths = LakePaths(tmp / "lake")
    closes = {iid: _closes(100 + k, N_BARS, 50.0 * (k + 1)) for k, iid in enumerate(ALL_IDS)}
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(closes))

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

    cfg = SignalsCfg()
    assert cfg.horizon_bars == H  # the ONE constant this module keys on
    engine = FeatureEngine(PITDataReader(paths), instruments, universe)
    service = SignalService(engine, universe, _registry(), cfg, alpha_names=ALPHAS)
    research = service.compute_research(START, END)
    weights = service.estimate_weights(START, END)
    yield Env(service=service, closes=closes, research=research, weights=weights, cfg=cfg)
    instruments.close()


def _sigma_independent(env: Env) -> pd.Series:
    """sigma_hat recomputed straight from the planted closes (full history from
    T0 — the same information set the service's PIT window sees)."""
    grid = np.arange(N_BARS, dtype=np.int64) * HOUR + T0
    wide = pd.DataFrame(
        {iid: env.closes[iid] for iid in ALL_IDS},
        index=pd.Index(grid, name="ts_open"),
    )
    wide.columns.name = "instrument_id"
    return long_series(ewma_vol(wide, span=168))


class TestResearchChain:
    def test_shape_columns_and_grid(self, env: Env) -> None:
        res = env.research
        assert list(res.columns) == ["alpha_blend", "mu_ann"]
        ts_level = res.index.get_level_values("ts_open").unique()
        assert len(ts_level) == (END - START) // HOUR
        assert len(res) == len(ts_level) * len(MEMBERS)

    def test_outsider_never_enters_the_panel(self, env: Env) -> None:
        """The id set is derived from the PIT universe store — an instrument
        that was never a member is absent from the panel entirely (stronger
        than NaN: it cannot even contribute an index row)."""
        inst_level = env.research.index.get_level_values("instrument_id")
        assert OUTSIDER not in set(inst_level)
        assert set(inst_level) == set(MEMBERS)

    def test_member_blend_is_zscored_cross_section(self, env: Env) -> None:
        for k in SAMPLE_BARS:
            cs = env.research.xs(T0 + k * HOUR, level="ts_open")["alpha_blend"]
            members = cs.loc[list(MEMBERS)]
            assert np.isfinite(members.to_numpy()).all()
            np.testing.assert_allclose(float(members.mean()), 0.0, atol=1e-9)
            np.testing.assert_allclose(float(members.std(ddof=1)), 1.0, rtol=1e-9)

    def test_mu_ann_contract_units_and_band(self, env: Env) -> None:
        """Finding 2 boundary test: mu_ann == ic_target·sigma_hat·sqrt(h)·A~·(8760/h)
        against an INDEPENDENT sigma_hat recomputation, and inside the |mu|<3 band."""
        res = env.research
        sigma = _sigma_independent(env).reindex(res.index)
        expected = env.cfg.ic_target * sigma * np.sqrt(float(H)) * res["alpha_blend"] * (8760.0 / H)
        got = res["mu_ann"]
        both = np.isfinite(got.to_numpy()) & np.isfinite(expected.to_numpy())
        assert both.sum() > 1000  # the comparison is over a real panel, not a sliver
        np.testing.assert_allclose(got.to_numpy()[both], expected.to_numpy()[both], rtol=1e-9)
        # NaN sets agree: mu is NaN exactly where alpha or sigma is unusable
        assert np.array_equal(np.isfinite(got.to_numpy()), np.isfinite(expected.to_numpy()))
        assert float(np.abs(got.to_numpy()[both]).max()) < 3.0  # optimizer refusal band


class TestWalkForwardWeights:
    def test_rows_normalized_positive_on_the_h_grid(self, env: Env) -> None:
        w = env.weights.weights
        spacing = np.diff(w.index.to_numpy(dtype=np.int64))
        assert (spacing == H * HOUR).all()
        assert (w.to_numpy() > 0.0).all()
        np.testing.assert_allclose(w.sum(axis=1).to_numpy(), 1.0, rtol=1e-12)

    def test_cold_start_first_grid_row_is_equal_weights(self, env: Env) -> None:
        np.testing.assert_allclose(env.weights.weights.iloc[0].to_numpy(), 0.5, rtol=0, atol=0)

    def test_lag_enforcement_end_to_end(self, env: Env) -> None:
        """Shorten the window by ONE grid step: every common weight row must be
        bit-identical — data inside the last h bars (and beyond) can never
        reach the weights used at earlier decision bars."""
        shorter = env.service.estimate_weights(START, END - H * HOUR)
        n = len(shorter.weights)
        assert n == len(env.weights.weights) - 1
        pd.testing.assert_frame_equal(
            shorter.weights, env.weights.weights.iloc[:n], check_exact=True
        )


class TestResearchLiveParity:
    def test_on_bar_close_reproduces_research_rows(self, env: Env) -> None:
        """THE seam contract: live (compute_asof + latest weights) == research
        at the same decision bar, to the EWMA parity tolerance (sigma_hat is
        EWMA-family; the alphas here are finite-window)."""
        members = sorted(MEMBERS)
        for k in SAMPLE_BARS:
            t_star = T0 + k * HOUR
            live = env.service.on_bar_close(t_star + HOUR, weights=env.weights)
            assert list(live.index) == members
            research_rows = env.research.xs(t_star, level="ts_open").loc[members]
            pd.testing.assert_frame_equal(live, research_rows, rtol=1e-9, atol=1e-12)

    def test_cold_start_live_path_uses_equal_weights(self, env: Env) -> None:
        as_of = T0 + (SAMPLE_BARS[0] + 1) * HOUR
        none_given = env.service.on_bar_close(as_of)
        explicit_equal = env.service.on_bar_close(as_of, weights=BlendWeights.equal(ALPHAS))
        pd.testing.assert_frame_equal(none_given, explicit_equal, check_exact=True)

    def test_empty_universe_refuses(self, env: Env) -> None:
        with pytest.raises(ValueError, match="universe is empty"):
            env.service.on_bar_close(T0)  # decision bar precedes every interval


class TestConstruction:
    def test_direction_zero_spec_is_rejected(self, env: Env) -> None:
        reg = FeatureRegistry()

        def not_an_alpha() -> FeatureSpec:
            return FeatureSpec(
                name="not_an_alpha",
                family=Family.MARKET,
                direction=0,
                cross_sectional=False,
                lookback_bars=1,
                params={},
                fn=_xret_fn,
            )

        reg.register(not_an_alpha)
        engine = env.service  # only need types for the ctor; reuse wired objects
        with pytest.raises(ValueError, match="direction=0"):
            SignalService(
                engine._engine,
                engine._universe,
                reg,
                env.cfg,
                alpha_names=("not_an_alpha",),
            )


# --------------------------------------------------------------------------- asset-class scope
#
# 2026-09-05: the crypto sleeve's weekly rebalance crashed four Thursdays running
# (08-13, 08-20, 08-27, 09-03) with ``KeyError: instrument 'XUSE:CASH:AALUSD' is unknown
# to the SCD2 store``. The universe store is SHARED across asset classes (2,088 equity
# names beside 20 perps on the crypto lake), the live loop's ``_InstrumentsAdapter``
# scopes the TRADABLE set to the profile's asset class, but the SignalService built its
# cross-section from the raw membership, so the carry feature asked the instrument store
# for the funding interval of an equity — which on the trading host has no record at
# all. The sleeve held its 30 July positions for 37 days. These tests pin the contract:
# the signal cross-section is the sleeve's asset class, never the raw membership.

EQUITY_WITH_RECORD = "XUSE:CASH:AALUSD"  # alphabetically first equity -> the one that raised
EQUITY_WITHOUT_RECORD = "XUSE:CASH:ZZZUSD"  # the trading host's condition: no SCD2 row at all
LEAKED = (EQUITY_WITH_RECORD, EQUITY_WITHOUT_RECORD)


def _equity_instrument(instrument_id: str) -> Instrument:
    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.EQUITY,
        market_type=MarketType.CASH,
        base=instrument_id.split(":")[2].removesuffix("USD"),
        quote="USD",
        tick_size=0.01,
        lot_size=1.0,
        min_qty=1.0,
        min_notional=0.0,
        can_short=True,
        maker_fee_bps=1.0,
        taker_fee_bps=1.0,
        funding_interval_hours=None,
        listed_ts=T0 - 365 * 24 * HOUR,
        delisted_ts=None,
    )


@pytest.fixture(scope="module")
def leaked_env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    """The production shape: a cross-asset universe store over a crypto sleeve.

    Membership = the crypto MEMBERS plus two equity ids. One has an EQUITY record
    (the Mac's store), one has NO record (the trading host's pruned store). Neither
    has bars on this lake, exactly like production.
    """
    tmp = tmp_path_factory.mktemp("signal_service_scope")
    paths = LakePaths(tmp / "lake")
    closes = {iid: _closes(300 + k, N_BARS, 50.0 * (k + 1)) for k, iid in enumerate(ALL_IDS)}
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(closes))

    members = [*MEMBERS, *LEAKED]
    universe = UniverseStore(paths)
    universe.write_intervals(
        pa.table(
            {
                "instrument_id": pa.array(members, type=pa.string()),
                "effective_from": pa.array([T0] * len(members), type=pa.timestamp("ms", tz="UTC")),
                "effective_to": pa.array([None] * len(members), type=pa.timestamp("ms", tz="UTC")),
                "rank": pa.array([1] * len(members), type=pa.int32()),
                "reason": pa.array(["enter_top40"] * len(members), type=pa.string()),
            }
        )
    )

    instruments = InstrumentStore(tmp / "instruments.db")
    for iid in ALL_IDS:
        instruments.upsert(_instrument(iid), as_of=T0 - 1000)
    instruments.upsert(_equity_instrument(EQUITY_WITH_RECORD), as_of=T0 - 1000)
    # EQUITY_WITHOUT_RECORD deliberately gets no row.

    cfg = SignalsCfg()
    engine = FeatureEngine(PITDataReader(paths), instruments, universe)
    service = SignalService(engine, universe, _registry(), cfg, alpha_names=ALPHAS)
    research = service.compute_research(START, END)
    weights = service.estimate_weights(START, END)
    yield Env(service=service, closes=closes, research=research, weights=weights, cfg=cfg)
    instruments.close()


class TestCrossSectionIsScopedToTheSleeve:
    def test_live_cross_section_is_exactly_the_sleeve_members(self, leaked_env: Env) -> None:
        """The decision row set equals the crypto members: the equity with a record
        is excluded by asset class, the equity without one is excluded because it
        cannot be resolved — and neither raises."""
        as_of = T0 + (SAMPLE_BARS[0] + 1) * HOUR
        live = leaked_env.service.on_bar_close(as_of, weights=leaked_env.weights)
        assert set(live.index) == set(MEMBERS)
        for leaked in LEAKED:
            assert leaked not in live.index

    def test_research_panel_excludes_leaked_ids(self, leaked_env: Env) -> None:
        """Research and live are one seam: the batch panel is scoped the same way,
        or the parity contract would compare a scoped live row set against an
        unscoped research grid."""
        ids = set(leaked_env.research.index.get_level_values("instrument_id"))
        assert ids == set(MEMBERS)

    def test_scoped_live_rows_still_reproduce_research(self, leaked_env: Env) -> None:
        members = sorted(MEMBERS)
        for k in SAMPLE_BARS:
            t_star = T0 + k * HOUR
            live = leaked_env.service.on_bar_close(t_star + HOUR, weights=leaked_env.weights)
            research_rows = leaked_env.research.xs(t_star, level="ts_open").loc[members]
            pd.testing.assert_frame_equal(live, research_rows, rtol=1e-9, atol=1e-12)

    def test_a_universe_of_only_foreign_ids_refuses_loudly(self, tmp_path: Path) -> None:
        """If scoping empties the cross-section the service must say so, not hold
        silently: a silent hold is how 173 signal-dead cycles once read as
        'carry compressed'."""
        paths = LakePaths(tmp_path / "lake")
        closes = {iid: _closes(900 + k, N_BARS, 50.0) for k, iid in enumerate(ALL_IDS)}
        LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(closes))
        universe = UniverseStore(paths)
        universe.write_intervals(
            pa.table(
                {
                    "instrument_id": pa.array(list(LEAKED), type=pa.string()),
                    "effective_from": pa.array([T0] * 2, type=pa.timestamp("ms", tz="UTC")),
                    "effective_to": pa.array([None] * 2, type=pa.timestamp("ms", tz="UTC")),
                    "rank": pa.array([1] * 2, type=pa.int32()),
                    "reason": pa.array(["enter_top40"] * 2, type=pa.string()),
                }
            )
        )
        instruments = InstrumentStore(tmp_path / "instruments.db")
        try:
            instruments.upsert(_equity_instrument(EQUITY_WITH_RECORD), as_of=T0 - 1000)
            engine = FeatureEngine(PITDataReader(paths), instruments, universe)
            service = SignalService(engine, universe, _registry(), SignalsCfg(), alpha_names=ALPHAS)
            with pytest.raises(ValueError, match=r"no .*members"):
                service.on_bar_close(T0 + (SAMPLE_BARS[0] + 1) * HOUR)
        finally:
            instruments.close()
