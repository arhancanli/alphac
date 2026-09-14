"""Rebuild position quantities from fills/splits and compare marks with frozen prices."""
from pathlib import Path
from collections import defaultdict
import json,hashlib
import numpy as np,pandas as pd
from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
ROOT=Path(__file__).resolve().parents[1];D=ROOT/'artifacts/analysis/earnings_change_20260913_v2/normal'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 cfg=json.loads((D/'reservation.json').read_text())['trial_config'];cal=XNYSCalendar()
 files={n:D/'run'/f'{n}.parquet' for n in ['equity','fills','positions','corporate_actions']}
 eq,fills,pos,actions=[pd.read_parquet(files[n]) for n in files]
 raw=PITDataReader(LakePaths(ROOT/'evidence/core-2023-2026-frozen-inputs-20260913/lake')).ohlcv(cfg['instrument_ids'],start=cfg['start'],end=cfg['end'],as_of=cfg['end'],tf=Timeframe.D1).to_pandas()
 raw['source_ms']=raw.ts_open.astype('datetime64[ms, UTC]').astype('int64')
 prices={(r.instrument_id,int(r.source_ms)):(float(r.open),float(r.close)) for r in raw.itertuples()}
 fg={int(t):g for t,g in fills[fills.reason.ne('forced_flat')].groupby('ts')};forced={int(t):g for t,g in fills[fills.reason.eq('forced_flat')].groupby('ts')}
 ag={int(t):g for t,g in actions.groupby('action_ts')};pg={int(t):g for t,g in pos.groupby('ts')}
 q=defaultdict(float);lastmark={};maxerr=0.;markerr=0.;checked=0;slippage_errors=[]
 for mark in eq.ts:
  source=cal.floor_bar(int(mark)-1,Timeframe.D1)
  if source in ag:
   for a in ag[source].itertuples():
    assert abs(q[a.instrument_id]-a.position_qty_before)<1e-8
    if a.action_type=='split':q[a.instrument_id]*=a.ratio
  if source in fg:
   for f in fg[source].itertuples():
    op=prices[(f.instrument_id,source)][0]
    if (f.side=='buy' and f.price<op-1e-10) or (f.side=='sell' and f.price>op+1e-10):slippage_errors.append(f.client_order_id)
    assert abs(f.notional-f.qty*f.price)<1e-7
    q[f.instrument_id]+=f.qty*(1 if f.side=='buy' else -1)
  for iid in q:
   if (iid,source) in prices:lastmark[iid]=prices[(iid,source)][1]
  if int(mark) in forced:
   for f in forced[int(mark)].itertuples():
    assert abs(f.price-lastmark[f.instrument_id])<1e-8
    q[f.instrument_id]+=f.qty*(1 if f.side=='buy' else -1)
  actual={} if int(mark) not in pg else {r.instrument_id:r for r in pg[int(mark)].itertuples()}
  for iid in set(q)|set(actual):
   row=actual.get(iid);maxerr=max(maxerr,abs(q[iid]-(0 if row is None else row.qty)))
   if row is not None:
    markerr=max(markerr,abs(row.mark-lastmark[iid]));checked+=1
 assert maxerr<1e-8,maxerr;assert markerr<1e-8,markerr;assert not slippage_errors
 manifest=json.loads((D.parent/'input_manifest.json').read_text())
 for path,digest in manifest['sha256'].items():assert sha(Path(path))==digest,path
 report={'pass':True,'quantity_max_error':maxerr,'mark_max_error':markerr,'position_rows':checked,'marks':len(eq),'fills':len(fills),'actions':len(actions),'slippage_direction_errors':slippage_errors,'frozen_bindings_verified':len(manifest['sha256']),'scope':'All saved positions rebuilt from signed fills and held splits; marks from frozen raw closes. Market fills checked against adverse raw-open direction and notional; exact impact/commission recomputation and real terminal proceeds not certified.','bindings':[{'path':str(p),'sha256':sha(p)} for p in [Path(__file__),*files.values()]]}
 (D/'quantity_audit.json').write_text(json.dumps(report,indent=2)+'\n');print({k:v for k,v in report.items() if k!='bindings'})
if __name__=='__main__':main()
