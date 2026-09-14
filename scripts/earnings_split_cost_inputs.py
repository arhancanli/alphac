"""Isolated split-corrected cost volatility; ADV and execution prices unchanged."""
import math
import numpy as np
import pandas as pd
import pyarrow as pa
from alphaforge.backtest.engine import LakeCostInputs
from alphaforge.core.time import Timeframe
from alphaforge.features.library.vol import log_returns,ewma_vol_halflife


def corrected_returns(closes, split_events):
    result=log_returns(closes)
    seen=set()
    for iid,ex,ratio in split_events:
        if iid not in closes.columns or ex not in closes.index:continue
        if not math.isfinite(ratio) or ratio<=0:raise ValueError('Invalid split ratio')
        if (iid,ex) in seen:raise ValueError('Duplicate split')
        seen.add((iid,ex))
        result.loc[ex,iid]+=math.log(ratio)
    return result


class EarningsSplitCostInputs(LakeCostInputs):
    def __init__(self, reader, instrument_ids, *, start,end,calendar,split_events):
        super().__init__(reader,instrument_ids,start=start,end=end,anchor_tf=Timeframe.D1,calendar=calendar)
        grid=self._sigma.index
        if len(grid)==0:return
        table=reader.ohlcv(instrument_ids,start=int(grid.min()),end=end,as_of=end,tf=Timeframe.D1)
        frame=pd.DataFrame({'instrument_id':table.column('instrument_id').to_pylist(),'ts_open':table.column('ts_open').cast(pa.int64()).to_pylist(),'close':table.column('close').to_pylist()})
        if frame.empty:return
        closes=frame.pivot(index='ts_open',columns='instrument_id',values='close').reindex(index=grid,columns=self._sigma.columns).astype(float)
        self._sigma=ewma_vol_halflife(corrected_returns(closes,split_events),self.SIGMA_HALFLIFE_BARS)
