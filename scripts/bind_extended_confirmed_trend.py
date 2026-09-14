"""Bind established confirmedTrend inputs and check timestamps; no signal computation."""
import hashlib
import json
from pathlib import Path
import pandas as pd
from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/core-2023-2026-confirmed-trend-binding-20260913'
SOURCE=ROOT/'evidence/alphatrend-retrospective-execution-20260912'
SAVED=ROOT/'artifacts/analysis/alphatrend_retrospective_comparison_20260912/baseline'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    OUT.mkdir(exist_ok=False)
    refs={}
    seal=json.loads((SOURCE/'closure.json').read_text())
    for path,digest in seal['files'].items():
        assert sha(ROOT/path)==digest,path
        refs[path]=digest
    baseline=ROOT/'artifacts/analysis/alphatrend_positive_targets_20260913/baseline/reservation.json'
    config=json.loads(baseline.read_text())['trial_config']
    assert config['direction_confirmation'] and not config['positive_targets']
    assert config['trend_blend_normalization']=='cross_sectional_zscore'
    schedule=json.loads((SOURCE/'schedule.json').read_text())
    frame=pd.read_parquet(SOURCE/'paired_prices.parquet',columns=['symbol','session_ms'])
    signals=pd.read_parquet(SAVED/'signals.parquet',columns=[]).index
    protocol_path=ROOT/'evidence/core-2023-2026-coverage-20260913/PROTOCOL.json'
    protocol=json.loads(protocol_path.read_text());start=protocol['equity_first_test_ms'];end=protocol['end_exclusive_ms']
    cal=XNYSCalendar();grid=set(cal.expected_bar_opens(start,end,Timeframe.D1))
    rows=[]
    for iid,symbol in schedule['instrument_symbols'].items():
        p=frame[frame.symbol.eq(symbol)].session_ms
        s=signals[signals.get_level_values('instrument_id')==iid].get_level_values('ts_open')
        missing_price=sorted(grid-set(p));missing_signal=sorted(grid-set(s))
        rows.append({'instrument_id':iid,'expected_sessions':len(grid),'missing_price_sessions':len(missing_price),'missing_signal_rows':len(missing_signal),'duplicate_price_sessions':int(p.duplicated().sum()),'duplicate_signal_rows':int(s.duplicated().sum())})
        assert not missing_price and not missing_signal
    pd.DataFrame(rows).to_csv(OUT/'coverage.csv',index=False)
    files=[Path(__file__),SOURCE/'closure.json',SOURCE/'paired_prices.parquet',SOURCE/'schedule.json',SAVED/'signals.parquet',SAVED/'reservation.json',baseline,protocol_path,ROOT/'artifacts/analysis/alphatrend_directional_20260912_attempt2/state/ops.sqlite',ROOT/'scripts/run_trend_positive_targets.py']
    files+=sorted((ROOT/'src/alphaforge').rglob('*.py'))
    for p in files:refs[str(p.relative_to(ROOT))]=sha(p)
    result={'status':'CONFIRMED_TREND_INPUTS_BOUND_NO_NEW_RETURNS','instrument_count':len(rows),'expected_sessions_per_instrument':len(grid),'missing_price_sessions':sum(x['missing_price_sessions'] for x in rows),'missing_signal_rows':sum(x['missing_signal_rows'] for x in rows),'policy':'Fresh portfolio cash/risk state from Dec29 2022 through June2 2026 exclusive; reuse exact established causal forecasts anchored Jan3 2012. Continuous portfolio, 10-session rebalance; original confirmation, normalization, payable dividends, raw execution and cost settings. No positive-only candidate.','signal_reuse_boundary':'Retained retrospective forecasts are not new untouched observations. Saved history has been inspected. Signal rows checked for presence only, not finite-value or correctness certification.','qualification':False,'reservation':'Future replay identity must bind this manifest, resolved settings and runner before consuming forecasts to compute returns.'}
    (OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    (OUT/'source_manifest.json').write_text(json.dumps({'sha256':refs},indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
