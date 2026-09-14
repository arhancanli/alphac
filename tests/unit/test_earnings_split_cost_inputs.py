import numpy as np
import pandas as pd
import pytest
from earnings_split_cost_inputs import corrected_returns
from alphaforge.features.library.vol import log_returns


def test_split_move_removed_economic_move_preserved_and_input_unchanged():
 raw=pd.DataFrame({'A':[100.,102.,51.51,52.],'B':[20.,21.,22.,23.]},index=[1,2,3,4]);original=raw.copy()
 got=corrected_returns(raw,[('A',3,2.)]);expected=log_returns(raw)
 assert got.loc[3,'A']==pytest.approx(np.log(1.01))
 pd.testing.assert_series_equal(got['B'],expected['B'])
 pd.testing.assert_frame_equal(raw,original)
 assert got.loc[2,'A']==expected.loc[2,'A']


def test_future_split_and_truncation_invariance():
 raw=pd.DataFrame({'A':[100.,102.,51.51,52.]},index=[1,2,3,4])
 pd.testing.assert_frame_equal(corrected_returns(raw,[('A',3,2.)]).iloc[:2],corrected_returns(raw.iloc[:2],[('A',3,2.)]))
 pd.testing.assert_frame_equal(corrected_returns(raw,[('A',8,4.)]),log_returns(raw))
 with pytest.raises(ValueError):corrected_returns(raw,[('A',3,2.),('A',3,2.)])
 with pytest.raises(ValueError):corrected_returns(raw,[('A',3,0.)])

def test_provider_corrects_sigma_preserves_adv_and_prior_values(tmp_path):
 from test_backtest_engine import bar_row,ohlcv_table
 from alphaforge.data.store.lake import LakePaths
 from alphaforge.data.store.writer import LakeWriter
 from alphaforge.data.store.reader import PITDataReader
 from alphaforge.data.schemas import Dataset
 from alphaforge.core.calendar import calendar_for
 from alphaforge.core.types import AssetClass
 from alphaforge.core.time import Timeframe
 from alphaforge.backtest.engine import LakeCostInputs
 from earnings_split_cost_inputs import EarningsSplitCostInputs
 cal=calendar_for(AssetClass.EQUITY)
 start=int(pd.Timestamp('2022-01-03',tz='UTC').timestamp()*1000);end=int(pd.Timestamp('2023-06-01',tz='UTC').timestamp()*1000)
 grid=cal.expected_bar_opens(start,end,Timeframe.D1);iid='XUSE:CASH:TESTUSD';ex=grid[300]
 rows=[]
 for n,t in enumerate(grid):
  price=(100+np.sin(n)) /(4 if t>=ex else 1)
  rows.append(bar_row(iid,t,open_=price,close=price,quote_volume=1e8))
 paths=LakePaths(tmp_path/'lake');LakeWriter(paths).write(Dataset.OHLCV_1D,ohlcv_table(rows));reader=PITDataReader(paths)
 original=LakeCostInputs(reader,[iid],start=start,end=end,anchor_tf=Timeframe.D1,calendar=cal)
 fixed=EarningsSplitCostInputs(reader,[iid],start=start,end=end,calendar=cal,split_events=[(iid,ex,4.)])
 pd.testing.assert_frame_equal(original._adv,fixed._adv)
 pd.testing.assert_frame_equal(original._sigma.loc[:grid[299]],fixed._sigma.loc[:grid[299]])
 assert original._sigma.loc[ex,iid]>fixed._sigma.loc[ex,iid]*10
