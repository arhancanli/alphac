"""Saved-position cadence exposure attribution; no new forecasts or returns."""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
SNAP=ROOT/'evidence/core-2023-2026-frozen-inputs-20260913'
OUT=ROOT/'evidence/crypto-cadence-exposure-20260913'
IDS=['BINANCE:PERP:'+s+'USDT' for s in ['AXS','BLZ','REEF']]

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    OUT.mkdir(exist_ok=False);refs={}
    manifest=json.loads((SNAP/'manifest.json').read_text())
    meta=json.loads((SNAP/'references/2_instrument_versions.json').read_text())
    intervals={r['instrument_id']:r['funding_interval_hours'] for r in meta}
    source=[]
    for rel,h in manifest['output_sha256'].items():
        if rel.startswith('lake/funding/') and any('instrument_id='+iid+'/' in rel for iid in IDS):
            p=SNAP/rel;assert sha(p)==h;refs[str(p.relative_to(ROOT))]=h;source.append(pd.read_parquet(p))
    funding=pd.concat(source).sort_values(['instrument_id','ts_funding'])
    funding['ts_funding']=pd.to_datetime(funding.ts_funding,utc=True).astype('datetime64[ms, UTC]').astype('int64')
    funding['available_at']=pd.to_datetime(funding.available_at,utc=True).astype('datetime64[ms, UTC]').astype('int64')
    states={}
    for iid,f in funding.groupby('instrument_id'):
        f=f.copy();g=f.ts_funding.diff()/3600000
        bad=(g-intervals[iid]).abs()>1/3600
        bad.iloc[0]=False
        f['window_has_mismatch']=bad.rolling(21,min_periods=21).max()
        states[iid]=f[['available_at','window_has_mismatch']].sort_values('available_at')
    rows=[];holdings=[]
    for family,arms in [('crypto_extended_reference_20260913',['baseline','baseline_stress']),('crypto_observed_carry_20260913',['candidate','candidate_stress'])]:
        for arm in arms:
            d=ROOT/'artifacts/analysis'/family/arm
            accounting=json.loads((d/'independent_audit.json').read_text());boundary=json.loads((d/'boundary_audit.json').read_text())
            bindings={**accounting['source_sha256'],**boundary['sha256']}
            for name,h in bindings.items():assert sha(ROOT/name)==h,name
            eqp=d/'run/equity.parquet';eq=pd.read_parquet(eqp);assert eq.ts.is_unique
            pospaths=sorted((d/'run/legs').glob('*/positions.parquet'));fillpaths=sorted((d/'run/legs').glob('*/fills.parquet'))
            pos=pd.concat([pd.read_parquet(p) for p in pospaths]);fills=pd.concat([pd.read_parquet(p) for p in fillpaths])
            assert not pos.duplicated(['ts','instrument_id']).any()
            gross=pos.weight.abs().sum()
            for iid in IDS:
                held=pos[(pos.instrument_id==iid)&(pos.qty.abs()>1e-10)].sort_values('ts')
                joined=pd.merge_asof(held,states[iid],left_on='ts',right_on='available_at',direction='backward',allow_exact_matches=True)
                overlap=joined.window_has_mismatch.eq(1)
                selected=fills[fills.instrument_id==iid]
                rows.append({'family':family,'arm':arm,'instrument_id':iid,'total_marks':len(eq),'held_marks':len(held),
                             'held_mark_fraction':len(held)/len(eq),'average_absolute_nav_weight':float(held.weight.abs().sum()/len(eq)),
                             'share_of_all_gross_weight_marks':float(held.weight.abs().sum()/gross),
                             'held_marks_with_known_21gap_mismatch':int(overlap.sum()),
                             'held_marks_cadence_unknown':int(joined.window_has_mismatch.isna().sum()),
                             'average_abs_nav_weight_with_mismatch':float(joined.loc[overlap,'weight'].abs().sum()/len(eq)),
                             'fills':len(selected),'fees_quote':float(selected.fee.sum())})
                joined['arm']=arm;holdings.append(joined)
            for p in [eqp,*pospaths,*fillpaths,d/'independent_audit.json',d/'boundary_audit.json']:
                refs[str(p.relative_to(ROOT))]=sha(p)
    pd.DataFrame(rows).to_csv(OUT/'summary.csv',index=False)
    pd.concat(holdings).to_parquet(OUT/'matched_holdings.parquet',index=False)
    for p in [Path(__file__),SNAP/'manifest.json',SNAP/'references/2_instrument_versions.json',OUT/'summary.csv',OUT/'matched_holdings.parquet']:
        refs[str(p.relative_to(ROOT))]=sha(p)
    (OUT/'source_bindings.json').write_text(json.dumps({'sha256':refs},indent=2)+'\n')
    print(pd.DataFrame(rows).to_string(index=False))

if __name__=='__main__':main()
