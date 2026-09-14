"""Freeze later evaluation scope and audit timestamps; no signals or returns."""
import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe

ROOT=Path(__file__).resolve().parents[1]
PROD=Path('/Users/arhancanli/alphaforge')
OUT=ROOT/'evidence/core-2023-2026-coverage-20260913'
DAY=86400000
HOUR=3600000


def ms(t):return int(pd.Timestamp(t,tz='UTC').timestamp()*1000)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):
    with p.open('x') as f:json.dump(x,f,indent=2,sort_keys=True);f.write('\n')


def main():
    OUT.mkdir(exist_ok=False)
    end=ms('2026-06-02');cal=XNYSCalendar()
    all_sessions=cal.expected_bar_opens(ms('2010-01-01'),end,Timeframe.D1)
    first_test=ms('2022-12-29');train=all_sessions[all_sessions.index(first_test)-252]
    context=all_sessions[all_sessions.index(train)-2520+1]
    crypto_test=ms('2022-12-31');crypto_train=crypto_test-6048*HOUR;crypto_context=crypto_train-2520*HOUR
    protocol={'status':'HORIZON_FIXED_BEFORE_NEW_STRATEGY_RESULTS','evaluation_start':'2023-01-01','evaluation_end_inclusive':'2026-06-01','equity_first_test_ms':first_test,'equity_train_start_ms':train,'equity_shared_context_start_ms':context,'crypto_first_test_ms':crypto_test,'crypto_train_start_ms':crypto_train,'crypto_shared_context_start_ms':crypto_context,'end_exclusive_ms':end,'capital_rule':{'max':.225,'crypto':.225,'confirmed_trend':.225,'idle_cash_zero_yield':.325},'legacy_control':'retainVintage/overlaycontrol as retrospective comparator','rule_changes':'none; no span/window/weight/horizon tuning','validation':'Report wholehorizon,2023,2024,2025,partial2026 withfixedboundaries; notuntouchedvalidation','timing':'fresh window-specific strategy start; different training and walkforward phase from2022, so not a continuation of that cash/riskstate','admission':False}
    write(OUT/'PROTOCOL.json',protocol)
    membership_path=ROOT/'evidence/historical-extension-inputs-20260913/membership_rows.parquet'
    membership=pd.read_parquet(membership_path)
    fields=('instrument_id asset_class market_type base quote tick_size lot_size min_qty min_notional contract_multiplier can_short maker_fee_bps taker_fee_bps funding_interval_hours listed_ts delisted_ts valid_from_ms valid_to_ms').split()
    with sqlite3.connect(f"file:{PROD/'var/ops.sqlite'}?mode=ro",uri=True) as db:
        db.row_factory=sqlite3.Row
        ids=sorted(membership.instrument_id.unique())
        versions=[dict(row) for row in db.execute(f"SELECT {','.join(fields)} FROM instruments_v WHERE instrument_id IN ({','.join('?' for _ in ids)}) ORDER BY instrument_id,valid_from_ms",ids)]
    write(OUT/'instrument_versions.json',versions)
    latest={x['instrument_id']:x for x in versions}
    build=PROD/'artifacts/audit/sharadar_corporate_action_corrected_lake.json'
    equity_lake=PROD/json.loads(build.read_text())['corrected_lake']
    repaired=ROOT/'artifacts/analysis/crypto_full2022_terminal_20260913/state/repaired_snapshot'
    refs={str(p):sha(p) for p in [membership_path,build,Path(__file__)]}
    rows=[];gaps=[];selected=[]
    for sleeve,start,ctx,step,table in [('k30_dn_63',train,context,DAY,'ohlcv_1d'),('crypto_carry_wk',crypto_train,crypto_context,HOUR,'ohlcv')]:
        members=membership[(membership.sleeve==sleeve)&(membership.effective_from<pd.Timestamp(end,unit='ms',tz='UTC'))&(membership.effective_to.isna()|(membership.effective_to>pd.Timestamp(start,unit='ms',tz='UTC')))]
        selected.append(members)
        grid=np.array(cal.expected_bar_opens(ctx,end,Timeframe.D1) if step==DAY else np.arange(ctx,end,HOUR),dtype=np.int64)
        for iid,intervals in members.groupby('instrument_id'):
            meta=latest.get(iid)
            if meta is None:
                rows.append({'sleeve':sleeve,'instrument_id':iid,'missing_metadata':True});continue
            active=np.zeros(len(grid),dtype=bool)
            for row in intervals.itertuples():
                low=int(row.effective_from.timestamp()*1000);high=int(row.effective_to.timestamp()*1000) if pd.notna(row.effective_to) else end
                active|=(grid>=max(start,low))&(grid<high)
            listed=(grid>=meta['listed_ts'])&(grid<(meta['delisted_ts'] or end))
            active_expected=grid[active&listed];context_expected=grid[listed]
            observed=[];funding=[]
            for year in range(pd.Timestamp(ctx,unit='ms').year,2027):
                lake=equity_lake if step==DAY else (repaired if year<=2022 else PROD/'data/lake')
                p=lake/table/f'instrument_id={iid}'/f'year={year}'/'data.parquet'
                if p.exists():
                    refs[str(p)]=sha(p)
                    t=pd.read_parquet(p,columns=['ts_open']).ts_open
                    observed.extend(pd.to_datetime(t,utc=True).astype('datetime64[ms, UTC]').astype('int64').tolist())
                if step==HOUR:
                    p=lake/'funding'/f'instrument_id={iid}'/f'year={year}'/'data.parquet'
                    if p.exists():
                        refs[str(p)]=sha(p)
                        f=pd.read_parquet(p,columns=['ts_funding','available_at'])
                        funding.append(f)
            obs=np.array(observed,dtype=np.int64);obs=obs[(obs>=ctx)&(obs<end)]
            unique=np.unique(obs);missing=np.setdiff1d(active_expected,unique);context_missing=np.setdiff1d(context_expected,unique)
            for label,items in [('active',missing),('context',context_missing)]:
                if len(items):gaps.append({'sleeve':sleeve,'instrument_id':iid,'scope':label,'count':len(items),'first_ms':int(items[0]),'last_ms':int(items[-1]),'interior_count':int(((items>unique.min())&(items<unique.max())).sum()) if len(unique) else 0})
            row={'sleeve':sleeve,'instrument_id':iid,'active_expected':len(active_expected),'active_missing':len(missing),'context_expected':len(context_expected),'context_missing':len(context_missing),'duplicates':len(obs)-len(unique),'first_observed_ms':int(unique[0]) if len(unique) else None,'last_observed_ms':int(unique[-1]) if len(unique) else None,'metadata_valid_from_ms':meta['valid_from_ms'],'modeled_listing_end_ms':meta['delisted_ts']}
            if step==HOUR:
                fund=pd.concat(funding) if funding else pd.DataFrame(columns=['ts_funding','available_at'])
                ts=pd.to_datetime(fund.ts_funding,utc=True).astype('datetime64[ms, UTC]').astype('int64')
                use=(ts>=start)&(ts<end);ft=ts[use].sort_values().to_numpy()
                row['funding_rows']=len(ft);row['funding_duplicates']=len(ft)-len(np.unique(ft));row['funding_max_gap_hours']=float(np.diff(ft).max()/HOUR) if len(ft)>1 else None
                row['funding_schedule_verified']=False
            rows.append(row)
    pd.concat(selected).to_parquet(OUT/'active_intervals.parquet',index=False)
    pd.DataFrame(rows).to_csv(OUT/'coverage.csv',index=False)
    write(OUT/'gaps.json',gaps)
    summary={}
    for sleeve in ['k30_dn_63','crypto_carry_wk']:
        r=[x for x in rows if x['sleeve']==sleeve]
        summary[sleeve]={'instruments':len(r),'missing_metadata':sum(x.get('missing_metadata',False) for x in r),'active_expected':sum(x.get('active_expected',0) for x in r),'active_missing':sum(x.get('active_missing',0) for x in r),'context_missing':sum(x.get('context_missing',0) for x in r),'duplicates':sum(x.get('duplicates',0) for x in r)}
    write(OUT/'result.json',{'status':'TIMESTAMP_INVENTORY_COMPLETE_NOT_REPLAY_CLEARANCE','summary':summary,'qualification':False,'limitations':'Membership and latest listing metadata modeled, not PIT certification. Delisted bounds clip expected observations but do not prove correct final settlement. Funding rows inventoried, schedule not verified. Corporate-action/terminal lifecycle audit still required.'})
    write(OUT/'source_manifest.json',{'sha256':refs})
    print(json.dumps(summary))


if __name__=='__main__':main()
