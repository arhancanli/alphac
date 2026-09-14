"""Compare the six saved semantic-correction arms; no strategy recomputation."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/alphamax_covariance_basis_20260913'
CONTROL=ROOT/'artifacts/analysis/alphamax_share_ratio_20260913'
ARMS=['baseline','baseline_stress','sessions','sessions_stress','sessions_splits','sessions_splits_stress']


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    rows={};proof={}
    for arm in ARMS:
        directory=(CONTROL/('momentum_sigma' if arm=='baseline' else 'momentum_sigma_stress')) if arm in ['baseline','baseline_stress'] else OUT/arm
        c=json.loads((directory/'closure.json').read_text())
        p=ROOT/c['packet'];assert sha(p)==c['packet_sha256']
        packet=json.loads(p.read_text());h=packet.pop('content_hash');assert h=='sha256:'+hashlib.sha256(json.dumps(packet,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        for ref in next(iter(packet['required_sections'].values()))['evidence']: assert sha(ROOT/ref['path'])==ref['sha256']
        a=json.loads((directory/'independent_audit.json').read_text())
        b=json.loads((directory/'benchmark_audit.json').read_text())
        for key,h in a['source_sha256'].items(): assert sha(ROOT/key)==h
        rows[arm]={k:b[k] for k in ['total_return','raw_sharpe','net_excess_sharpe_DFF_proxy','max_drawdown']}
        wf=json.loads((directory/'run/walkforward.json').read_text())
        rows[arm]['whole_run_turnover']=wf['summary']['turnover_ann']
        rows[arm]['whole_run_fees']=wf['summary']['fees_paid']
        proof[arm]={'packet_sha256':sha(p),'accounting_residual':max(x['max_abs_residual'] for x in a['legs'])}
    gates={}
    for mode in ['sessions','sessions_splits']:
        a,b=rows['baseline'],rows[mode]
        gates[mode]={'excess_gain_at_least_0_1':b['net_excess_sharpe_DFF_proxy']-a['net_excess_sharpe_DFF_proxy']>=.1,'drawdown_not_worse':b['max_drawdown']<=a['max_drawdown'],'return_not_worse':b['total_return']>=a['total_return'],'cost_stress_excess_gain_positive':rows[mode+'_stress']['net_excess_sharpe_DFF_proxy']>rows['baseline_stress']['net_excess_sharpe_DFF_proxy']}
    result={'rows':rows,'development_gates':gates,'proof':proof,'qualified':False,'semantic_correction_required_regardless_of_performance':True}
    with (OUT/'comparison.json').open('x') as f: json.dump(result,f,indent=2);f.write('\n')
    lines=['# AlphaMax covariance basis: four new arms and retained controls\n','| Arm | Return | Excess Sharpe proxy | Drawdown |','|---|---:|---:|---:|']
    for arm,r in rows.items(): lines.append(f"| {arm} | {r['total_return']:.3%} | {r['net_excess_sharpe_DFF_proxy']:.6f} | {r['max_drawdown']:.3%} |")
    lines.extend(['\nRetained controls296/297 are reused without recomputation. Four new covariance arms have251 source-session returns with an observedDec31 predecessor; every engine mark independently reconciled. Both cost levels remain reported.\n','Session arms restore the requested covariance history. Session_splits additionally applies scoped share-ratio corrections in covariance closes. All arms retain corrected momentum and signal sigma. Raw-open labels cannot change the single normalized factor weight, but their semantic and availability limitations remain. No lookback/parameter sweep. Performance deterioration does not justify restoring incorrect units.\n','This retrospective2022 comparison cannot qualify the combined portfolio or a sleeve. Current-vintage modeled metadata/actions/DFF, older unscoped actions, raw-open labels, covariance/execution risk inputs, short availability and financing remain limitations. The historical legacy price helper remains intact solely to preserve trials; no production or live correction was deployed.\n'])
    (OUT/'REPORT.md').write_text('\n'.join(lines))
    with (OUT/'phase_closure.json').open('x') as f: json.dump({'status':'FOUR_ARM_COVARIANCE_BASIS_COMPARISON_COMPLETE','qualified':False,'goal_complete':False,'sha256':{str(p.relative_to(ROOT)):sha(p) for p in [OUT/'comparison.json',OUT/'REPORT.md',Path(__file__),ROOT/'scripts/alphamax_covariance_engine.py']}},f,indent=2);f.write('\n')
    print(json.dumps(result))


if __name__=='__main__': main()
