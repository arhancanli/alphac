"""Build calendar-aware equity signal intervals without opening account ledgers."""
import numpy as np
from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe
from alphamax_replay_support_v2 import MergeSingletonTail
from funded_inception_runner import InceptionSplitter

def equity_schedule(splitter,grid,full_frame,full_ts,train_bars,inception=1672531200000):
    cal=XNYSCalendar();tf=Timeframe.D1;result=[];last=None
    for _,test in InceptionSplitter(MergeSingletonTail(splitter),inception=inception).split(grid):
        test=np.asarray(test,dtype=np.int64);start=int(test[0]);end=int(test[-1])+tf.ms
        expected=cal.expected_bar_opens(start,end,tf)
        if list(test)!=list(expected):raise ValueError('Non-session or missing equity test bars')
        if last is not None and start!=cal.next_bar_open(last,tf):
            raise ValueError('Gap or overlap between equity model intervals')
        warm=start-train_bars*tf.ms
        train_start=max(int(full_ts.min()),warm) if full_ts.size else warm
        result.append({'model_interval':len(result),'test_start':start,'test_end':end,'train_start':train_start,
                       'decision_start':cal.next_bar_open(start,tf),
                       'frame':full_frame.iloc[(full_ts>=train_start)&(full_ts<end)]})
        last=int(test[-1])
    if not result:raise ValueError('No funded equity test intervals')
    return result
