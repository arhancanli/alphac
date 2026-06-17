"""Unit tests for alphaforge.labeling.meta — meta-label dataset assembly (§5.3, §4.3).

Covers: ``make_meta_labels`` net-return semantics + NaN masking (leakageCritique
findings 2/11); the ``make_meta_label_dataset`` composer (triple_barrier · weights ·
forward_returns alignment, feature/label disjointness, NaN-sentinel dropping, forward
diagnostics, immutability, validations); and that ``bet_size_from_prob`` is the single
re-exported canonical seam (findings 1/6/16). All fixtures are synthetic — the live
data lake is never touched.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alphaforge.core.instruments import Instrument
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass, Liquidity, MarketType
from alphaforge.costs.model import TransactionCostModel
from alphaforge.labeling.meta import (
    DEFAULT_FORWARD_HORIZONS,
    MetaLabelDataset,
    bet_size_from_prob,
    make_meta_label_dataset,
    make_meta_labels,
)
from alphaforge.labeling.triple_barrier import TripleBarrierConfig

_H1_MS = Timeframe.H1.ms
_PERP_ID = "BINANCE:PERP:BTCUSDT"
_ETH_ID = "BINANCE:PERP:ETHUSDT"
_SPOT_ID = "BINANCE:SPOT:ETHUSDT"

_INDEX_NAMES = ("ts_open", "instrument_id")

# (bars, events, cfg, cost_model, instruments) — the resolving-setup tuple.
_Setup = tuple[
    pd.DataFrame,
    pd.DataFrame,
    TripleBarrierConfig,
    TransactionCostModel,
    dict[str, Instrument],
]


# --------------------------------------------------------------------------- fixtures


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


def _bars(
    instrument_id: str,
    opens: list[float],
    *,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    closes: list[float] | None = None,
    start_ms: int = 0,
) -> pd.DataFrame:
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


def _events(rows: list[tuple[int, str, int]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": np.array([r[0] for r in rows], dtype=np.int64),
            "instrument_id": [r[1] for r in rows],
            "side": np.array([r[2] for r in rows], dtype=np.int8),
        }
    )


def _vol_series(bars: pd.DataFrame, sigma: float) -> pd.Series:
    idx = pd.MultiIndex.from_arrays(
        [bars["ts_open"].to_numpy(), bars["instrument_id"].to_numpy()],
        names=_INDEX_NAMES,
    )
    return pd.Series(sigma, index=idx, dtype="float64")


def _features(index: pd.MultiIndex, n_cols: int = 3, *, seed: int = 0) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    data = {f"f{i}": rng.randn(len(index)) for i in range(n_cols)}
    return pd.DataFrame(data, index=index)


def _label_frame(rets: list[float], sides: list[int]) -> pd.DataFrame:
    """A minimal §1.3-shaped frame with explicit ``ret``/``side`` for make_meta_labels."""
    idx = pd.MultiIndex.from_arrays(
        [[i * _H1_MS for i in range(len(rets))], [_PERP_ID] * len(rets)],
        names=_INDEX_NAMES,
    )
    return pd.DataFrame({"ret": rets, "side": sides}, index=idx)


# --------------------------------------------------------------------------- make_meta_labels


class TestMakeMetaLabels:
    def test_one_if_net_ret_positive(self) -> None:
        labels = _label_frame([0.01, -0.02, 0.0, 0.5], [1, 1, 1, -1])
        y = make_meta_labels(labels)
        assert y.name == "meta_label"
        # 1{ ret > 0 } on the SIDE-SIGNED net return; ret == 0 is NOT a win.
        assert list(y.dropna().to_numpy()) == [1, 0, 0, 1]

    def test_no_double_side_application(self) -> None:
        # A winning SHORT already carries a POSITIVE ret (ret = s·ln(...)); the label is
        # 1, NOT s·ret folded again (which would invert it). finding 2.
        labels = _label_frame([0.03], [-1])  # short with positive net ret = a win
        y = make_meta_labels(labels)
        assert int(y.iloc[0]) == 1

    def test_nan_ret_masked(self) -> None:
        labels = _label_frame([0.01, np.nan, -0.02], [1, 1, 1])
        y = make_meta_labels(labels)
        assert y.isna().to_numpy().tolist() == [False, True, False]
        # masked, not coerced to 0
        assert y.dtype == "Int8"

    def test_computed_on_net_not_gross(self) -> None:
        # make_meta_labels reads 'ret' (net) only; a gross-positive/net-negative row -> 0.
        labels = _label_frame([-0.001], [1])  # net negative after costs
        assert int(make_meta_labels(labels).iloc[0]) == 0

    def test_missing_ret_column_raises(self) -> None:
        labels = _label_frame([0.01], [1]).drop(columns=["ret"])
        with pytest.raises(ValueError, match="ret"):
            make_meta_labels(labels)


# --------------------------------------------------------------------------- bet_size seam


class TestBetSizeReexport:
    def test_is_the_canonical_ml_implementation(self) -> None:
        # Single definition (findings 1/6/16): meta.bet_size_from_prob IS ml.model's.
        from alphaforge.ml.model import bet_size_from_prob as canonical

        assert bet_size_from_prob is canonical

    def test_sign_is_side_never_flips(self) -> None:
        rng = np.random.RandomState(7)
        idx = pd.RangeIndex(200)
        p = pd.Series(rng.uniform(0.0, 1.0, 200), index=idx)
        side = pd.Series(rng.choice([-1.0, 1.0], 200), index=idx)
        size = bet_size_from_prob(p, side)
        nz = size.to_numpy() != 0.0
        assert np.all(np.sign(size.to_numpy()[nz]) == side.to_numpy()[nz])


# --------------------------------------------------------------------------- composer


def _resolving_setup(*, horizon: int = 4, n_bars: int = 12) -> _Setup:
    """A drifting-up perp path so a +1 long touches PT early (a resolved label)."""
    opens = [100.0 * (1.0 + 0.01 * i) for i in range(n_bars)]
    highs = [o * 1.03 for o in opens]  # wide highs so PT is reachable
    lows = [o * 0.995 for o in opens]
    bars = _bars(_PERP_ID, opens, highs=highs, lows=lows)
    events = _events([(0, _PERP_ID, 1), (1 * _H1_MS, _PERP_ID, 1)])
    cfg = TripleBarrierConfig(horizon_bars=horizon, cost_honest=False)
    return bars, events, cfg, TransactionCostModel(), {_PERP_ID: _perp()}


class TestMakeMetaLabelDataset:
    def test_assembles_aligned_panel(self) -> None:
        bars, events, cfg, cm, insts = _resolving_setup()
        # Feature panel on the decision-tau index of the events (+ extra rows ignored).
        feat_idx = pd.MultiIndex.from_arrays(
            [[i * _H1_MS for i in range(6)], [_PERP_ID] * 6], names=_INDEX_NAMES
        )
        features = _features(feat_idx)
        vol = _vol_series(bars, 0.02)
        ds = make_meta_label_dataset(
            bars, events, features, cfg, cost_model=cm, instruments=insts, vol=vol
        )
        assert isinstance(ds, MetaLabelDataset)
        X, y, w, t1, side = ds.matrices()
        # All five members share ONE index (the resolved, weighted, feature-present rows).
        for member in (y, w, t1, side):
            assert member.index.equals(X.index)
        assert list(X.index.names) == list(_INDEX_NAMES)
        assert y.name == "meta_label" and w.name == "sample_weight"
        assert t1.name == "t1" and side.name == "side"
        assert y.dtype == "int8" and side.dtype == "int8" and t1.dtype == "int64"
        assert (w.to_numpy() >= 0.0).all() and not w.isna().any()
        assert ds.feature_names == ("f0", "f1", "f2")
        assert list(X.columns) == ["f0", "f1", "f2"]

    def test_target_matches_labeler_meta_label(self) -> None:
        bars, events, cfg, cm, insts = _resolving_setup()
        feat_idx = pd.MultiIndex.from_arrays(
            [[i * _H1_MS for i in range(6)], [_PERP_ID] * 6], names=_INDEX_NAMES
        )
        features = _features(feat_idx)
        vol = _vol_series(bars, 0.02)
        ds = make_meta_label_dataset(
            bars, events, features, cfg, cost_model=cm, instruments=insts, vol=vol
        )
        # target == 1{ net ret > 0 } on the kept rows; the up-drift long should win.
        ret = ds.labels.loc[ds.target.index, "ret"].to_numpy()
        expected = (ret > 0.0).astype("int8")
        np.testing.assert_array_equal(ds.target.to_numpy(), expected)

    def test_feature_label_disjoint_enforced(self) -> None:
        bars, events, cfg, cm, insts = _resolving_setup()
        feat_idx = pd.MultiIndex.from_arrays(
            [[i * _H1_MS for i in range(6)], [_PERP_ID] * 6], names=_INDEX_NAMES
        )
        # A feature column named like a label column must raise (forward-looking leak).
        features = _features(feat_idx).assign(ret=0.0)
        vol = _vol_series(bars, 0.02)
        with pytest.raises(ValueError, match="label space"):
            make_meta_label_dataset(
                bars, events, features, cfg, cost_model=cm, instruments=insts, vol=vol
            )

    def test_forward_returns_attached_as_diagnostics(self) -> None:
        bars, events, cfg, cm, insts = _resolving_setup(n_bars=200)
        feat_idx = pd.MultiIndex.from_arrays(
            [[i * _H1_MS for i in range(2)], [_PERP_ID] * 2], names=_INDEX_NAMES
        )
        features = _features(feat_idx)
        vol = _vol_series(bars, 0.02)
        ds = make_meta_label_dataset(
            bars, events, features, cfg, cost_model=cm, instruments=insts, vol=vol
        )
        for h in DEFAULT_FORWARD_HORIZONS:
            assert f"fwd_ret_{h}" in ds.labels.columns
        assert "fwd_ret_72_volscaled" in ds.labels.columns
        # The forward-return columns live ONLY in the diagnostic frame, never in X.
        assert not any(c.startswith("fwd_ret") for c in ds.features.columns)

    def test_nan_sentinel_rows_dropped(self) -> None:
        # An event near the end of the panel cannot resolve (no path bars) -> NaN label,
        # dropped from the dataset; an earlier resolving event survives.
        opens = [100.0 * (1.0 + 0.01 * i) for i in range(8)]
        bars = _bars(
            _PERP_ID, opens, highs=[o * 1.03 for o in opens], lows=[o * 0.99 for o in opens]
        )
        # second event's decision tau is the last bar -> entry bar missing -> sentinel.
        events = _events([(0, _PERP_ID, 1), (7 * _H1_MS, _PERP_ID, 1)])
        cfg = TripleBarrierConfig(horizon_bars=4, cost_honest=False)
        feat_idx = pd.MultiIndex.from_arrays([[0, 7 * _H1_MS], [_PERP_ID] * 2], names=_INDEX_NAMES)
        features = _features(feat_idx)
        vol = _vol_series(bars, 0.02)
        ds = make_meta_label_dataset(
            bars,
            events,
            features,
            cfg,
            cost_model=TransactionCostModel(),
            instruments={_PERP_ID: _perp()},
            vol=vol,
        )
        assert (0, _PERP_ID) in ds.target.index
        assert (7 * _H1_MS, _PERP_ID) not in ds.target.index

    def test_inner_join_on_features(self) -> None:
        # An event with NO feature row at its decision tau is dropped (inner alignment).
        bars, events, cfg, cm, insts = _resolving_setup()
        # features cover only the FIRST event's tau (ts_open == 0).
        feat_idx = pd.MultiIndex.from_arrays([[0], [_PERP_ID]], names=_INDEX_NAMES)
        features = _features(feat_idx)
        vol = _vol_series(bars, 0.02)
        ds = make_meta_label_dataset(
            bars, events, features, cfg, cost_model=cm, instruments=insts, vol=vol
        )
        assert (0, _PERP_ID) in ds.target.index
        assert (1 * _H1_MS, _PERP_ID) not in ds.target.index

    def test_feature_names_subset_pinned(self) -> None:
        bars, events, cfg, cm, insts = _resolving_setup()
        feat_idx = pd.MultiIndex.from_arrays(
            [[i * _H1_MS for i in range(6)], [_PERP_ID] * 6], names=_INDEX_NAMES
        )
        features = _features(feat_idx, n_cols=4)
        vol = _vol_series(bars, 0.02)
        ds = make_meta_label_dataset(
            bars,
            events,
            features,
            cfg,
            cost_model=cm,
            instruments=insts,
            vol=vol,
            feature_names=["f2", "f0"],
        )
        assert ds.feature_names == ("f2", "f0")
        assert list(ds.features.columns) == ["f2", "f0"]  # order pinned exactly

    def test_unknown_feature_name_raises(self) -> None:
        bars, events, cfg, cm, insts = _resolving_setup()
        feat_idx = pd.MultiIndex.from_arrays(
            [[i * _H1_MS for i in range(6)], [_PERP_ID] * 6], names=_INDEX_NAMES
        )
        features = _features(feat_idx)
        vol = _vol_series(bars, 0.02)
        with pytest.raises(KeyError, match="not in features"):
            make_meta_label_dataset(
                bars,
                events,
                features,
                cfg,
                cost_model=cm,
                instruments=insts,
                vol=vol,
                feature_names=["f0", "does_not_exist"],
            )

    def test_non_multiindex_features_raise(self) -> None:
        bars, events, cfg, cm, insts = _resolving_setup()
        features = pd.DataFrame({"f0": [1.0]}, index=pd.RangeIndex(1))
        with pytest.raises(ValueError, match="MultiIndex"):
            make_meta_label_dataset(bars, events, features, cfg, cost_model=cm, instruments=insts)

    def test_inputs_not_mutated(self) -> None:
        bars, events, cfg, cm, insts = _resolving_setup()
        feat_idx = pd.MultiIndex.from_arrays(
            [[i * _H1_MS for i in range(6)], [_PERP_ID] * 6], names=_INDEX_NAMES
        )
        features = _features(feat_idx)
        vol = _vol_series(bars, 0.02)
        bars_copy = bars.copy(deep=True)
        events_copy = events.copy(deep=True)
        features_copy = features.copy(deep=True)
        make_meta_label_dataset(
            bars, events, features, cfg, cost_model=cm, instruments=insts, vol=vol
        )
        pd.testing.assert_frame_equal(bars, bars_copy)
        pd.testing.assert_frame_equal(events, events_copy)
        pd.testing.assert_frame_equal(features, features_copy)

    def test_cost_honest_funding_path_runs(self) -> None:
        # The full cost-honest path with a funding frame composes end-to-end and the
        # net label can flip a thin gross win to a loss.
        bars, events, _cfg, cm, insts = _resolving_setup(horizon=4)
        cfg = TripleBarrierConfig(horizon_bars=4, cost_honest=True)
        funding = pd.DataFrame(
            {
                "ts_funding": np.array([0], dtype=np.int64),
                "instrument_id": [_PERP_ID],
                "rate": [0.0001],
                "available_at": np.array([0], dtype=np.int64),
            }
        )
        feat_idx = pd.MultiIndex.from_arrays(
            [[i * _H1_MS for i in range(6)], [_PERP_ID] * 6], names=_INDEX_NAMES
        )
        features = _features(feat_idx)
        vol = _vol_series(bars, 0.02)
        ds = make_meta_label_dataset(
            bars,
            events,
            features,
            cfg,
            cost_model=cm,
            instruments=insts,
            funding=funding,
            vol=vol,
        )
        # ret is net of round-trip cost (2·(fee+half_spread)) -> strictly below ret_gross.
        net = ds.labels["ret"].to_numpy()
        gross = ds.labels["ret_gross"].to_numpy()
        assert np.all(net < gross)
        roundtrip = 2.0 * (
            cm.fee_frac(insts[_PERP_ID], Liquidity.TAKER) + cm.half_spread_frac(insts[_PERP_ID])
        )
        assert roundtrip > 0.0
