"""Fund a fresh account at inception without inheriting pre-inception positions."""
import numpy as np
from alphaforge.analytics.walkforward import WalkForwardRunner
from alphamax_replay_support_v2 import MergeSingletonTail
INCEPTION=1672531200000


class InceptionSplitter:
    def __init__(self,splitter,inception=INCEPTION):
        self.splitter=splitter;self.inception=inception

    def split(self,grid):
        for train,test in self.splitter.split(grid):
            test=np.asarray(test)
            selected=test[test>=self.inception]
            if not len(selected):continue
            if len(selected)<2:raise ValueError('Inception leaves an unsupported singleton leg')
            yield train,selected


class FundedInceptionRunner(WalkForwardRunner):
    def _run_leg_set(self,splitter,*args,**kwargs):
        return super()._run_leg_set(InceptionSplitter(MergeSingletonTail(splitter)),*args,**kwargs)
