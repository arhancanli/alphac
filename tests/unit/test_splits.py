"""Unit + exhaustive property tests for alphaforge.validation.splits.

THE splitter (leakage finding 16): the invariants asserted here over a
parameter sweep are the leakage contract — no train timestamp's label
interval may touch a test span, no train timestamp may sit in the embargo
window after a test span, and the test spans must tile the evaluable grid
exactly once. All grids are synthetic 1h grids; everything is offline and
deterministic.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from alphaforge.config.settings import Settings
from alphaforge.validation.splits import PurgedWalkForward

HOUR = 3_600_000
T0 = 1_700_000_400_000  # arbitrary 1h-aligned epoch ms


def grid(n: int, *, step: int = HOUR) -> np.ndarray:
    return T0 + step * np.arange(n, dtype=np.int64)


# ----------------------------------------------------------------- validation


def test_rejects_nonpositive_train_test() -> None:
    with pytest.raises(ValueError, match="train_bars/test_bars"):
        PurgedWalkForward(0, 24, purge_bars=4)
    with pytest.raises(ValueError, match="train_bars/test_bars"):
        PurgedWalkForward(48, 0, purge_bars=4)


def test_rejects_negative_purge_or_embargo() -> None:
    with pytest.raises(ValueError, match="purge_bars/embargo_bars"):
        PurgedWalkForward(48, 24, purge_bars=-1)
    with pytest.raises(ValueError, match="purge_bars/embargo_bars"):
        PurgedWalkForward(48, 24, purge_bars=4, embargo_bars=-1)


def test_rejects_purge_consuming_whole_train_window() -> None:
    with pytest.raises(ValueError, match="purged"):
        PurgedWalkForward(48, 24, purge_bars=48)


def test_rejects_purge_below_label_horizon() -> None:
    with pytest.raises(ValueError, match="label horizon"):
        PurgedWalkForward(200, 24, purge_bars=71, horizon_bars=72)
    # exactly h is allowed
    PurgedWalkForward(200, 24, purge_bars=72, horizon_bars=72)


def test_from_settings_wires_the_one_horizon_constant() -> None:
    settings = Settings()
    sp = PurgedWalkForward.from_settings(settings, train_bars=200, test_bars=24)
    assert sp.purge_bars == settings.signals.horizon_bars == 72
    assert sp.embargo_bars == 168


def test_from_settings_rejects_train_window_swallowed_by_purge() -> None:
    with pytest.raises(ValueError, match="purged"):
        PurgedWalkForward.from_settings(Settings(), train_bars=72, test_bars=24)


def test_split_rejects_bad_grids() -> None:
    sp = PurgedWalkForward(48, 24, purge_bars=4)
    with pytest.raises(ValueError, match="1-D"):
        list(sp.split(grid(100).reshape(10, 10)))
    with pytest.raises(ValueError, match="not a single test span"):
        list(sp.split(grid(48)))  # exactly train_bars: no test point left
    decreasing = grid(100)[::-1].copy()
    with pytest.raises(ValueError, match="strictly increasing"):
        list(sp.split(decreasing))
    irregular = grid(100)
    irregular[50] += 1
    with pytest.raises(ValueError, match="uniformly spaced"):
        list(sp.split(irregular))


# ---------------------------------------------------------- exhaustive sweep

SWEEP = list(
    itertools.product(
        (80, 96, 120),  # train_bars
        (24, 30, 48),  # test_bars
        (8, 24, 72),  # purge_bars
        (0, 168),  # embargo_bars
        (121, 240, 311),  # n grid points (forces a partial final leg sometimes)
    )
)


@pytest.mark.parametrize(("train", "test", "purge", "embargo", "n"), SWEEP)
def test_split_invariants(train: int, test: int, purge: int, embargo: int, n: int) -> None:
    """The leakage contract, exhaustively: tiling, purge distance, embargo, shape."""
    if purge >= train:
        pytest.skip("invalid configuration rejected at construction")
    sp = PurgedWalkForward(train, test, purge_bars=purge, embargo_bars=embargo)
    g = grid(n)
    splits = list(sp.split(g))

    assert len(splits) == sp.n_splits(n) > 0
    g_set = set(g.tolist())

    # Test spans tile [g[train], g[n-1]] without overlap or gap.
    all_test = np.concatenate([t for _, t in splits])
    np.testing.assert_array_equal(all_test, g[train:])

    for train_ts, test_ts in splits:
        test_start = int(test_ts[0])
        test_end_excl = int(test_ts[-1]) + HOUR

        # membership: every yielded ts is a grid point
        assert set(train_ts.tolist()) <= g_set
        assert set(test_ts.tolist()) <= g_set
        # train and test never intersect
        assert not set(train_ts.tolist()) & set(test_ts.tolist())
        # ordering inside each array
        assert bool(np.all(np.diff(train_ts) > 0))
        assert bool(np.all(np.diff(test_ts) > 0))

        # PURGE: no train sample's label interval [t, t + purge*Δ] touches the
        # test span — strictly, for EVERY pair.
        assert bool(np.all(train_ts + purge * HOUR < test_start))
        # EMBARGO: no train ts within embargo_bars after the test end.
        in_embargo = (train_ts >= test_end_excl) & (train_ts < test_end_excl + embargo * HOUR)
        assert not bool(in_embargo.any())
        # rolling-window shape: exactly train - purge survivors, window-bounded
        assert train_ts.shape == (train - purge,)
        assert int(train_ts[0]) == test_start - train * HOUR
        # final leg may be short; all others are exactly test_bars long
        assert 1 <= test_ts.shape[0] <= test

    full_legs = [t for _, t in splits[:-1]]
    assert all(t.shape == (test,) for t in full_legs)


def test_split_deterministic() -> None:
    sp = PurgedWalkForward(96, 48, purge_bars=72, embargo_bars=168)
    g = grid(400)
    a = list(sp.split(g))
    b = list(sp.split(g))
    assert len(a) == len(b)
    for (tr1, te1), (tr2, te2) in zip(a, b, strict=True):
        np.testing.assert_array_equal(tr1, tr2)
        np.testing.assert_array_equal(te1, te2)


def test_split_yields_copies() -> None:
    """Mutating a yielded array must not corrupt subsequent splits."""
    sp = PurgedWalkForward(80, 24, purge_bars=8)
    g = grid(160)
    first_train, first_test = next(iter(sp.split(g)))
    first_train[:] = 0
    first_test[:] = 0
    again_train, again_test = next(iter(sp.split(g)))
    assert int(again_train[0]) == T0
    assert int(again_test[0]) == T0 + 80 * HOUR


def test_known_small_example_exact() -> None:
    """Hand-checkable: train=6, test=3, purge=2 on a 12-point grid."""
    sp = PurgedWalkForward(6, 3, purge_bars=2, embargo_bars=4)
    g = grid(12)
    splits = list(sp.split(g))
    assert len(splits) == 2
    # split 0: test positions 6,7,8; train candidates 0..5, purge drops 4,5.
    np.testing.assert_array_equal(splits[0][0], g[[0, 1, 2, 3]])
    np.testing.assert_array_equal(splits[0][1], g[[6, 7, 8]])
    # split 1: test positions 9,10,11; train candidates 3..8, purge drops 7,8.
    np.testing.assert_array_equal(splits[1][0], g[[3, 4, 5, 6]])
    np.testing.assert_array_equal(splits[1][1], g[[9, 10, 11]])


def test_n_splits_arithmetic() -> None:
    sp = PurgedWalkForward(96, 48, purge_bars=72)
    assert sp.n_splits(96) == 0
    assert sp.n_splits(97) == 1
    assert sp.n_splits(96 + 48) == 1
    assert sp.n_splits(96 + 49) == 2
    assert sp.n_splits(96 + 3 * 48) == 3


def test_accepts_plain_sequence_input() -> None:
    sp = PurgedWalkForward(4, 2, purge_bars=1)
    ts = [T0 + k * HOUR for k in range(8)]
    splits = list(sp.split(ts))
    assert len(splits) == 2
    assert splits[0][1].dtype == np.int64
