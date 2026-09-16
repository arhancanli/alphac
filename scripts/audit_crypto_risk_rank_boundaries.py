"""Check saved exposures against retained source bounds, without imputing funding."""
import argparse
import hashlib
import json
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/crypto_risk_normalized_rank_20260913'
HOUR=3600000

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('arm');d=OUT/parser.parse_args().arm
    assert (d/'execution_complete.json').exists()
    path=ROOT/'evidence/core-2023-2026-funding-lifecycle-20260913/funding_inventory.csv'
    inventory=pd.read_csv(path).set_index('instrument_id')
    wf=json.loads((d/'run/walkforward.json').read_text());violations=[];terminal=[];refs={str(path.relative_to(ROOT)):sha(path)};checked=0
    for leg in wf['legs']:
        folder=d/f"run/legs/leg_{leg['leg']:02d}"
        frames={n:pd.read_parquet(folder/f'{n}.parquet') for n in ['positions','fills','funding']}
        for n in frames:refs[str((folder/f'{n}.parquet').relative_to(ROOT))]=sha(folder/f'{n}.parquet')
        for n,f in frames.items():
            assert not f.instrument_id.eq('BINANCE:PERP:LUNAUSDT').any(),(leg['leg'],n)
        pos=frames['positions'];checked+=len(pos)
        for iid,g in pos.groupby('instrument_id'):
            r=inventory.loc[iid]
            # Permissive maximum observed cadence screen; not exchange schedule proof.
            bad=g[(g.ts<r.first_price_ms+HOUR)|(g.ts>r.last_price_ms+HOUR)|(g.ts<r.first_funding_ms-8*HOUR)|(g.ts>r.last_funding_ms+8*HOUR)]
            if len(bad):violations.append({'leg':leg['leg'],'instrument_id':iid,'rows':len(bad),'first_ts':int(bad.ts.min()),'last_ts':int(bad.ts.max())})
        ff=frames['fills'];t=ff[ff.reason.isin(['forced_flat','administrative_terminal_settlement'])]
        terminal.extend({'leg':leg['leg'],**x} for x in t.to_dict('records'))
    result={'status':'SAVED_EXPOSURE_BOUNDARY_SCREEN_PASS' if not violations else 'SAVED_EXPOSURE_BOUNDARY_SCREEN_FAIL','position_rows_checked':checked,'violations':violations,'luna_position_fill_funding_rows':0,'terminal_fills':terminal,'qualification':False,'limitation':'Eight-hour funding-boundary allowance is an anomaly screen, not schedule certification; shorter-cadence omissions can escape this check. Administrative final-close liquidation remains modeled.','sha256':refs}
    with (d/'boundary_audit.json').open('x') as f:json.dump(result,f,indent=2,default=str);f.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ['sha256','terminal_fills']}))
    assert not violations,violations
if __name__=='__main__':main()
