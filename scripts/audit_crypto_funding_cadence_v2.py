"""Compare frozen observed settlement gaps with modeled interval metadata; no signals."""
from pathlib import Path
import json,hashlib
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
SNAP=ROOT/'evidence/core-2023-2026-frozen-inputs-20260913'
OUT=ROOT/'evidence/crypto-carry-cadence-20260913-v2'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    manifest=json.loads((SNAP/'manifest.json').read_text())
    design=json.loads((ROOT/'evidence/crypto-extended-reference-20260913/EXPERIMENT_SPEC.json').read_text())
    assert sha(SNAP/'manifest.json')==design['snapshot_manifest_sha256']
    ids=set(design['scope']['instrument_ids'])
    meta_path=SNAP/'references/2_instrument_versions.json'
    meta={r['instrument_id']:r for r in json.loads(meta_path.read_text())}
    paths=[SNAP/p for p in manifest['output_sha256'] if p.startswith('lake/funding/')]
    refs={}
    for p in paths+[meta_path]:
        assert sha(p)==manifest['output_sha256'][str(p.relative_to(SNAP))]
        refs[str(p.relative_to(ROOT))]=sha(p)
    OUT.mkdir(exist_ok=False)
    protocol={'scope':'Frozen source cadence diagnostic only, no feature/forecast/return computation.',
              'comparison':'Adjacent unique settlement timestamps; observed gaps within1second of modeled interval count matching. Gaps are not independently verified settlement periods and may represent absent records.',
              'selection':'All51frozen crypto instrument identities, all retained funding rows; report2023–June1 2026 separately.',
              'stop':'Do not change original feature or metadata. If mismatch present, synthesize causal cadence-aware alternative and preserve observed-gap uncertainty before any historical trial.'}
    (OUT/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2)+'\n')
    data=pd.concat([pd.read_parquet(p) for p in paths],ignore_index=True)
    data=data[data.instrument_id.isin(ids)].sort_values(['instrument_id','ts_funding'])
    assert not data.duplicated(['instrument_id','ts_funding']).any()
    data['ts_funding']=pd.to_datetime(data.ts_funding,utc=True).astype('datetime64[ms, UTC]').astype('int64')
    data['gap_hours']=data.groupby('instrument_id').ts_funding.diff()/3600000
    data['metadata_interval']=data.instrument_id.map({i:meta[i]['funding_interval_hours'] for i in ids})
    data['mismatch']=(data.gap_hours-data.metadata_interval).abs()>1/3600
    summaries=[];distribution=[]
    for scope,frame in [('all_retained',data),('evaluation',data[data.ts_funding.between(1672531200000,1780358399999)])]:
        for iid,g in frame.groupby('instrument_id'):
            valid=g[g.gap_hours.notna()]
            summaries.append({'scope':scope,'instrument_id':iid,'metadata_interval':meta[iid]['funding_interval_hours'],
                              'observed_gaps':len(valid),'mismatching_gaps':int(valid.mismatch.sum()),
                              'shorter_than_metadata':int((valid.gap_hours < valid.metadata_interval-1/3600).sum()),
                              'longer_than_metadata':int((valid.gap_hours > valid.metadata_interval+1/3600).sum())})
            for gap,count in valid.gap_hours.round(3).value_counts().items():
                distribution.append({'scope':scope,'instrument_id':iid,'observed_gap_hours_rounded':float(gap),'count':int(count)})
    pd.DataFrame(summaries).to_csv(OUT/'summary.csv',index=False)
    pd.DataFrame(distribution).to_csv(OUT/'gap_distribution.csv',index=False)
    data[data.mismatch].to_parquet(OUT/'mismatching_source_rows.parquet',index=False)
    result={'funding_rows':len(data),'instrument_ids':data.instrument_id.nunique(),'evaluation':[
        r for r in summaries if r['scope']=='evaluation' and r['mismatching_gaps']],
        'new_signals_or_returns':False,'qualified':False}
    (OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    for p in [SNAP/'manifest.json',ROOT/'evidence/crypto-extended-reference-20260913/EXPERIMENT_SPEC.json',Path(__file__),OUT/'PROTOCOL.json',OUT/'summary.csv',OUT/'gap_distribution.csv',OUT/'mismatching_source_rows.parquet',OUT/'result.json']:
        refs[str(p.relative_to(ROOT))]=sha(p)
    (OUT/'source_bindings.json').write_text(json.dumps({'sha256':refs},indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
