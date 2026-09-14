"""Inventory retained component timestamps without computing portfolio returns."""
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/combined-2022-source-readiness-20260913'
FROZEN = ROOT / 'evidence/combined-baseline-audit-20260912/sources'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    OUT.mkdir(exist_ok=False)
    prior = json.loads((FROZEN / 'artifacts/analysis/current_book_diversification/result.json').read_text())
    sources = {}
    for relative, digest in prior['source_bindings']['sleeve_equity_inputs'].items():
        p = FROZEN / relative
        assert sha(p) == digest
        sources['legacy:' + relative] = p
    for name in ['baseline', 'baseline_stress', 'candidate', 'candidate_stress']:
        sources['trend:' + name] = ROOT / 'artifacts/analysis/alphatrend_positive_targets_20260913' / name / 'run/equity.parquet'
    for name in ['baseline', 'cost_stress']:
        sources['max:' + name] = ROOT / 'artifacts/analysis/alphamax_full2022_baseline_v2_20260913' / name / 'run/equity.parquet'
    for name in ['terminal_lower', 'terminal_lower_cost_stress']:
        sources['crypto:' + name] = ROOT / 'artifacts/analysis/crypto_full2022_terminal_20260913' / name / 'run/equity.parquet'
    rows = []
    for name,p in sources.items():
        if not p.exists():
            rows.append({'name':name,'path':str(p.relative_to(ROOT)), 'present':False})
            continue
        frame = pd.read_parquet(p, columns=['ts'])
        t = pd.to_datetime(frame.ts, unit='ms', utc=True)
        rows.append({'name':name,'path':str(p.relative_to(ROOT)), 'present':True,
                     'sha256':sha(p),'first':str(t.min()),'last':str(t.max()),
                     'rows_2022_labels':int(t.dt.year.eq(2022).sum()),'duplicates':int(t.duplicated().sum()),
                     'scope':'timestamp inventory only; label semantics and source qualification separate'})
    (OUT / 'inventory.json').write_text(json.dumps({'sources':rows,'new_returns_computed':False},indent=2)+'\n')
    print(json.dumps(rows,indent=2))


if __name__ == '__main__':
    main()
