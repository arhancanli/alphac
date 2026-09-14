"""Check inactive cooldown parameter on retained2022 paths, not a strategy replay."""
import ast
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from alphaforge.risk.monitors import DrawdownLadder, DDState
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/cooldown-2022-invariance-20260913'
SAVED=ROOT/'artifacts/analysis/alphamax_covariance_basis_20260913'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    refs={}
    def bind(p):refs[str(p.relative_to(ROOT))]=sha(p);return p
    bind(OUT/'PROTOCOL.json')
    manifest=json.loads(bind(SAVED/'input_manifest.json').read_text())['sha256']
    for path,digest in manifest.items():assert sha(ROOT/path)==digest,path
    monitor=ROOT/'src/alphaforge/risk/monitors.py';tree=ast.parse(bind(monitor).read_text())
    parents={child:node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    reads=[node for node in ast.walk(tree) if isinstance(node,ast.Attribute) and node.attr=='_flat_cooldown_bars' and isinstance(node.ctx,ast.Load)]
    assert len(reads)==1
    node=reads[0];guards=[]
    while node in parents:
        node=parents[node]
        if isinstance(node,ast.If):guards.append(ast.unparse(node.test))
    assert 'self._state is DDState.FLAT_HALTED' in guards,guards
    runtime_consumers=[]
    for p in (ROOT/'src/alphaforge').rglob('*.py'):
        for node in ast.walk(ast.parse(p.read_text())):
            if isinstance(node,ast.Attribute) and node.attr=='flat_cooldown_bars' and isinstance(node.ctx,ast.Load):runtime_consumers.append({'path':str(p.relative_to(ROOT)),'line':node.lineno})
    # All runtime field consumers must be known constructor wiring, not alpha computations.
    assert all(x['path'] in ['src/alphaforge/portfolio/strategy.py'] for x in runtime_consumers),runtime_consumers
    settings=json.loads(bind(SAVED/'state/settings.json').read_text());risk=settings['risk'];assert risk['flat_cooldown_bars']==336
    rows=[]
    for arm in ['sessions_splits','sessions_splits_stress']:
        d=SAVED/arm;c=json.loads(bind(d/'closure.json').read_text());assert sha(ROOT/c['packet'])==c['packet_sha256']
        audit=json.loads(bind(d/'independent_audit.json').read_text())
        for p,h in audit['source_sha256'].items():assert sha(ROOT/p)==h
        wf=json.loads(bind(d/'run/walkforward.json').read_text());assert sum(x['risk_counters']['bars_halted_flat'] for x in wf['legs'])==0
        assert sum(x['risk_counters']['n_auto_rearms'] for x in wf['legs'])==0
        eq=pd.read_parquet(bind(d/'run/equity.parquet')).equity.to_numpy();assert len(eq)==253
        ladders=[DrawdownLadder(dd_half_frac=abs(risk['dd_halve_gross']),dd_flat_frac=abs(risk['dd_flat_halt']),flat_cooldown_bars=n) for n in [336,10]]
        # Test both actual first-observation initialization and conservative initial-cash seed.
        for seed in [False,True]:
            pair=[DrawdownLadder(dd_half_frac=abs(risk['dd_halve_gross']),dd_flat_frac=abs(risk['dd_flat_halt']),flat_cooldown_bars=n) for n in [336,10]]
            if seed:
                for ladder in pair:ladder.update(100000.)
            states=[]
            for equity in eq:
                states=[x.update(float(equity)) for x in pair]
                assert states[0]==states[1] and states[0] is not DDState.FLAT_HALTED
                assert pair[0].gross_multiplier()==pair[1].gross_multiplier()
        rows.append({'arm':arm,'saved_marks':len(eq),'halted_bars':0,'rearms':0,'state_and_multiplier_equal_both_initializations':True})
    bind(ROOT/'src/alphaforge/portfolio/strategy.py');bind(Path(__file__))
    result={'status':'STRUCTURAL_2022_COOLDOWN_NON_INFLUENCE_VERIFIED','arms':rows,'cooldown_runtime_read_guards':guards,'public_field_consumers':runtime_consumers,'new_strategy_returns':False,'qualification':False,'interpretation':'Same deterministic upstream state until a first halt; no baseline halt occurs, so changed cooldown cannot cause first divergence. This establishes non-influence on these retained2022 paths, not a rerun or future performance guarantee.'}
    (OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n');(OUT/'source_manifest.json').write_text(json.dumps({'sha256':refs},indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
