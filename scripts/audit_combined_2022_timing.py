"""Verify retained mark-to-source session mapping without new portfolio returns."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/combined-2022-timing-20260913'
BASE = ROOT / 'artifacts/analysis/alphatrend_positive_targets_20260913'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    OUT.mkdir(exist_ok=False)
    cal = XNYSCalendar()
    source_sessions = cal.expected_bar_opens(1640908800000, 1672531200000, Timeframe.D1)
    marks = [cal.next_bar_open(t, Timeframe.D1) for t in source_sessions]
    inverse = dict(zip(marks, source_sessions, strict=True))
    mapping = pd.DataFrame({'source_session':source_sessions, 'engine_mark':marks})
    mapping.to_csv(OUT / 'session_mapping.csv',index=False)
    results=[]; refs={}
    for arm in ['baseline','baseline_stress','candidate','candidate_stress']:
        directory=BASE/arm
        curve=pd.read_parquet(directory/'run/equity.parquet')
        np.testing.assert_array_equal(curve[curve.ts.isin(marks)].ts.to_numpy(), marks)
        pos=pd.read_parquet(directory/'run/positions.parquet')
        pos=pos[pos.ts.isin(marks)].copy()
        pos['source_session']=pos.ts.map(inverse)
        price_rows=[]
        for iid in sorted(pos.instrument_id.unique()):
            for year in [2021,2022]:
                p=directory/'inputs/execution/ohlcv_1d'/f'instrument_id={iid}'/f'year={year}'/'data.parquet'
                f=pd.read_parquet(p,columns=['ts_open','close'])
                f['source_session']=pd.to_datetime(f.ts_open,utc=True).astype('datetime64[ms, UTC]').astype('int64')
                f['instrument_id']=iid
                price_rows.append(f[['source_session','instrument_id','close']])
                refs[str(p.relative_to(ROOT))]=sha(p)
        prices=pd.concat(price_rows)
        assert not prices.duplicated(['source_session','instrument_id']).any()
        merged=pos.merge(prices,on=['source_session','instrument_id'],how='left',validate='many_to_one')
        assert merged.close.notna().all()
        residual=float((merged.mark-merged.close).abs().max())
        assert residual < 1e-10, (arm,residual)
        for p in [directory/'run/equity.parquet',directory/'run/positions.parquet']:
            refs[str(p.relative_to(ROOT))]=sha(p)
        results.append({'arm':arm,'mapped_equity_observations':len(marks),'position_marks_checked':len(merged),'maximum_source_close_error':residual})
    code=[ROOT/'src/alphaforge/backtest/payable_engine.py',ROOT/'scripts/run_combined_positive_targets_v2.py',ROOT/'evidence/alphac-algorithm-contributions-20260913/source-market_factor.py',Path('/Users/arhancanli/alphaforge/scripts/probe_cpi_surprise_size.py'),Path('/Users/arhancanli/alphaforge/src/alphaforge/analytics/curve_store.py')]
    for p in code: refs[str(p)]=sha(p)
    result={'status':'TREND_SOURCE_SESSION_MAPPING_VERIFIED','arms':results,
            'source_session_observations':len(marks),
            'calendar_gap_days':[int(x) for x in sorted(set((np.array(marks)-np.array(source_sessions))//86400000))],
            'earlier_combined_comparison':'Trend returns reindexed directly on engine labels while overlay uses source-day labels; economic-day synchronization not established by prior numeric replay parity.',
            'boundary':'Do not treat prior best combined1.1065 excess Sharpe as synchronized portfolio evidence. Retain it as legacy development proxy pending registered corrected comparison.',
            'new_strategy_or_combined_returns':False,'sha256':refs}
    (OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    (OUT/'REPORT.md').write_text('# Combined timing: material label mismatch verified\n\n'
        'All four Trend arms map252 equity observations (Dec31 2021 predecessor plus251 2022 sessions) to next-XNYS-open labels. Saved position marks match the previous source session close exactly. Calendar label shifts span1–4 days.\n\n'
        'The prior combined runner reindexed Trend returns directly by these engine labels. The legacy BTC/SPY overlay uses source-day close labels, and the CPI probe writer preserves its source-day return index. Matching UTC types and replaying previous arithmetic do not establish simultaneous economic observations. The earlier1.1065 combined excess Sharpe remains a retained legacy proxy; synchronized diversification and its reported improvement are unverified. No corrected combined performance has been computed here.\n\n'
        'Next freeze a corrected economic-day comparison with explicit model boundaries for crypto23UTC marks, equity closes and overnight accrual. Preserve the original label-based control. Vintage remains killed; retirement to reserved cash must be a separately disclosed portfolio choice, with financing conventions fixed before returns. Overlay prices alone do not certify fundable net returns.\n')
    print(json.dumps({k:v for k,v in result.items() if k!='sha256'}))


if __name__ == '__main__':
    main()
