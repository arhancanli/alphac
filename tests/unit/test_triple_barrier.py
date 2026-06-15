"""Unit tests for cost-honest, gap-aware triple-barrier labeling.

Golden synthetic paths (touches known by construction), property/leakage guards, and
the must-fix regression tests from CRITIQUE_leakage (findings 2/3/6/8/11/17/24) and
CRITIQUE_overfit item 8. All fixtures are synthetic — the live data lake is never
touched.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alphaforge.core.instruments import Instrument
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass, Liquidity, MarketType
from alphaforge.costs.model import TransactionCostModel
from alphaforge.labeling.triple_barrier import TripleBarrierConfig, apply_triple_barrier

_H1_MS = Timeframe.H1.ms
_PERP_ID = "BINANCE:PERP:BTCUSDT"
_SPOT_ID = "BINANCE:SPOT:ETHUSDT"


def _perp(instrument_id: str = _PERP_ID, *, funding_interval_hours: int = 8) -> Instrument:
    base = instrument_id.split(":")[-1].removesuffix("USDT")
    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base=base,
        quote="USDT",
        tick_size=0.01,
        lot_size=0.001,
        min_qty=0.001,
        min_notional=5.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=funding_interval_hours,
        listed_ts=0,
        delisted_ts=None,
    )


def _spot(instrument_id: str = _SPOT_ID) -> Instrument:
    base = instrument_id.split(":")[-1].removesuffix("USDT")
    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.CRYPTO_SPOT,
        market_type=MarketType.SPOT,
        base=base,
        quote="USDT",
        tick_size=0.01,
        lot_size=0.001,
        min_qty=0.001,
        min_notional=5.0,
        can_short=True,
        maker_fee_bps=10.0,
        taker_fee_bps=10.0,
        funding_interval_hours=None,
        listed_ts=0,
        delisted_ts=None,
    )


def _bars(
    instrument_id: str,
    opens: list[float],
    *,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    closes: list[float] | None = None,
    start_ms: int = 0,
) -> pd.DataFrame:
    """Build an OHLC panel from a list of opens (high/low default to open ± a hair)."""
    n = len(opens)
    ts = [start_ms + i * _H1_MS for i in range(n)]
    highs = highs if highs is not None else [o * 1.0001 for o in opens]
    lows = lows if lows is not None else [o * 0.9999 for o in opens]
    closes = closes if closes is not None else list(opens)
    return pd.DataFrame(
        {
            "instrument_id": instrument_id,
            "ts_open": np.array(ts, dtype=np.int64),
            "open": np.array(opens, dtype=float),
            "high": np.array(highs, dtype=float),
            "low": np.array(lows, dtype=float),
            "close": np.array(closes, dtype=float),
        }
    )


def _event(ts: int, instrument_id: str = _PERP_ID, side: int = 1) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": np.array([ts], dtype=np.int64),
            "instrument_id": [instrument_id],
            "side": [np.int8(side)],
        }
    )


def _vol_series(bars: pd.DataFrame, sigma: float) -> pd.Series:
    """A constant per-bar sigma_hat on the (ts_open, instrument_id) grid."""
    idx = pd.MultiIndex.from_arrays(
        [bars["ts_open"].to_numpy(), bars["instrument_id"].to_numpy()],
        names=("ts_open", "instrument_id"),
    )
    return pd.Series(sigma, index=idx, dtype="float64")


def _free_cfg(**kw: object) -> TripleBarrierConfig:
    """A short-horizon, cost-free config for geometry-only golden tests."""
    defaults: dict[str, object] = {"horizon_bars": 5, "cost_honest": False}
    defaults.update(kw)
    return TripleBarrierConfig(**defaults)  # type: ignore[arg-type]


def _run(
    bars: pd.DataFrame,
    events: pd.DataFrame,
    cfg: TripleBarrierConfig,
    *,
    instruments: dict[str, Instrument] | None = None,
    cost_model: TransactionCostModel | None = None,
    funding: pd.DataFrame | None = None,
    vol: pd.Series | None = None,
) -> pd.DataFrame:
    """Thin wrapper supplying the common perp instrument + default cost model."""
    return apply_triple_barrier(
        bars,
        events,
        cfg,
        cost_model=cost_model if cost_model is not None else TransactionCostModel(),
        instruments=instruments if instruments is not None else {_PERP_ID: _perp()},
        funding=funding,
        vol=vol,
    )


# --------------------------------------------------------------------------- golden


def test_long_pt_touch_golden() -> None:
    # sigma_hat=0.01, H=5 -> w = 0.01*sqrt(5) ≈ 0.022360; up = p0*exp(+w).
    cfg = _free_cfg()
    # Entry at bar 1 (p0=100). A rising ramp first pierces up at a known bar.
    opens = [100.0, 100.0, 100.5, 101.0, 101.5, 102.0, 103.0, 104.0]
    bars = _bars(_PERP_ID, opens, highs=[o * 1.0 for o in opens])  # high == open
    events = _event(0 * _H1_MS, side=1)
    vol = _vol_series(bars, 0.01)
    out = _run(bars, events, cfg, vol=vol)
    row = out.iloc[0]
    p0 = 100.0
    w = 0.01 * np.sqrt(5)
    up = p0 * np.exp(w)
    # First path bar (k=1.. = ts 2,3,..) whose high>=up. up≈102.26 -> bar at open 103 (ts=6*Δ).
    assert row["touch"] == 1
    assert row["label_tb"] == 1
    assert row["t1"] == 6 * _H1_MS
    assert row["exit_price"] == pytest.approx(up)  # PT fills at the limit, not the high
    assert row["entry_price"] == pytest.approx(p0)
    assert row["ret_gross"] == pytest.approx(np.log(up / p0))


def test_long_sl_touch_golden() -> None:
    cfg = _free_cfg()
    opens = [100.0, 100.0, 99.5, 99.0, 98.5, 98.0, 97.0]
    bars = _bars(_PERP_ID, opens, lows=[o * 1.0 for o in opens])  # low == open
    events = _event(0, side=1)
    vol = _vol_series(bars, 0.01)
    out = _run(bars, events, cfg, vol=vol)
    row = out.iloc[0]
    assert row["touch"] == -1
    assert row["label_tb"] == -1  # -side
    # stop barrier dn~97.79; first low<=dn is open 97 at ts=6d; open 97 < dn -> gap fills at open.
    assert row["t1"] == 6 * _H1_MS
    assert row["exit_price"] == pytest.approx(97.0)  # gap through stop -> worse fill (open)


def test_both_touch_in_one_bar_is_stop_first() -> None:
    cfg = _free_cfg()
    p0 = 100.0
    w = 0.01 * np.sqrt(5)
    up = p0 * np.exp(w)
    dn = p0 * np.exp(-w)
    # Bar 2 (k=1) straddles BOTH barriers; path unknown -> conservative stop-first.
    opens = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0]
    highs = list(opens)
    lows = list(opens)
    highs[2] = up + 1.0
    lows[2] = dn - 1.0
    bars = _bars(_PERP_ID, opens, highs=highs, lows=lows)
    events = _event(0, side=1)
    vol = _vol_series(bars, 0.01)
    out = _run(bars, events, cfg, vol=vol)
    row = out.iloc[0]
    assert row["touch"] == -1
    assert row["label_tb"] == -1
    assert row["t1"] == 2 * _H1_MS
    # open of bar 2 is 100 (not beyond stop) -> stop fills at the barrier level dn.
    assert row["exit_price"] == pytest.approx(dn)


def test_pt_fills_at_limit_even_when_high_exceeds() -> None:
    cfg = _free_cfg()
    p0 = 100.0
    w = 0.01 * np.sqrt(5)
    up = p0 * np.exp(w)
    opens = [100.0, 100.0, 100.0, 100.0]
    highs = list(opens)
    highs[2] = up + 5.0  # blows way past PT
    bars = _bars(_PERP_ID, opens, highs=highs, lows=opens)
    events = _event(0, side=1)
    vol = _vol_series(bars, 0.01)
    out = _run(bars, events, cfg, vol=vol)
    row = out.iloc[0]
    assert row["touch"] == 1
    assert row["exit_price"] == pytest.approx(up)  # never better than the resting limit


def test_gap_through_stop_is_worse_than_barrier_fill() -> None:
    cfg = _free_cfg()
    p0 = 100.0
    w = 0.01 * np.sqrt(5)
    dn = p0 * np.exp(-w)  # ≈ 97.79
    opens = [100.0, 100.0, 90.0, 90.0]  # bar 2 GAPS far below the stop
    lows = list(opens)
    bars = _bars(_PERP_ID, opens, highs=opens, lows=lows)
    events = _event(0, side=1)
    vol = _vol_series(bars, 0.01)
    out = _run(bars, events, cfg, vol=vol)
    row = out.iloc[0]
    assert row["exit_price"] == pytest.approx(90.0)  # fills at the open (worse than dn)
    counterfactual = np.log(dn / p0)
    assert row["ret_gross"] < counterfactual  # gap fill strictly more negative


def test_vertical_exit_at_next_open_not_close() -> None:
    cfg = _free_cfg()  # H=5
    # Flat-ish path that never touches; vertical exits at O(τ+(1+H)Δ).
    opens = [100.0, 100.0, 100.1, 100.2, 100.1, 100.0, 100.3, 100.5]
    closes = [o + 50.0 for o in opens]  # closes WILDLY different -> proves we use opens
    bars = _bars(
        _PERP_ID,
        opens,
        highs=[o + 0.01 for o in opens],
        lows=[o - 0.01 for o in opens],
        closes=closes,
    )
    events = _event(0, side=1)
    vol = _vol_series(bars, 0.01)
    out = _run(bars, events, cfg, vol=vol)
    row = out.iloc[0]
    vert_ts = (1 + 5) * _H1_MS
    assert row["touch"] == 0
    assert row["t1"] == vert_ts
    assert row["exit_price"] == pytest.approx(100.3)  # O(τ+6Δ), NOT the close 150.3
    assert row["exit_price"] != pytest.approx(closes[6])


# ----------------------------------------------------------------- cost / funding


def test_cost_honest_net_subtracts_roundtrip_and_funding() -> None:
    # Small gross-positive vertical that flips meta_label to 0 once costs net out.
    cfg = TripleBarrierConfig(horizon_bars=2, cost_honest=True)
    # vertical: opens flat at entry, tiny positive drift to exit.
    p0 = 100.0
    exit_px = 100.02  # +2bp gross
    opens = [100.0, p0, 100.0, exit_px]
    bars = _bars(_PERP_ID, opens, highs=[o + 0.001 for o in opens], lows=[o - 0.001 for o in opens])
    events = _event(0, side=1)
    vol = _vol_series(bars, 0.05)  # wide barriers so no touch -> vertical
    cost = TransactionCostModel()
    inst = _perp()
    # funding rate published before decision: +10 bp per settlement.
    funding = pd.DataFrame(
        {
            "ts_funding": np.array([0], dtype=np.int64),
            "instrument_id": [_PERP_ID],
            "rate": [0.001],
            "available_at": np.array([0], dtype=np.int64),  # known at decision τ+Δ
        }
    )
    out = _run(
        bars, events, cfg, cost_model=cost, instruments={_PERP_ID: inst}, funding=funding, vol=vol
    )
    row = out.iloc[0]
    rg = np.log(exit_px / p0)
    roundtrip = 2.0 * (cost.fee_frac(inst, Liquidity.TAKER) + cost.half_spread_frac(inst))
    n_funding = int(row["n_funding"])
    funding_cost = 1 * 0.001 * n_funding  # s=+1 long pays positive funding
    assert row["ret_gross"] == pytest.approx(rg)
    assert row["ret"] == pytest.approx(rg - roundtrip - funding_cost)
    assert row["ret"] < 0.0  # costs + funding overwhelm the +2bp gross
    assert row["meta_label"] == 0  # computed on the NET ret


def test_funding_pit_ignores_future_rate_change() -> None:
    # f_hat must be the rate available at τ+Δ, never a later settlement.
    cfg = TripleBarrierConfig(horizon_bars=2, cost_honest=True)
    opens = [100.0, 100.0, 100.0, 100.0]
    bars = _bars(_PERP_ID, opens, highs=[o + 0.001 for o in opens], lows=[o - 0.001 for o in opens])
    events = _event(0, side=1)
    vol = _vol_series(bars, 0.05)
    inst = _perp()
    cost = TransactionCostModel()
    # rate known at decision = 5bp; a 500bp rate published AFTER decision must be ignored.
    funding = pd.DataFrame(
        {
            "ts_funding": np.array([0, _H1_MS], dtype=np.int64),
            "instrument_id": [_PERP_ID, _PERP_ID],
            "rate": [0.0005, 0.05],
            "available_at": np.array([0, 2 * _H1_MS], dtype=np.int64),  # 2nd available AFTER τ+Δ=Δ
        }
    )
    out = _run(
        bars, events, cfg, cost_model=cost, instruments={_PERP_ID: inst}, funding=funding, vol=vol
    )
    row = out.iloc[0]
    roundtrip = 2.0 * (cost.fee_frac(inst, Liquidity.TAKER) + cost.half_spread_frac(inst))
    n_funding = int(row["n_funding"])
    expected_funding_cost = 1 * 0.0005 * n_funding  # uses the 5bp rate, NOT 500bp
    assert row["ret"] == pytest.approx(0.0 - roundtrip - expected_funding_cost)


def test_funding_count_scales_with_interval() -> None:
    # 4h interval gets exactly 2x the settlements of 8h over the same hold (property).
    cfg = TripleBarrierConfig(horizon_bars=24, cost_honest=True)
    opens = [100.0] * 30
    bars8 = _bars(
        _PERP_ID, opens, highs=[o + 0.001 for o in opens], lows=[o - 0.001 for o in opens]
    )
    events = _event(0, side=1)
    vol = _vol_series(bars8, 0.5)  # huge barriers -> always vertical
    cost = TransactionCostModel()
    funding = pd.DataFrame(
        {
            "ts_funding": np.array([0], dtype=np.int64),
            "instrument_id": [_PERP_ID],
            "rate": [0.0001],
            "available_at": np.array([0], dtype=np.int64),
        }
    )
    out8 = _run(
        bars8, events, cfg, cost_model=cost,
        instruments={_PERP_ID: _perp(funding_interval_hours=8)}, funding=funding, vol=vol,
    )
    out4 = _run(
        bars8, events, cfg, cost_model=cost,
        instruments={_PERP_ID: _perp(funding_interval_hours=4)}, funding=funding, vol=vol,
    )
    n8 = int(out8.iloc[0]["n_funding"])
    n4 = int(out4.iloc[0]["n_funding"])
    assert n8 >= 1
    assert n4 == 2 * n8


def test_negative_funding_increases_long_label() -> None:
    # alphaDesign §10.3 regression: a negative-funding window (shorts pay) must
    # INCREASE a long's labeled ret vs the zero-funding counterfactual.
    cfg = TripleBarrierConfig(horizon_bars=24, cost_honest=True)
    opens = [100.0] * 30
    bars = _bars(_PERP_ID, opens, highs=[o + 0.001 for o in opens], lows=[o - 0.001 for o in opens])
    events = _event(0, side=1)
    vol = _vol_series(bars, 0.5)
    cost = TransactionCostModel()
    inst = _perp()
    neg = pd.DataFrame(
        {"ts_funding": np.array([0], dtype=np.int64), "instrument_id": [_PERP_ID],
         "rate": [-0.001], "available_at": np.array([0], dtype=np.int64)}
    )
    out_neg = _run(
        bars, events, cfg, cost_model=cost, instruments={_PERP_ID: inst}, funding=neg, vol=vol
    )
    out_zero = _run(
        bars, events, cfg, cost_model=cost, instruments={_PERP_ID: inst}, funding=None, vol=vol
    )
    assert out_neg.iloc[0]["ret"] > out_zero.iloc[0]["ret"]


def test_spot_has_no_funding() -> None:
    cfg = TripleBarrierConfig(horizon_bars=3, cost_honest=True)
    opens = [100.0] * 8
    bars = _bars(_SPOT_ID, opens, highs=[o + 0.001 for o in opens], lows=[o - 0.001 for o in opens])
    events = _event(0, instrument_id=_SPOT_ID, side=1)
    vol = _vol_series(bars, 0.5)
    out = _run(bars, events, cfg, instruments={_SPOT_ID: _spot()}, vol=vol)
    assert int(out.iloc[0]["n_funding"]) == 0


# ----------------------------------------------------------------- side = -1


def test_short_win_symmetry() -> None:
    # Mirrored falling path: a short's PT barrier dn (below) is hit -> winning short.
    cfg = _free_cfg()
    p0 = 100.0
    w = 0.01 * np.sqrt(5)
    dn = p0 * np.exp(-w)  # PT for s=-1 is below
    opens = [100.0, 100.0, 100.0, 100.0]
    lows = list(opens)
    lows[2] = dn - 0.001  # bar 2 low pierces the (below) PT exactly
    bars = _bars(_PERP_ID, opens, highs=opens, lows=lows)
    events = _event(0, side=-1)
    vol = _vol_series(bars, 0.01)
    out = _run(bars, events, cfg, vol=vol)
    row = out.iloc[0]
    assert row["touch"] == 1  # profit-take
    assert row["label_tb"] == -1  # +s = -1 for a short
    assert row["exit_price"] == pytest.approx(dn)  # PT fills at the limit
    assert row["ret_gross"] > 0.0  # short profited as price fell
    assert row["meta_label"] == 1  # net (cost-free) win
    assert row["side"] == -1


def test_flipping_side_flips_label_for_same_path() -> None:
    cfg = _free_cfg()
    opens = [100.0, 100.0, 99.0, 98.0, 97.0, 96.0, 95.0]  # falling
    bars = _bars(_PERP_ID, opens, highs=opens, lows=opens)
    vol = _vol_series(bars, 0.01)
    cm = TransactionCostModel()
    inst = {_PERP_ID: _perp()}
    long_out = _run(bars, _event(0, side=1), cfg, cost_model=cm, instruments=inst, vol=vol)
    short_out = _run(bars, _event(0, side=-1), cfg, cost_model=cm, instruments=inst, vol=vol)
    # Falling path: long stops out (label -1), short profit-takes (label -side = +1... = -1?).
    assert long_out.iloc[0]["label_tb"] == -1  # long stop -> -s = -1
    assert short_out.iloc[0]["label_tb"] == -1  # short PT -> +s = -1
    # but meta_label diverges: long loses, short wins.
    assert long_out.iloc[0]["meta_label"] == 0
    assert short_out.iloc[0]["meta_label"] == 1


# --------------------------------------------------------------------------- gaps


@pytest.mark.parametrize("drop_idx", [1, 3, 6])  # entry bar, interior, vertical bar
def test_gap_yields_nan_no_bridge(drop_idx: int) -> None:
    cfg = _free_cfg()  # H=5 -> vertical bar at index 6
    opens = [100.0, 100.0, 100.1, 100.2, 100.1, 100.0, 100.3]
    bars = _bars(_PERP_ID, opens, highs=[o + 0.001 for o in opens], lows=[o - 0.001 for o in opens])
    vol = _vol_series(bars, 0.01)
    # drop the target bar to simulate a gap; neighbours stay intact.
    bars_gapped = bars.drop(index=drop_idx).reset_index(drop=True)
    out = _run(bars_gapped, _event(0, side=1), cfg, vol=vol)
    row = out.iloc[0]
    assert np.isnan(row["entry_price"])
    assert np.isnan(row["t1"])
    assert np.isnan(row["ret"])
    assert row["label_tb"] == 0
    assert row["touch"] == 0
    assert row["meta_label"] == 0


def test_gap_neighbour_event_unaffected() -> None:
    cfg = _free_cfg()
    opens = [100.0, 100.0, 100.5, 101.0, 101.5, 102.0, 103.0, 104.0, 105.0, 106.0]
    bars = _bars(_PERP_ID, opens, highs=opens, lows=[o - 0.001 for o in opens])
    vol = _vol_series(bars, 0.01)
    events = pd.concat([_event(0, side=1), _event(2 * _H1_MS, side=1)], ignore_index=True)
    full = _run(bars, events, cfg, vol=vol)
    # both events resolve cleanly on the full panel.
    assert full.notna()["t1"].all()


# ------------------------------------------------------------------ PIT / leakage


def test_pit_truncation_invariance() -> None:
    # Truncating the panel AFTER a resolved event must not change its label.
    cfg = _free_cfg()
    opens = [100.0, 100.0, 100.5, 101.0, 101.5, 102.0, 103.0, 104.0, 200.0, 300.0]
    bars = _bars(_PERP_ID, opens, highs=opens, lows=[o - 0.001 for o in opens])
    vol = _vol_series(bars, 0.01)
    events = _event(0, side=1)
    inst = {_PERP_ID: _perp()}
    cm = TransactionCostModel()
    full = _run(bars, events, cfg, cost_model=cm, instruments=inst, vol=vol)
    # Event touches PT at ts=6Δ; bars after that (the 200/300 spikes) must be irrelevant.
    t1_bar = int(full.iloc[0]["t1"] // _H1_MS)
    truncated = bars.iloc[: t1_bar + 1].reset_index(drop=True)
    vol_trunc = _vol_series(truncated, 0.01)
    out_trunc = _run(truncated, events, cfg, cost_model=cm, instruments=inst, vol=vol_trunc)
    pd.testing.assert_series_equal(full.iloc[0], out_trunc.iloc[0])


def test_sigma_truncation_invariant_when_computed() -> None:
    # sigma_hat computed on the grid is identical whether or not later bars exist (finding 8).
    rng = np.random.default_rng(0)
    opens = list(100.0 * np.exp(np.cumsum(rng.normal(0, 0.005, 300))))
    bars = _bars(_PERP_ID, opens, highs=[o * 1.001 for o in opens], lows=[o * 0.999 for o in opens])
    cfg = TripleBarrierConfig(horizon_bars=10, cost_honest=False)
    events = _event(200 * _H1_MS, side=1)
    inst = {_PERP_ID: _perp()}
    cm = TransactionCostModel()
    full = _run(bars, events, cfg, cost_model=cm, instruments=inst)
    # truncate just past the event's path window.
    truncated = bars.iloc[:215].reset_index(drop=True)
    trunc = _run(truncated, events, cfg, cost_model=cm, instruments=inst)
    assert full.iloc[0]["vol_at_entry"] == pytest.approx(trunc.iloc[0]["vol_at_entry"])


def test_meta_label_on_net_not_gross() -> None:
    # finding 11: meta_label is 1{net>0}; a gross-positive event with bigger costs -> 0.
    cfg = TripleBarrierConfig(horizon_bars=2, cost_honest=True)
    opens = [100.0, 100.0, 100.0, 100.05]  # +5bp gross vertical
    bars = _bars(_PERP_ID, opens, highs=[o + 0.001 for o in opens], lows=[o - 0.001 for o in opens])
    events = _event(0, side=1)
    vol = _vol_series(bars, 0.05)
    out = _run(bars, events, cfg, funding=None, vol=vol)
    row = out.iloc[0]
    assert row["ret_gross"] > 0.0
    assert row["ret"] < row["ret_gross"]
    assert row["meta_label"] == (1 if row["ret"] > 0 else 0)


# ------------------------------------------------------------------- validations


def test_immutability() -> None:
    opens = [100.0, 100.0, 100.5, 101.0, 101.5, 102.0, 103.0]
    bars = _bars(_PERP_ID, opens)
    events = _event(0, side=1)
    funding = pd.DataFrame(
        {"ts_funding": np.array([0], dtype=np.int64), "instrument_id": [_PERP_ID],
         "rate": [0.001], "available_at": np.array([0], dtype=np.int64)}
    )
    bars_copy = bars.copy(deep=True)
    events_copy = events.copy(deep=True)
    funding_copy = funding.copy(deep=True)
    _run(bars, events, TripleBarrierConfig(horizon_bars=5, cost_honest=True), funding=funding)
    pd.testing.assert_frame_equal(bars, bars_copy)
    pd.testing.assert_frame_equal(events, events_copy)
    pd.testing.assert_frame_equal(funding, funding_copy)


def test_missing_bar_column_raises() -> None:
    bars = _bars(_PERP_ID, [100.0, 101.0]).drop(columns=["high"])
    with pytest.raises(ValueError, match="missing required columns"):
        _run(bars, _event(0), _free_cfg())


def test_duplicate_event_raises() -> None:
    bars = _bars(_PERP_ID, [100.0, 101.0, 102.0])
    events = pd.concat([_event(0), _event(0)], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        _run(bars, events, _free_cfg())


def test_non_positive_price_raises() -> None:
    bars = _bars(_PERP_ID, [100.0, -1.0, 102.0])
    with pytest.raises(ValueError, match="non-positive"):
        _run(bars, _event(0), _free_cfg())


def test_non_int_ts_open_raises() -> None:
    bars = _bars(_PERP_ID, [100.0, 101.0])
    bars["ts_open"] = bars["ts_open"].astype(float)
    with pytest.raises(TypeError, match="ts_open"):
        _run(bars, _event(0), _free_cfg())


def test_bad_side_raises() -> None:
    bars = _bars(_PERP_ID, [100.0, 101.0, 102.0])
    events = _event(0, side=1)
    events["side"] = [0]
    with pytest.raises(ValueError, match="side"):
        _run(bars, events, _free_cfg())


def test_missing_perp_instrument_raises_keyerror() -> None:
    bars = _bars(_PERP_ID, [100.0, 101.0, 102.0])
    with pytest.raises(KeyError, match="metadata"):
        _run(bars, _event(0), _free_cfg(), instruments={})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"horizon_bars": 0},
        {"pt_mult": 0.0},
        {"sl_mult": -1.0},
        {"vol_span": 0},
        {"vertical_zero_band": -0.1},
    ],
)
def test_bad_config_raises(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        TripleBarrierConfig(**kwargs)  # type: ignore[arg-type]


def test_use_numba_requested_unavailable_raises() -> None:
    bars = _bars(_PERP_ID, [100.0, 101.0, 102.0])
    with pytest.raises(NotImplementedError, match="numba"):
        _run(bars, _event(0), TripleBarrierConfig(use_numba=True))


def test_output_schema_and_index() -> None:
    cfg = _free_cfg()
    opens = [100.0, 100.0, 100.5, 101.0, 101.5, 102.0, 103.0]
    bars = _bars(_PERP_ID, opens)
    out = _run(bars, _event(0), cfg)
    assert list(out.columns) == [
        "entry_ts", "entry_price", "t1", "exit_price", "ret_gross", "ret",
        "label_tb", "touch", "side", "meta_label", "vol_at_entry", "n_funding",
    ]
    assert out.index.names == ["ts_open", "instrument_id"]
    assert out["label_tb"].dtype == np.int8
    assert out["side"].dtype == np.int8
