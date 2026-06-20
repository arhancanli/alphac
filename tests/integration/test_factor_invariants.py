"""Registry-wide factor invariants (Phase 4 integration gate).

For EVERY spec in ``default_registry()`` (the deployed feature surface — importing
:mod:`alphaforge.features.library` registers the full v1 library), on one synthetic
deterministic lake deep enough for the largest lookback (``reg_rvp_720``, 9480 bars):

1. **Truncation invariance / batch-live parity** — ``verify_truncation`` per spec:
   the value computed from FULL history (``compute_history`` from lake genesis)
   equals the value computed by the live path (``compute_asof``, minimal window of
   exactly ``lookback_bars``) within the spec's declared tolerance (atol = 0 for
   finite windows, rtol 1e-9 for the EWMA family). A factor that consumes more
   history than it declares, or whose window alignment drifts, fails here.
2. **Non-vacuity** — every spec is non-NaN for every instrument at the sampled
   decision bars (a parity check between two NaNs proves nothing).
3. **NaN-warmup boundary** — every spec is NaN at lake genesis (no history) when
   ``lookback_bars > 1``, and its first non-NaN decision bar arrives no later than
   ``lookback_bars - 1`` bars after genesis: the declared lookback is SUFFICIENT
   (the other half of lookback honesty; the live buffer sized from it can always
   produce a value).

Plus the leakage-finding-20 spot checks: an under-declared ``lookback_bars`` is
caught mechanically by the truncation harness, and the EWMA-family convention
(``lookback_bars >= 10·span``) re-validates whenever params are altered — a window
parameter can never drift away from the history the live path loads. And the
funding-interval contract (leakage finding 6): carry annualizes with
``8760 / funding_interval_hours`` read from the SCD2 instrument record (8h vs 4h
instruments give different annualizations from identical rates).

Offline; tmp_path lakes only; deterministic (seeded rng).
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa
import pytest

import alphaforge.features.library  # noqa: F401  — registers the full factor library
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.parity import verify_truncation
from alphaforge.features.registry import default_registry
from alphaforge.features.spec import FeatureSpec

if TYPE_CHECKING:
    from collections.abc import Iterator

    import pandas as pd

BTC = "BINANCE:PERP:BTCUSDT"  # the regime anchor — must be in the cross-section
ETH = "BINANCE:PERP:ETHUSDT"  # 4h funding interval (interval-aware carry fixture)
IDS = [BTC, ETH]

HOUR = 3_600_000
MIN5 = 300_000
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z — 1h-, 4h- and 8h-aligned
N_BARS = 9_600  # > max registered lookback (reg_rvp_720: 9480) + sample headroom

BTC_RATE = 1.0e-4  # base funding level for the carry-level annualization fixture
ETH_RATE = 1.0e-4

# A deterministic, per-settlement-index funding rate with genuine variation. A
# constant rate would make the self-relative funding z-score (``carry_z_252``)
# all-NaN by correct design (zero trailing std => relative-eps sigma floor), which
# is not a factor bug — it is a degenerate fixture. The settlement-indexed sinusoid
# below gives every funding-dynamics factor a non-degenerate window while staying a
# closed form the carry-annualization test can evaluate exactly. (Amplitude << base,
# so the sign of the rate never flips: the carry-level economics are unchanged.)
_FUND_AMP = 1.0e-5


def _funding_rate(base: float, j: int) -> float:
    """Settlement-indexed funding rate: ``base + amp·sin(j)`` (deterministic)."""
    return float(base + _FUND_AMP * math.sin(float(j)))


# Decision instants T = t* + Δ at bars 9520 / 9560 / 9599 — all with full history
# for every registered spec (largest lookback 9480 needs bar index >= 9479).
SAMPLE_BARS = (9_520, 9_560, 9_599)
SAMPLES = [T0 + (k + 1) * HOUR for k in SAMPLE_BARS]

ALL_SPECS: list[FeatureSpec] = default_registry().all_specs()
ALL_NAMES = [s.name for s in ALL_SPECS]

#: F2 fundamental factors REQUIRE the fundamentals lake (Dataset.FUNDAMENTALS), which this
#: crypto test fixture has none of -> they are legitimately all-NaN here. The truncation/
#: parity sweep still covers them (NaN == NaN, atol=0); the NON-NaN warmup-boundary tests
#: (which assert a real value warms up) cannot apply without fundamentals data, so they are
#: parametrized over the non-fundamental factors only. Their warmup is covered on real data
#: by the equity IC report + the equity integration parity test.
_NEEDS_FUNDAMENTALS: frozenset[str] = frozenset(
    {
        "eq_earnings_yield",
        "eq_book_to_price",
        "eq_sales_to_price",
        "eq_gross_profitability",
        "eq_roe",
        "eq_operating_margin",
    }
)
WARMUP_NAMES = [n for n in ALL_NAMES if n not in _NEEDS_FUNDAMENTALS]


# ------------------------------------------------------------------------ lake build


def _random_walk_ohlcv(seed: int, n: int, level: float) -> dict[str, np.ndarray]:
    """Valid OHLC geometry + heavy-tailed positive quote volume (liquidity needs it)."""
    rng = np.random.default_rng(seed)
    close = level * np.exp(np.cumsum(rng.normal(0.0, 0.005, n)))
    open_ = np.empty(n)
    open_[0] = level
    open_[1:] = close[:-1] * np.exp(rng.normal(0.0, 0.001, n - 1))
    wick = np.abs(rng.normal(0.0, 0.002, n))
    high = np.maximum(open_, close) * np.exp(wick)
    low = np.minimum(open_, close) * np.exp(-wick)
    qv = np.exp(rng.normal(np.log(1.0e6), 0.5, n))
    return {"open": open_, "high": high, "low": low, "close": close, "quote_volume": qv}


def _ohlcv_table(per_inst: dict[str, dict[str, np.ndarray]]) -> pa.Table:
    iids: list[str] = []
    ts: list[int] = []
    cols: dict[str, list[float]] = {c: [] for c in ("open", "high", "low", "close")}
    qvs: list[float] = []
    for iid, ohlc in per_inst.items():
        n = len(ohlc["close"])
        iids.extend([iid] * n)
        ts.extend(T0 + k * HOUR for k in range(n))
        for name in cols:
            cols[name].extend(float(v) for v in ohlc[name])
        qvs.extend(float(v) for v in ohlc["quote_volume"])
    n_rows = len(iids)
    return pa.table(
        {
            "instrument_id": pa.array(iids, type=pa.string()),
            "ts_open": pa.array(ts, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array(cols["open"], type=pa.float64()),
            "high": pa.array(cols["high"], type=pa.float64()),
            "low": pa.array(cols["low"], type=pa.float64()),
            "close": pa.array(cols["close"], type=pa.float64()),
            "volume": pa.array([10.0] * n_rows, type=pa.float64()),
            "quote_volume": pa.array(qvs, type=pa.float64()),
            "n_trades": pa.array([42] * n_rows, type=pa.int64()),
            "quality_flags": pa.array([0] * n_rows, type=pa.int32()),
            "ingested_at": pa.array(
                [t + HOUR + 1000 for t in ts], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def _funding_table(rows: list[tuple[str, int, float, int]]) -> pa.Table:
    return pa.table(
        {
            "instrument_id": pa.array([r[0] for r in rows], type=pa.string()),
            "ts_funding": pa.array([r[1] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "rate": pa.array([r[2] for r in rows], type=pa.float64()),
            "available_at": pa.array([r[3] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "ingested_at": pa.array(
                [r[3] + 1_000 for r in rows], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def _universe_table(rows: list[tuple[str, int, int | None]]) -> pa.Table:
    return pa.table(
        {
            "instrument_id": pa.array([r[0] for r in rows], type=pa.string()),
            "effective_from": pa.array([r[1] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "effective_to": pa.array([r[2] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "rank": pa.array([1 for _ in rows], type=pa.int32()),
            "reason": pa.array(["enter_top40" for _ in rows], type=pa.string()),
        }
    )


def _instrument(instrument_id: str, base: str, interval: int) -> Instrument:
    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base=base,
        quote="USDT",
        tick_size=0.1,
        lot_size=0.001,
        min_qty=0.001,
        min_notional=5.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=interval,
        listed_ts=T0 - 365 * 24 * HOUR,
        delisted_ts=None,
    )


@dataclass(frozen=True)
class Env:
    engine: FeatureEngine
    history: pd.DataFrame  # ALL specs, full lake span, both instruments


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    tmp = tmp_path_factory.mktemp("factor_invariants")
    paths = LakePaths(tmp / "lake")
    writer = LakeWriter(paths)
    writer.write(
        Dataset.OHLCV,
        _ohlcv_table(
            {
                BTC: _random_walk_ohlcv(7, N_BARS, 100.0),
                ETH: _random_walk_ohlcv(8, N_BARS, 50.0),
            }
        ),
    )
    funding_rows: list[tuple[str, int, float, int]] = []
    for j in range(N_BARS // 8):  # BTC settles every 8h, published 5min later
        ts = T0 + j * 8 * HOUR
        funding_rows.append((BTC, ts, _funding_rate(BTC_RATE, j), ts + MIN5))
    for j in range(N_BARS // 4):  # ETH settles every 4h (interval-aware fixture)
        ts = T0 + j * 4 * HOUR
        funding_rows.append((ETH, ts, _funding_rate(ETH_RATE, j), ts + MIN5))
    writer.write(Dataset.FUNDING, _funding_table(funding_rows))

    universe = UniverseStore(paths)
    universe.write_intervals(_universe_table([(BTC, T0, None), (ETH, T0, None)]))

    instruments = InstrumentStore(tmp / "instruments.db")
    instruments.upsert(_instrument(BTC, "BTC", 8), as_of=T0 - 1000)
    instruments.upsert(_instrument(ETH, "ETH", 4), as_of=T0 - 1000)

    engine = FeatureEngine(PITDataReader(paths), instruments, universe)
    history = engine.compute_history(ALL_SPECS, IDS, start=T0, end=T0 + N_BARS * HOUR)
    yield Env(engine=engine, history=history)
    instruments.close()


def _spec(name: str) -> FeatureSpec:
    return default_registry().get(name)


# ------------------------------------------------- 1. registry-wide truncation sweep


class TestTruncationAndParitySweep:
    def test_registry_is_the_full_v1_library(self) -> None:
        # The sweep below is only meaningful if it runs over the REAL library: the
        # 24 original v1 crypto factors + the 6 build-slate additions (carry_z_252,
        # carry_mom_21_63, lowvol_720, semivar_skew_504, beta_lowbeta_720,
        # mom_res_2160_168) + the two reference features = 32, PLUS the 7 EQUITIES-sleeve
        # price factors (eq_mom_252_21, eq_rev_21, eq_lowvol_252, eq_beta_252,
        # eq_bab_252, eq_vol_252, eq_amihud_63 — EQUITIES_SLEEVE.md §4) = 39. The equity
        # factors are positional on ctx.panel, so the truncation/parity/warmup sweep
        # below exercises them on this crypto lake too (they fall back to the raw close
        # panel when the context exposes no corporate actions — the documented build-order
        # gap — and remain finite-window ⇒ atol = 0). PLUS the 2 EQUITIES-sleeve breadth
        # additions (S6 eq_rev_resid_21 — beta-residualized reversal; S7 eq_ilrev —
        # illiquidity-premium alpha) = 41. Both are finite-window, EQUITY-sleeve opt-in
        # (NOT in any crypto active set), so the sweep covers them at atol = 0 too.
        # PLUS the 6 F2 FUNDAMENTAL factors (eq_earnings_yield / eq_book_to_price /
        # eq_sales_to_price value; eq_gross_profitability / eq_roe / eq_operating_margin
        # quality) = 47. On the crypto lake their fundamentals read is empty -> all-NaN, so
        # the sweep covers them at atol = 0 (NaN == NaN) and they never touch a crypto set.
        assert len(ALL_SPECS) == 47
        assert len(set(ALL_NAMES)) == 47

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_truncation_invariance_and_live_parity(self, env: Env, name: str) -> None:
        spec = _spec(name)
        report = verify_truncation(env.engine, spec, IDS, SAMPLES, history_start=T0)
        result = report.result(name)
        assert result.n_points == len(SAMPLES) * len(IDS)
        assert result.passed, (
            f"{name}: live minimal-window value disagrees with full-history value "
            f"(max_abs_diff={result.max_abs_diff!r}, rtol={result.rtol})"
        )
        if not spec.is_ewma_family:
            # Finite-window contract is exact: ANY difference is a window bug.
            assert result.max_abs_diff == 0.0


# ------------------------------------------- 2 + 3. non-vacuity and warmup boundary


class TestWarmupBoundary:
    @pytest.mark.parametrize("name", WARMUP_NAMES)
    def test_non_nan_at_sampled_decision_bars(self, env: Env, name: str) -> None:
        # Non-vacuity for the parity sweep: every spec produces a real value for
        # every instrument at every sampled decision bar.
        for k in SAMPLE_BARS:
            ts = T0 + k * HOUR
            for iid in IDS:
                value = env.history.loc[(ts, iid), name]
                assert math.isfinite(float(value)), f"{name} NaN at bar {k} for {iid}"

    @pytest.mark.parametrize("name", WARMUP_NAMES)
    def test_nan_at_genesis_and_first_valid_within_lookback(self, env: Env, name: str) -> None:
        spec = _spec(name)
        deadline = T0 + (spec.lookback_bars - 1) * HOUR
        for iid in IDS:
            series = env.history[name].xs(iid, level="instrument_id")
            if spec.lookback_bars > 1:
                assert np.isnan(series.loc[T0]), f"{name} must be NaN at genesis for {iid}"
            first_valid = series.first_valid_index()
            assert first_valid is not None
            assert int(first_valid) <= deadline, (
                f"{name}: first valid bar {int(first_valid)} is later than the declared "
                f"lookback allows ({deadline}) — lookback_bars={spec.lookback_bars} "
                "is INSUFFICIENT (the live buffer sized from it could not warm up)"
            )


# --------------------------------------------------- finding-20 lookback spot checks


class TestLookbackDerivesFromParams:
    def test_underdeclared_lookback_fails_the_truncation_harness(self, env: Env) -> None:
        # Alter the spec so lookback_bars no longer covers params["lookback"]: the
        # live minimal window (100 bars) cannot produce a 168-bar momentum, so the
        # harness must fail with an inf diff (one side NaN) — this is the safety
        # net that makes lookback/params drift mechanically impossible to ship.
        good = _spec("mom_xs_168_24")
        bad = dataclasses.replace(good, name="mom_xs_168_24__underdeclared", lookback_bars=100)
        report = verify_truncation(env.engine, bad, IDS, SAMPLES, history_start=T0)
        result = report.result(bad.name)
        assert not result.passed
        assert math.isinf(result.max_abs_diff)

    def test_ewma_convention_revalidates_on_param_change(self) -> None:
        # Constructing a spec with an altered EWMA span but a stale lookback must
        # fail at construction (FeatureSpec enforces lookback_bars >= 10·span):
        # a window parameter cannot drift away from the loaded history.
        good = _spec("mom_ts_168")
        assert good.lookback_bars >= 10 * int(good.params["span"])
        with pytest.raises(ValueError):
            dataclasses.replace(
                good,
                name="mom_ts_168__span_drift",
                params={**dict(good.params), "span": 300},  # needs >= 3000 > 2520
            )

    def test_finite_window_lookback_matches_params(self) -> None:
        # Direct derivation spot checks against the registered params (the factory
        # is the single construction site — these must always agree).
        xs = _spec("mom_xs_504_48")
        assert xs.lookback_bars == int(xs.params["lookback"]) + 1
        carry = _spec("carry_fund_21")
        expected = (int(carry.params["n_settlements"]) + 1) * int(
            carry.params["max_funding_interval_hours"]
        ) + 1
        assert carry.lookback_bars == expected
        yz = _spec("vol_yz_720")
        assert yz.lookback_bars == int(yz.params["window"]) + 1


# -------------------------------------------------- finding-6 funding interval check


class TestCarryFundingInterval:
    @staticmethod
    def _trailing_mean_asof(base: float, interval_h: int, decision_ts: int, k: int) -> float:
        """Mean of the last ``k`` settlements published (available_at <= decision_ts).

        Mirrors the carry factor's PIT contract on the fixture's known funding curve:
        settlement ``j`` of an ``interval_h``-hour instrument has ts ``T0 + j·I`` and is
        published at ``+ MIN5``; the trailing mean is over the ``k`` largest such ``j``.
        """
        last_j = -1
        j = 0
        while T0 + j * interval_h * HOUR + MIN5 <= decision_ts:
            last_j = j
            j += 1
        js = range(last_j - k + 1, last_j + 1)
        return sum(_funding_rate(base, jj) for jj in js) / float(k)

    def test_annualization_uses_instrument_interval(self, env: Env) -> None:
        # BTC settles 8h, ETH settles 4h (SCD2 record). CARRY = -f̄ · 8760/interval.
        # The funding curve now VARIES per settlement (so the funding-dynamics factors
        # are non-degenerate), so the expectation is the PIT trailing mean of the last
        # K published rates — computed from the same known curve — times the
        # interval-aware annualizer. A hard-coded 3·365 (8h) annualizer for ETH would
        # break the ratio (ETH annualizes at exactly twice BTC for equal trailing means).
        ts = T0 + SAMPLE_BARS[0] * HOUR
        decision_ts = ts + HOUR  # the value at ts_open=ts is decided at the bar close
        for name, k in (("carry_fund_21", 21), ("carry_fund_90", 90)):
            btc_mean = self._trailing_mean_asof(BTC_RATE, 8, decision_ts, k)
            eth_mean = self._trailing_mean_asof(ETH_RATE, 4, decision_ts, k)
            btc_carry = float(env.history.loc[(ts, BTC), name])
            eth_carry = float(env.history.loc[(ts, ETH), name])
            assert btc_carry == pytest.approx(-btc_mean * 8760.0 / 8.0, rel=1e-9)
            assert eth_carry == pytest.approx(-eth_mean * 8760.0 / 4.0, rel=1e-9)
