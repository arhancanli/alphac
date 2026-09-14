"""Explicit research-only tail policy and durable walk-forward leg outputs."""
from pathlib import Path

import numpy as np

from alphaforge.analytics.walkforward import WalkForwardRunner
from alphaforge.backtest.engine import EventDrivenBacktester


class MergeSingletonTail:
    """Keep every test observation; extend the preceding leg for a one-bar tail.

    The preceding training window stays fixed. A sole one-bar test cannot be
    repaired by this policy and is rejected. All other boundaries stay intact.
    """

    def __init__(self, splitter):
        self.splitter = splitter

    def split(self, grid):
        legs = list(self.splitter.split(grid))
        if legs and len(legs[-1][1]) == 1:
            if len(legs) < 2:
                raise ValueError('singleton test has no preceding leg to extend')
            train, test = legs[-2]
            legs[-2:] = [(train, np.concatenate((test, legs[-1][1])))]
        yield from legs


class TailSafeWalkForwardRunner(WalkForwardRunner):
    def _run_leg_set(self, splitter, *args, **kwargs):
        return super()._run_leg_set(MergeSingletonTail(splitter), *args, **kwargs)


def persisting_engine_factory(directory: Path):
    """Save each completed engine result before control returns to the runner.

    Existing directories are rejected to avoid overwriting earlier evidence.
    Failure leaves any partial save available for inspection and propagates.
    """
    directory = Path(directory)

    class PersistingEquityBacktester(EventDrivenBacktester):
        def __init__(self, *args, **kwargs):
            leg = kwargs['config_echo']['walkforward_leg']
            self._durable_path = directory / f'{leg:03d}'
            self._durable_path.mkdir(parents=True, exist_ok=False)
            super().__init__(*args, **kwargs)

        def run(self, *args, **kwargs):
            result = super().run(*args, **kwargs)
            result.save(self._durable_path)
            (self._durable_path / 'SAVE_COMPLETE').write_text('engine result saved\n')
            return result

    return PersistingEquityBacktester
