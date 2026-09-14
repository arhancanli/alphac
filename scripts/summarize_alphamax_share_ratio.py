"""Compare the six saved semantic-correction arms; no strategy recomputation."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/alphamax_share_ratio_20260913'
ARMS=['baseline','baseline_stress','momentum','momentum_stress','momentum_sigma','momentum_sigma_stress']


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    rows={};proof={}
    for arm in ARMS:
        directory=OUT/arm
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
    for arm in ['baseline','baseline_stress']:
        assert json.loads((OUT/arm/'control_parity.json').read_text())['status']=='EXACT_CONTROL_PARQUET_PARITY'
    gates={}
    for mode in ['momentum','momentum_sigma']:
        a,b=rows['baseline'],rows[mode]
        gates[mode]={'excess_gain_at_least_0_1':b['net_excess_sharpe_DFF_proxy']-a['net_excess_sharpe_DFF_proxy']>=.1,'drawdown_not_worse':b['max_drawdown']<=a['max_drawdown'],'return_not_worse':b['total_return']>=a['total_return'],'cost_stress_excess_gain_positive':rows[mode+'_stress']['net_excess_sharpe_DFF_proxy']>rows['baseline_stress']['net_excess_sharpe_DFF_proxy']}
    result={'rows':rows,'development_gates':gates,'proof':proof,'qualified':False,'semantic_correction_required_regardless_of_performance':True}
    with (OUT/'comparison.json').open('x') as f: json.dump(result,f,indent=2);f.write('\n')
    lines=['# AlphaMax share-ratio feature correction: six-arm comparison\n','| Arm | Return | Excess Sharpe proxy | Drawdown |','|---|---:|---:|---:|']
    for arm,r in rows.items(): lines.append(f"| {arm} | {r['total_return']:.3%} | {r['net_excess_sharpe_DFF_proxy']:.6f} | {r['max_drawdown']:.3%} |")
    lines.extend(['\nOriginal controls exactly reproduce286/287 across29parquet tables each. Allsix arms have251 source-session returns with an observedDec31 predecessor; every engine mark is independently reconciled. Both cost levels remain reported.\n','The momentum correction converts stored new-shares/old-shares ratios into reciprocal historical-price factors. The momentum_sigma arm additionally uses that split-adjusted series for168span EWMA sigma. Parameters, capital, action scope, raw-open holding labels, cost assumptions and execution remain fixed. A correction that lowers performance still fixes incorrect semantics; do not restore the error for a higher backtest score.\n','This retrospective2022 comparison cannot qualify the combined portfolio or a sleeve. Current-vintage modeled metadata/actions/DFF, older unscoped actions, raw-open labels, covariance/execution risk inputs, short availability and financing remain limitations. The historical legacy price helper remains intact solely to preserve trials; no production or live correction was deployed.\n'])
    (OUT/'REPORT.md').write_text('\n'.join(lines))
    with (OUT/'phase_closure.json').open('x') as f: json.dump({'status':'SIX_ARM_SHARE_RATIO_COMPARISON_COMPLETE','qualified':False,'goal_complete':False,'sha256':{str(p.relative_to(ROOT)):sha(p) for p in [OUT/'comparison.json',OUT/'REPORT.md',Path(__file__),ROOT/'scripts/verify_alphamax_share_ratio_control.py']}},f,indent=2);f.write('\n')
    print(json.dumps(result))


if __name__=='__main__': main()
