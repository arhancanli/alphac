"""Delayed aggressive trade-flow inputs; no order-book OFI or execution claims."""
import numpy as np
import pandas as pd
BAR=300000
BLOCK=48*BAR


def flow_blocks(frame):
    """Complete UTC4h blocks from already schema-validated5m source rows.

    Reindex the supplied span onto its full5m calendar; never compress gaps.
    Input numeric columns are quote_volume and taker_buy_quote_volume.
    """
    f=frame.copy(deep=True)
    if f.empty:raise ValueError('Nonempty grid required')
    if not pd.api.types.is_integer_dtype(f.index) or not f.index.is_unique or not f.index.is_monotonic_increasing:
        raise ValueError('Unique increasing integer timestamp grid required')
    if (f.index.to_numpy()%BAR).any():raise ValueError('Unaligned5m source')
    for name in ['quote_volume','taker_buy_quote_volume']:
        if name not in f:raise ValueError('Missing source column')
    valid=np.isfinite(f.quote_volume)&np.isfinite(f.taker_buy_quote_volume)&f.quote_volume.ge(0)&f.taker_buy_quote_volume.ge(0)&f.taker_buy_quote_volume.le(f.quote_volume)
    if not valid.all():raise ValueError('Invalid source volume')
    first=int(f.index[0])//BLOCK*BLOCK;end=(int(f.index[-1])//BLOCK+1)*BLOCK
    grid=pd.Index(np.arange(first,end,BAR,dtype=np.int64),name='open_time')
    f=f.reindex(grid);group=f.index.to_numpy()//BLOCK*BLOCK
    quote=f.quote_volume.groupby(group).sum(min_count=48)
    buy=f.taker_buy_quote_volume.groupby(group).sum(min_count=48)
    out=pd.DataFrame({'quote_volume':quote,'signed_quote_flow':2*buy-quote})
    out.index=out.index+BLOCK;out.index.name='input_end'
    return out


def delayed_flow_features(blocks):
    """Normalize by the fixed7day trailing mean and enforce a full history."""
    if blocks.empty:raise ValueError('Nonempty block grid required')
    index=blocks.index.to_numpy()
    if not pd.api.types.is_integer_dtype(blocks.index) or not blocks.index.is_unique or (index%BLOCK).any() or not (np.diff(index)==BLOCK).all():
        raise ValueError('Full ordered4hour block grid required')
    q=blocks.quote_volume;flow=blocks.signed_quote_flow
    if ((q.notna()&(~np.isfinite(q)|q.lt(0)))|(flow.notna()&(~np.isfinite(flow)|flow.abs().gt(q)))).any():
        raise ValueError('Invalid aggregated flow')
    scale=q.rolling(42,min_periods=42).mean()
    feature=flow/scale.where(scale>0)
    out=pd.DataFrame({'flow':feature,'input_end':index,'available_at':index+BAR,
                      'entry_reference':index+2*BAR,'exit_reference':index+BLOCK+2*BAR,
                      'label_available_at':index+BLOCK+3*BAR},index=blocks.index)
    return out
