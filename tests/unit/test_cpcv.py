"""Unit + exhaustive property tests for alphaforge.validation.cpcv.

CombinatorialPurgedCV is the research-protocol splitter (alphaDesign.md §7): it
must yield exactly ``C(N, k)`` splits whose train sets carry NO label leakage
into any test block (purge) and NO embargoed train decisions after any test
block, with the test groups tiling the grid so the per-group OOS predictions
assemble into ``phi = k·C(N, k)/N`` complete paths. The invariants asserted here
over a parameter sweep are that leakage contract. All grids are synthetic 1h
grids; everything is offline and deterministic.

The purge/embargo predicate is the SAME contract as PurgedWalkForward; one test
pins CPCV's behaviour against PurgedWalkForward directly on a layout both can
represent (a single trailing test group == one forward-chaining test leg).
"""

from __future__ import annotations

import itertools
from math import comb

import numpy as np
import pytest

from alphaforge.config.settings import Settings
from alphaforge.validation.cpcv import CombinatorialPurgedCV
from alphaforge.validation.splits import PurgedWalkForward

HOUR = 3_600_000
T0 = 1_700_000_400_000  # arbitrary 1h-aligned epoch ms


def grid(n: int, *, step: int = HOUR) -> np.ndarray:
    return T0 + step * np.arange(n, dtype=np.int64)


def flat_test_set(test_groups: tuple[np.ndarray, ...]) -> set[int]:
    """Union of all test-group timestamps as a Python set (helper, not a test)."""
    return set(np.concatenate(test_groups).tolist()) if test_groups else set()


# ----------------------------------------------------------------- validation


def test_rejects_too_few_groups() -> None:
    with pytest.raises(ValueError, match="n_groups must be >= 2"):
        CombinatorialPurgedCV(1, 1, purge_bars=4)


def test_rejects_bad_k_test() -> None:
    with pytest.raises(ValueError, match="1 <= k_test < n_groups"):
        CombinatorialPurgedCV(10, 0, purge_bars=4)
    with pytest.raises(ValueError, match="1 <= k_test < n_groups"):
        CombinatorialPurgedCV(10, 10, purge_bars=4)  # k == N leaves no train
    with pytest.raises(ValueError, match="1 <= k_test < n_groups"):
        CombinatorialPurgedCV(10, 11, purge_bars=4)


def test_rejects_negative_purge_or_embargo() -> None:
    with pytest.raises(ValueError, match="purge_bars/embargo_bars"):
        CombinatorialPurgedCV(10, 2, purge_bars=-1)
    with pytest.raises(ValueError, match="purge_bars/embargo_bars"):
        CombinatorialPurgedCV(10, 2, purge_bars=4, embargo_bars=-1)


def test_rejects_purge_below_label_horizon() -> None:
    with pytest.raises(ValueError, match="label horizon"):
        CombinatorialPurgedCV(10, 2, purge_bars=71, horizon_bars=72)
    # exactly h is allowed
    CombinatorialPurgedCV(10, 2, purge_bars=72, horizon_bars=72)


def test_from_settings_wires_the_one_horizon_constant() -> None:
    settings = Settings()
    cv = CombinatorialPurgedCV.from_settings(settings)
    assert cv.purge_bars == settings.signals.horizon_bars == 72
    assert cv.embargo_bars == 168
    assert cv.n_groups == 10
    assert cv.k_test == 2


def test_from_settings_passes_overrides() -> None:
    cv = CombinatorialPurgedCV.from_settings(Settings(), n_groups=8, k_test=3, embargo_bars=24)
    assert (cv.n_groups, cv.k_test, cv.embargo_bars) == (8, 3, 24)
    assert cv.purge_bars == 72


def test_split_rejects_bad_grids() -> None:
    cv = CombinatorialPurgedCV(5, 2, purge_bars=4)
    with pytest.raises(ValueError, match="1-D"):
        list(cv.split(grid(100).reshape(10, 10)))
    with pytest.raises(ValueError, match="< n_groups"):
        list(cv.split(grid(4)))  # fewer points than groups
    decreasing = grid(100)[::-1].copy()
    with pytest.raises(ValueError, match="strictly increasing"):
        list(cv.split(decreasing))
    irregular = grid(100)
    irregular[50] += 1
    with pytest.raises(ValueError, match="uniformly spaced"):
        list(cv.split(irregular))


# ----------------------------------------------------------------- counts


def test_n_splits_is_n_choose_k() -> None:
    assert CombinatorialPurgedCV(10, 2, purge_bars=4).n_splits == comb(10, 2) == 45
    assert CombinatorialPurgedCV(6, 3, purge_bars=4).n_splits == comb(6, 3) == 20
    assert CombinatorialPurgedCV(8, 1, purge_bars=4).n_splits == 8


def test_n_backtest_paths_formula() -> None:
    # phi = k*C(N,k)/N ; the canonical default gives 9.
    cv = CombinatorialPurgedCV(10, 2, purge_bars=4)
    assert cv.n_backtest_paths == 9
    assert cv.n_backtest_paths == cv.k_test * cv.n_splits // cv.n_groups
    # cross-check phi == C(N-1, k-1) and integer-exactness over a sweep
    for n_groups in range(2, 13):
        for k in range(1, n_groups):
            cv = CombinatorialPurgedCV(n_groups, k, purge_bars=4)
            phi = k * comb(n_groups, k) / n_groups
            assert phi == float(int(phi))  # always integral
            assert cv.n_backtest_paths == int(phi) == comb(n_groups - 1, k - 1)


def test_split_yields_exactly_n_splits() -> None:
    cv = CombinatorialPurgedCV(10, 2, purge_bars=8, embargo_bars=24)
    splits = list(cv.split(grid(500)))
    assert len(splits) == cv.n_splits == 45
    for _train, test_groups in splits:
        assert len(test_groups) == cv.k_test == 2


# ----------------------------------------------------------------- group layout


def test_group_bounds_tile_and_balance() -> None:
    # n divisible by N: equal sizes.
    b = CombinatorialPurgedCV._group_bounds(100, 10)
    assert b[0] == (0, 10) and b[-1] == (90, 100)
    assert all(hi - lo == 10 for lo, hi in b)
    # n not divisible: first (n mod N) groups get one extra (array_split convention).
    b = CombinatorialPurgedCV._group_bounds(103, 10)
    sizes = [hi - lo for lo, hi in b]
    assert sizes == [11, 11, 11, 10, 10, 10, 10, 10, 10, 10]
    # tile [0, n) with no gaps/overlaps
    assert b[0][0] == 0 and b[-1][1] == 103
    assert all(b[i][1] == b[i + 1][0] for i in range(len(b) - 1))


# ----------------------------------------------------------- exhaustive sweep

SWEEP = list(
    itertools.product(
        (4, 5, 8),  # n_groups
        (1, 2, 3),  # k_test
        (0, 8, 72),  # purge_bars
        (0, 24, 168),  # embargo_bars
        (40, 103, 250),  # n grid points (forces unequal group sizes sometimes)
    )
)


@pytest.mark.parametrize(("n_groups", "k", "purge", "embargo", "n"), SWEEP)
def test_split_invariants(n_groups: int, k: int, purge: int, embargo: int, n: int) -> None:
    """The leakage contract, exhaustively: counts, tiling, purge, embargo, shape."""
    if not 1 <= k < n_groups:
        pytest.skip("invalid configuration rejected at construction")
    cv = CombinatorialPurgedCV(n_groups, k, purge_bars=purge, embargo_bars=embargo)
    g = grid(n)
    splits = list(cv.split(g))

    assert len(splits) == cv.n_splits == comb(n_groups, k) > 0
    g_set = set(g.tolist())
    ts_to_pos = {int(t): i for i, t in enumerate(g)}

    # Coverage / path accounting: across all splits, count how many splits each
    # grid position appears in as a TEST position. Every position must appear
    # in exactly C(N-1, k-1) = n_backtest_paths splits (its group is chosen that
    # many times), which is what assembles phi complete OOS paths.
    test_count = np.zeros(n, dtype=np.int64)

    for train_ts, test_groups in splits:
        assert len(test_groups) == k
        # each test group is contiguous, ascending, a subset of the grid
        flat_test_pos: list[int] = []
        prev_end = -1
        for tg in test_groups:
            assert tg.size >= 1
            assert set(tg.tolist()) <= g_set
            assert bool(np.all(np.diff(tg) > 0))
            pos = [ts_to_pos[int(t)] for t in tg]
            # contiguous block
            assert pos == list(range(pos[0], pos[0] + len(pos)))
            # groups handed back in ascending grid order, disjoint
            assert pos[0] > prev_end
            prev_end = pos[-1]
            flat_test_pos.extend(pos)
            test_count[pos] += 1

        train_pos = np.array([ts_to_pos[int(t)] for t in train_ts], dtype=np.int64)
        test_pos = np.array(flat_test_pos, dtype=np.int64)

        # train ts are grid points, ascending, disjoint from test
        assert set(train_ts.tolist()) <= g_set
        assert bool(np.all(np.diff(train_ts) > 0)) or train_ts.size <= 1
        assert not set(train_ts.tolist()) & flat_test_set(test_groups)

        # PURGE + EMBARGO against EVERY test block.
        for tg in test_groups:
            block = np.array([ts_to_pos[int(t)] for t in tg], dtype=np.int64)
            a, b_excl = int(block[0]), int(block[-1]) + 1
            # purge: label interval [p, p+purge] must not reach into the block,
            # i.e. p + purge < a  for any train p that lies before the block.
            before = train_pos[train_pos < a]
            assert bool(np.all(before + purge < a))
            # nothing inside the block (disjoint already, but be explicit)
            assert not bool(((train_pos >= a) & (train_pos < b_excl)).any())
            # embargo: no train position in [b_excl, b_excl + embargo)
            in_embargo = (train_pos >= b_excl) & (train_pos < b_excl + embargo)
            assert not bool(in_embargo.any())

        # train never contains a purged/embargoed position w.r.t. union of blocks
        assert set(train_pos.tolist()).isdisjoint(test_pos.tolist())

    # every position appears as test in exactly C(N-1, k-1) splits
    assert bool(np.all(test_count == cv.n_backtest_paths))


def test_flat_test_set_helper() -> None:
    gs = (grid(3), grid(2) + 10 * HOUR)
    assert flat_test_set(gs) == set(np.concatenate(gs).tolist())
    assert flat_test_set(()) == set()


# ----------------------------------------------------------- purge equivalence


def test_purge_embargo_matches_purged_walk_forward() -> None:
    """One trailing test group must reproduce a forward-chaining WF leg exactly.

    With N groups, the combination that selects ONLY the LAST group as test has
    all earlier groups as train -- identical to a single PurgedWalkForward leg
    whose train window is everything before the test block. The surviving train
    timestamps (and the test block) must match position-for-position, proving
    the shared purge/embargo arithmetic is reused, not re-derived.
    """
    n = 100
    g = grid(n)
    n_groups, purge, embargo = 5, 8, 24
    cv = CombinatorialPurgedCV(n_groups, 1, purge_bars=purge, embargo_bars=embargo)
    bounds = CombinatorialPurgedCV._group_bounds(n, n_groups)
    last_lo, last_hi = bounds[-1]
    test_block_len = last_hi - last_lo

    # WF with train window = everything before the last group, single test leg.
    wf = PurgedWalkForward(last_lo, test_block_len, purge_bars=purge, embargo_bars=embargo)
    wf_splits = list(wf.split(g))
    assert len(wf_splits) == 1
    wf_train, wf_test = wf_splits[0]

    # CPCV split that tests ONLY the last group is the last combination yielded.
    cpcv_train, cpcv_test_groups = list(cv.split(g))[-1]
    assert len(cpcv_test_groups) == 1
    np.testing.assert_array_equal(cpcv_test_groups[0], wf_test)
    np.testing.assert_array_equal(cpcv_train, wf_train)


# ----------------------------------------------------------- determinism


def test_split_deterministic_and_lexicographic() -> None:
    cv = CombinatorialPurgedCV(6, 2, purge_bars=8, embargo_bars=24)
    g = grid(300)
    a = list(cv.split(g))
    b = list(cv.split(g))
    assert len(a) == len(b) == comb(6, 2)
    for (tr1, tg1), (tr2, tg2) in zip(a, b, strict=True):
        np.testing.assert_array_equal(tr1, tr2)
        assert len(tg1) == len(tg2)
        for x, y in zip(tg1, tg2, strict=True):
            np.testing.assert_array_equal(x, y)

    # combinations are emitted in lexicographic group-index order
    bounds = CombinatorialPurgedCV._group_bounds(300, 6)
    expected_first_group_starts = [bounds[c[0]][0] for c in itertools.combinations(range(6), 2)]
    g_pos = {int(t): i for i, t in enumerate(g)}
    got_first_group_starts = [g_pos[int(tg[0][0])] for _, tg in a]
    assert got_first_group_starts == expected_first_group_starts


def test_split_yields_copies() -> None:
    """Mutating a yielded array must not corrupt a fresh iteration of the same grid."""
    cv = CombinatorialPurgedCV(5, 2, purge_bars=4)
    g = grid(120)
    # snapshot the very first split before any mutation
    ref_train, ref_groups = next(iter(cv.split(g)))
    ref_train = ref_train.copy()
    ref_groups = tuple(arr.copy() for arr in ref_groups)

    # now obtain it again and scribble all over the yielded arrays
    bad_train, bad_groups = next(iter(cv.split(g)))
    bad_train[:] = 0
    for arr in bad_groups:
        arr[:] = 0

    # a fresh iteration must be untouched by the mutation above
    again_train, again_groups = next(iter(cv.split(g)))
    np.testing.assert_array_equal(again_train, ref_train)
    for got, ref in zip(again_groups, ref_groups, strict=True):
        np.testing.assert_array_equal(got, ref)
    # and the underlying grid array is not corrupted either
    np.testing.assert_array_equal(g, grid(120))


# ----------------------------------------------------------- hand-computed


def test_known_small_example_exact() -> None:
    """Hand-checkable: N=4, k=2, purge=1, embargo=1 on a 12-point grid.

    Groups (array_split, 12/4 = 3 each): G0=[0,1,2] G1=[3,4,5] G2=[6,7,8]
    G3=[9,10,11]. C(4,2)=6 splits, lexicographic test-group order:
    (0,1) (0,2) (0,3) (1,2) (1,3) (2,3).
    """
    cv = CombinatorialPurgedCV(4, 2, purge_bars=1, embargo_bars=1)
    g = grid(12)
    splits = list(cv.split(g))
    assert len(splits) == 6

    # split (0,1): test G0,G1 (pos 0..5). Train candidates = G2,G3 = 6..11.
    #   purge vs block [0,3): pos before 0 -> none. block [3,6): before=none.
    #   embargo after G1 end (pos 6) in [6, 7): drops pos 6. after G0 end(pos3)
    #   in [3,4): pos 3 is in test G1, not a candidate. So drop pos 6 only.
    train, test_groups = splits[0]
    np.testing.assert_array_equal(test_groups[0], g[[0, 1, 2]])
    np.testing.assert_array_equal(test_groups[1], g[[3, 4, 5]])
    np.testing.assert_array_equal(train, g[[7, 8, 9, 10, 11]])  # 6 embargoed out

    # split (0,3): test G0 (0..2) and G3 (9..11). Train candidates = G1,G2 = 3..8.
    #   vs block [0,3): before = none; embargo [3,4) drops pos 3.
    #   vs block [9,12): purge -> p+1 < 9 must hold for p<9 -> pos 8 fails
    #     (8+1=9 !< 9) -> drop 8. embargo [12,13): none.
    train, test_groups = splits[2]
    np.testing.assert_array_equal(test_groups[0], g[[0, 1, 2]])
    np.testing.assert_array_equal(test_groups[1], g[[9, 10, 11]])
    np.testing.assert_array_equal(train, g[[4, 5, 6, 7]])  # 3 embargoed, 8 purged

    # split (2,3): test G2,G3 (6..11). Train = G0,G1 = 0..5.
    #   vs block [6,9): purge p+1<6 -> pos5 fails(5+1=6) drop 5; embargo[9,10) none
    #   vs block [9,12): p+1<9 keeps 0..7, but candidates only up to 5 -> fine.
    train, test_groups = splits[5]
    np.testing.assert_array_equal(test_groups[0], g[[6, 7, 8]])
    np.testing.assert_array_equal(test_groups[1], g[[9, 10, 11]])
    np.testing.assert_array_equal(train, g[[0, 1, 2, 3, 4]])  # 5 purged out


def test_minimum_grid_one_per_group() -> None:
    """A grid of exactly n_groups points -> one position per group."""
    cv = CombinatorialPurgedCV(4, 1, purge_bars=0, embargo_bars=0)
    g = grid(4)
    splits = list(cv.split(g))
    assert len(splits) == 4
    for train, test_groups in splits:
        assert len(test_groups) == 1
        assert test_groups[0].size == 1
        # purge=embargo=0 -> all other 3 positions are train
        assert train.size == 3


def test_accepts_plain_sequence_input() -> None:
    cv = CombinatorialPurgedCV(4, 2, purge_bars=0, embargo_bars=0)
    ts = [T0 + k * HOUR for k in range(8)]
    splits = list(cv.split(ts))
    assert len(splits) == comb(4, 2) == 6
    train, test_groups = splits[0]
    assert train.dtype == np.int64
    assert test_groups[0].dtype == np.int64
