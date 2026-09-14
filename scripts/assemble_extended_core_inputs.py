"""Copy and seal broader core research inputs; no strategy execution."""
import hashlib
import json
import shutil
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT=Path(__file__).resolve().parents[1]
PROD=Path('/Users/arhancanli/alphaforge')
OUT=ROOT/'evidence/core-2023-2026-frozen-inputs-20260913'
COVER=ROOT/'evidence/core-2023-2026-coverage-20260913'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    OUT.mkdir(exist_ok=False)
    sources={};outputs={};counts={}
    def copy(source,relative,expected=None):
        digest=sha(source)
        if expected is not None:assert digest==expected,source
        dest=OUT/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():assert sha(dest)==digest
        else:shutil.copyfile(source,dest)
        assert sha(dest)==digest and sha(source)==digest
        sources[str(source)]=digest;outputs[str(relative)]=digest
    manifest=json.loads((COVER/'source_manifest.json').read_text())['sha256']
    overlay_root=ROOT/'evidence/core-2023-2026-gap-overlay-20260913'
    repairs=json.loads((overlay_root/'result.json').read_text())['repairs']
    overrides={x['source_path']:x for x in repairs}
    for path,digest in manifest.items():
        source=Path(path)
        table=next((t for t in ['ohlcv_1d','ohlcv','funding'] if f'/{t}/' in path),None)
        if not table:continue
        relative=Path('lake')/table/path.split(f'/{table}/',1)[1]
        if path in overrides:
            x=overrides[path];assert sha(source)==digest==x['source_sha256']
            sources[path]=digest;source=ROOT/x['output_path'];digest=x['output_sha256']
        copy(source,relative,digest);counts[table]=counts.get(table,0)+1
    members=pd.read_parquet(COVER/'active_intervals.parquet')
    # Preserve complete source membership partitions for every selected instrument.
    allmembers=pd.read_parquet(ROOT/'evidence/historical-extension-inputs-20260913/membership_rows.parquet')
    selected=allmembers[allmembers.instrument_id.isin(members.instrument_id.unique())]
    for row in selected.drop_duplicates('path').itertuples():
        p=Path(row.path);copy(p,Path('lake')/p.relative_to(PROD/'data/lake'),row.sha256)
        counts['universe_membership']=counts.get('universe_membership',0)+1
    build=PROD/'artifacts/audit/sharadar_corporate_action_corrected_lake.json'
    lake=PROD/json.loads(build.read_text())['corrected_lake']
    protocol=json.loads((COVER/'PROTOCOL.json').read_text())
    cutoff=int(pd.Timestamp('2019-12-30',tz='UTC').timestamp()*1000)
    action_rows=0
    for iid in sorted(members[members.sleeve.eq('k30_dn_63')].instrument_id.unique()):
        for year in range(2019,2027):
            rel=Path('corporate_actions')/f'instrument_id={iid}'/f'year={year}'/'data.parquet';source=lake/rel
            if not source.exists():continue
            copy(source,Path('raw_actions')/rel)
            table=pq.ParquetFile(source).read()
            ts=pd.to_datetime(table.column('ex_date').to_pandas(),utc=True).astype('datetime64[ms, UTC]').astype('int64')
            indexes=[int(i) for i,t in enumerate(ts) if cutoff<=t<protocol['end_exclusive_ms']]
            filtered=table.take(pa.array(indexes,type=pa.int64()))
            target=OUT/'lake'/rel;target.parent.mkdir(parents=True,exist_ok=True);pq.write_table(filtered,target)
            assert pq.ParquetFile(target).read().equals(filtered)
            outputs[str(Path('lake')/rel)]=sha(target);action_rows+=len(indexes)
            counts['corporate_actions']=counts.get('corporate_actions',0)+1
    references=[COVER/'PROTOCOL.json',COVER/'source_manifest.json',COVER/'instrument_versions.json',COVER/'active_intervals.parquet',build,ROOT/'evidence/core-2023-2026-equity-dependencies-20260913/result.json',ROOT/'evidence/core-2023-2026-funding-lifecycle-20260913/closure.json',ROOT/'evidence/core-2023-2026-gap-preparation-20260913/closure.json',overlay_root/'result.json',ROOT/'artifacts/analysis/alphamax_covariance_basis_20260913/state/settings.json',ROOT/'artifacts/analysis/crypto_full2022_terminal_20260913/state/settings.json',ROOT/'evidence/crypto-full2022-terminal-20260913/EXPERIMENT_SPEC.json',Path(__file__)]
    for i,p in enumerate(references):copy(p,Path('references')/f'{i}_{p.name}')
    result={'status':'SNAPSHOT_ASSEMBLED_NO_SIGNALS_OR_RETURNS','tables':counts,'action_rows':action_rows,'source_files':len(sources),'output_files':len(outputs),'action_floor_ms':cutoff,'qualification':False,'limitations':['Current metadata/membership applicability modeled, not observed PIT','Original corrected-reference action floor retained; older raw-price volatility artifacts unresolved','Funding and terminal boundary exposure checks required in replay','Only AlphaMax and crypto inputs assembled here; confirmedTrend and combination still require frozen bindings']}
    (OUT/'manifest.json').write_text(json.dumps({'source_sha256':sources,'output_sha256':outputs,'result':result},indent=2)+'\n')
    for p,d in outputs.items():assert sha(OUT/p)==d
    (OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
