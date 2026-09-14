import numpy as np
import pandas as pd
import pytest
from crypto_trade_flow import BAR,BLOCK,flow_blocks,delayed_flow_features


def bars(blocks=44):
    return pd.DataFrame({'quote_volume':np.full(48*blocks,100.),'taker_buy_quote_volume':np.full(48*blocks,75.)},index=np.arange(48*blocks,dtype=np.int64)*BAR)


def test_economic_identity_and_delayed_execution():
    a=delayed_flow_features(flow_blocks(bars()))
    assert a.flow.iloc[:41].isna().all()
    assert (a.flow.iloc[41:]==.5).all()
    assert (a.available_at==a.input_end+BAR).all()
    assert (a.entry_reference>a.available_at).all()
    assert (a.exit_reference-a.entry_reference==BLOCK).all()
    assert (a.label_available_at==a.exit_reference+BAR).all()


def test_prefix_and_future_volume_do_not_change_previous_inputs():
    f=bars();base=delayed_flow_features(flow_blocks(f))
    prefix=delayed_flow_features(flow_blocks(f.iloc[:42*48]))
    pd.testing.assert_frame_equal(base.iloc[:42],prefix)
    f.iloc[42*48:,f.columns.get_loc('taker_buy_quote_volume')]=0
    pd.testing.assert_frame_equal(base.iloc[:42],delayed_flow_features(flow_blocks(f)).iloc[:42])


def test_missing_bar_remains_missing_block_and_full_window():
    f=bars().drop(index=BAR)
    a=delayed_flow_features(flow_blocks(f))
    assert len(a)==44 and a.flow.iloc[:42].isna().all()
    assert a.flow.iloc[42]==.5


def test_no_price_direction_inference_and_zero_volume():
    f=bars();f['taker_buy_quote_volume']=50.
    assert delayed_flow_features(flow_blocks(f)).flow.iloc[-1]==0
    f[['quote_volume','taker_buy_quote_volume']]=0.
    assert delayed_flow_features(flow_blocks(f)).flow.isna().all()


@pytest.mark.parametrize('kind',['duplicate','order','negative','too_large','nan'])
def test_invalid_source_rejected(kind):
    f=bars()
    if kind=='duplicate':f=pd.concat([f,f.iloc[-1:]])
    elif kind=='order':f=f.iloc[::-1]
    elif kind=='negative':f.iloc[0,1]=-1
    elif kind=='too_large':f.iloc[0,1]=101
    else:f.iloc[0,1]=np.nan
    with pytest.raises(ValueError):flow_blocks(f)


def test_input_immutable_and_partial_last_block_not_used():
    f=bars().iloc[:-1];before=f.copy(deep=True)
    a=delayed_flow_features(flow_blocks(f))
    assert np.isnan(a.flow.iloc[-1])
    pd.testing.assert_frame_equal(f,before)
