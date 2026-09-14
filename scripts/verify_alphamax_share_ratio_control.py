"""Exact saved control replay parity against measured286/287."""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/alphamax_share_ratio_20260913'
PREVIOUS=ROOT/'artifacts/analysis/alphamax_full2022_baseline_v2_20260913'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('arm',choices=['baseline','baseline_stress']);arm=parser.parse_args().arm
    directory=OUT/arm
    previous=PREVIOUS/('baseline' if arm=='baseline' else 'cost_stress')
    checked=[]
    paths=[Path('equity.parquet')]
    paths.extend(sorted(p.relative_to(directory/'run') for p in (directory/'run/legs').rglob('*.parquet')))
    for relative in paths:
        p,q=directory/'run'/relative,previous/'run'/relative
        pd.testing.assert_frame_equal(pd.read_parquet(p),pd.read_parquet(q),check_exact=True)
        checked.append({'path':str(relative),'new_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'control_sha256':hashlib.sha256(q.read_bytes()).hexdigest()})
    with (directory/'control_parity.json').open('x') as f:
        json.dump({'status':'EXACT_CONTROL_PARQUET_PARITY','files':checked,'qualified':False},f,indent=2);f.write('\n')
    print(f'{arm}: {len(checked)} parquet files exactly match prior control.')


if __name__=='__main__': main()
