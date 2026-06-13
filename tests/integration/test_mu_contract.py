"""THE mu_ann contract, end-to-end (leakageCritique.md finding 2).

The single most dangerous seam in the system: the alpha layer emits an
expected-return vector and the portfolio layer consumes it. If the two
disagree on units — per-bar vs per-horizon vs annualized — the optimizer
silently chases a mis-scaled signal and every downstream P&L is wrong while
looking plausible. This test pins the contract on the DEPLOYED path:

1. ``SignalService.compute_research`` emits a column literally named
   ``mu_ann`` and every value clears the optimizer's ``|mu_ann| < 3.0``
   tripwire (a free-data 1h crypto book's annualized alpha is at most tens of
   percent, never multiples).
2. Feeding the genuine ``mu_ann`` through ``MeanVarianceOptimizer`` yields a
   constraint-respecting book whose ex-ante annualized alpha ``μᵀw`` sits in
   the modest band an IC≈0.02 signal implies — not a levered moonshot.
3. The finding-2 failure mode is CAUGHT: a mu vector mis-scaled by the
   horizon (x72, the classic per-bar/per-horizon slip) trips
   ``check_mu_ann_contract`` / the optimizer, hard.
4. The horizon ``h`` lives in exactly ONE settings field
   (``signals.horizon_bars``); the sizer and the splitter both read it, so a
   single edit re-tunes the whole stack coherently (buildability §3.10).

Offline, tmp_path lake only, deterministic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.config.settings import Settings, SignalsCfg
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.context import long_series
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.registry import FeatureRegistry
from alphaforge.features.spec import Family, FeatureSpec
from alphaforge.portfolio.covariance import (
    annualize_cov,
    ewma_cov,
    ledoit_wolf_cc,
    nearest_psd,
)
from alphaforge.portfolio.optimizer import (
    MU_ANN_ABS_MAX,
    MeanVarianceOptimizer,
    check_mu_ann_contract,
)
from alphaforge.signals.service import SignalService

if TYPE_CHECKING:
    from collections.abc import Iterator

    from alphaforge.features.context import FeatureContext

HOUR = 3_600_000
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z
N_BARS = 900
H = 72  # == SignalsCfg().horizon_bars (asserted below)
MEMBERS = tuple(f"BINANCE:PERP:{b}USDT" for b in ("BTC", "ETH", "SOL", "ADA", "DOGE", "LTC"))
START = T0 + 240 * HOUR
END = T0 + N_BARS * HOUR


def _xret_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """w-bar log return on the complete grid (a tiny finite-window CS alpha)."""
    close = ctx.panel("close")
    window = int(spec.params["window"])
    out: pd.DataFrame = np.log(close / close.shift(window))  # type: ignore[assignment]
    return long_series(out, name=spec.name)


def _registry() -> FeatureRegistry:
    reg = FeatureRegistry()

    def alpha_mom() -> FeatureSpec:
        window = 48
        return FeatureSpec(
            name="alpha_mom",
            family=Family.MOMENTUM,
            direction=1,
            cross_sectional=True,
            lookback_bars=window + 1,
            params={"window": window},
            fn=_xret_fn,
        )

    reg.register(alpha_mom)
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


class _Env:
    __slots__ = ("closes", "research", "store")

    def __init__(
        self, research: pd.DataFrame, closes: dict[str, np.ndarray], store: InstrumentStore
    ) -> None:
        self.research = research
        self.closes = closes
        self.store = store


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Env]:
    tmp = tmp_path_factory.mktemp("mu_contract")
    paths = LakePaths(tmp / "lake")
    closes = {iid: _closes(11 + k, N_BARS, 50.0 * (k + 1)) for k, iid in enumerate(MEMBERS)}
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

    store = InstrumentStore(tmp / "ops.sqlite")
    for iid in MEMBERS:
        store.upsert(_instrument(iid), as_of=T0 - 365 * 24 * HOUR)

    reader = PITDataReader(paths)
    service = SignalService(
        FeatureEngine(reader, store, universe), universe, _registry(), SignalsCfg()
    )
    research = service.compute_research(START, END)
    yield _Env(research, closes, store)
    store.close()


def test_horizon_is_one_settings_field() -> None:
    """h lives only in signals.horizon_bars; the contract's 8760/h is derived."""
    assert SignalsCfg().horizon_bars == H
    assert Settings().signals.horizon_bars == H


def test_research_emits_mu_ann_column_within_tripwire(env: _Env) -> None:
    """(1) The seam's output column is literally ``mu_ann`` and clears |mu|<3."""
    assert "mu_ann" in env.research.columns
    mu = env.research["mu_ann"].to_numpy(dtype=np.float64)
    finite = mu[np.isfinite(mu)]
    assert finite.size > 0
    assert np.abs(finite).max() < MU_ANN_ABS_MAX
    # The genuine vector passes the optimizer's own guard unchanged.
    check_mu_ann_contract(finite)


def _latest_full_mu(research: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    """The most recent ts_open whose every member has a finite mu_ann."""
    mu = research["mu_ann"]
    for _ts_open, row in reversed(list(mu.groupby(level="ts_open"))):
        vals = row.droplevel("ts_open")
        if np.isfinite(vals.to_numpy(dtype=np.float64)).all() and len(vals) >= 2:
            ids = [str(i) for i in vals.index]
            return ids, vals.to_numpy(dtype=np.float64)
    raise AssertionError("no fully-populated mu_ann cross-section in the research frame")


def _cov_ann(closes: dict[str, np.ndarray], ids: list[str], *, upto: int) -> np.ndarray:
    """Annualized Σ from the same closes, the BlendStrategy way (EWMA→LW→PSD)."""
    panel = pd.DataFrame({iid: closes[iid][:upto] for iid in ids})
    rets = panel.pct_change().iloc[1:]
    cov_bar = ewma_cov(rets, halflife_bars=720, min_periods=200)
    block, _delta = ledoit_wolf_cc(rets.to_numpy(dtype=np.float64), cov_bar)
    return annualize_cov(nearest_psd(block), 8760.0)


def test_optimizer_consumes_mu_ann_into_a_sane_book(env: _Env) -> None:
    """(2) Real mu_ann → constraint-respecting book; ex-ante alpha μᵀw modest."""
    ids, mu = _latest_full_mu(env.research)
    cov_ann = _cov_ann(env.closes, ids, upto=N_BARS)
    opt = MeanVarianceOptimizer.from_settings(Settings())
    w_prev = np.zeros(len(ids))
    cost = np.full(len(ids), 0.0010)
    shortable = np.ones(len(ids))
    res = opt.solve(mu, cov_ann, w_prev, cost, shortable)

    assert res.status in ("optimal", "fallback_used")
    w = res.weights
    assert np.isfinite(w).all()
    assert np.abs(w).sum() <= 1.0 + 1e-6  # gross cap
    assert np.abs(w).max() <= 0.15 + 1e-6  # per-asset cap
    ex_ante_alpha = float(mu @ w)
    # An IC≈0.02 signal at 15% vol target implies single-digit-to-tens-of-%
    # annualized expected alpha — finite, and nowhere near a levered moonshot.
    assert 0.0 <= ex_ante_alpha < 1.0


def test_horizon_misscaled_mu_trips_the_tripwire(env: _Env) -> None:
    """(3) The finding-2 failure: mu mistakenly left per-72-bar-horizon-x-8760 (about 72x
    too large) must be REFUSED, not silently chased."""
    ids, mu = _latest_full_mu(env.research)
    cov_ann = _cov_ann(env.closes, ids, upto=N_BARS)
    opt = MeanVarianceOptimizer.from_settings(Settings())
    bad = mu * float(H)  # the classic per-bar↔per-horizon unit slip
    assert np.abs(bad).max() >= MU_ANN_ABS_MAX  # the synthetic world actually trips it
    with pytest.raises(ValueError, match="mu_ann"):
        opt.solve(bad, cov_ann, np.zeros(len(ids)), np.full(len(ids), 0.0010), np.ones(len(ids)))
