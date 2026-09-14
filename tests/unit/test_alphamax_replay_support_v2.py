"""Calendar retention and durable evidence when a later leg fails."""
import numpy as np
import pytest
from alphamax_replay_support_v2 import MergeSingletonTail, persisting_engine_factory

from alphaforge.backtest.engine import EventDrivenBacktester
from alphaforge.validation.splits import PurgedWalkForward


def test_full_calendar_retained_with_original_training_and_last_session():
    # Irregular labels also cover weekend/session gaps.
    grid = np.cumsum(np.tile([1, 1, 3], 169))[:505].astype(np.int64)
    splitter = PurgedWalkForward(252, 63, purge_bars=21, embargo_bars=274, horizon_bars=21)
    original = list(splitter.split(grid))
    merged = list(MergeSingletonTail(splitter).split(grid))
    assert [len(test) for _, test in original] == [63, 63, 63, 63, 1]
    assert [len(test) for _, test in merged] == [63, 63, 63, 64]
    np.testing.assert_array_equal(np.concatenate([t for _, t in merged]), grid[252:])
    for i, (train, test) in enumerate(merged):
        np.testing.assert_array_equal(train, original[i][0])
        assert train[-1] < test[0]
    assert merged[-1][1][-1] == grid[-1]
    assert len(np.unique(np.concatenate([t for _, t in merged]))) == 253


@pytest.mark.parametrize('remaining', [63, 64, 65, 126, 128])
def test_only_singleton_tail_changes_boundaries(remaining):
    grid = np.arange(252 + remaining)
    splitter = PurgedWalkForward(252, 63, purge_bars=21, embargo_bars=274, horizon_bars=21)
    old = list(splitter.split(grid))
    new = list(MergeSingletonTail(splitter).split(grid))
    if remaining == 64:
        assert len(new) == 1 and len(new[0][1]) == 64
    else:
        for before, after in zip(old, new, strict=True):
            for a, b in zip(before, after, strict=True):
                np.testing.assert_array_equal(a, b)


def test_lone_session_rejected():
    splitter = PurgedWalkForward(252, 63, purge_bars=21, embargo_bars=274, horizon_bars=21)
    with pytest.raises(ValueError, match='no preceding leg'):
        list(MergeSingletonTail(splitter).split(np.arange(253)))


def test_completed_leg_persists_when_next_engine_fails(tmp_path, monkeypatch):
    class Result:
        def save(self, path):
            (path / 'equity.csv').write_text('timestamp,equity\n1,100\n2,99\n')

    def init(self, *args, **kwargs):
        self.leg = kwargs['config_echo']['walkforward_leg']

    def run(self, *args, **kwargs):
        if self.leg == 1:
            raise ValueError('later engine failure')
        return Result()

    monkeypatch.setattr(EventDrivenBacktester, '__init__', init)
    monkeypatch.setattr(EventDrivenBacktester, 'run', run)
    factory = persisting_engine_factory(tmp_path)
    factory(config_echo={'walkforward_leg': 0}).run()
    with pytest.raises(ValueError, match='later engine failure'):
        factory(config_echo={'walkforward_leg': 1}).run()
    assert (tmp_path / '000/equity.csv').read_text().endswith('2,99\n')
    assert (tmp_path / '000/SAVE_COMPLETE').exists()
    assert not (tmp_path / '001/SAVE_COMPLETE').exists()
    with pytest.raises(FileExistsError):
        factory(config_echo={'walkforward_leg': 0})
