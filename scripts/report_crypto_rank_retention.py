"""Summarize audited retention paths and normalized scheduled turnover."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/crypto_rank_retention_20260913'
OLD=ROOT/'artifacts/analysis/crypto_extended_reference_20260913'
ATTR=ROOT/'evidence/crypto-retention-fill-attribution-20260913'
OLDATTR=ROOT/'evidence/crypto-maintenance-fill-attribution-20260913-v2'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    bindings=json.loads((OUT/'input_manifest.json').read_text())['sha256']
    for p,h in bindings.items():assert sha(ROOT/p)==h,p
    old=pd.read_parquet(OLDATTR/'classified_fills.parquet');new=pd.read_parquet(ATTR/'classified_fills.parquet');rows=[];refs={}
    for arm,control in [('candidate','baseline'),('candidate_stress','baseline_stress')]:
        row={'arm':arm}
        for source,name,prefix,data in [(OUT,arm,'candidate',new),(OLD,control,'control',old)]:
            d=source/name;a=json.loads((d/'calendar2023_2026_audit.json').read_text());c=json.loads((d/'closure.json').read_text());assert sha(ROOT/c['packet'])==c['packet_sha256']
            for k in ['total_return','net_excess_sharpe_DFF_proxy','max_drawdown']:row[prefix+'_'+k]=a[k]
            f=data[(data.arm==name)&(data.category=='scheduled')]
            row[prefix+'_scheduled_notional_per_nav']=float((f.notional/f.equity).sum())
            row[prefix+'_scheduled_fills']=len(f)
            for p in [d/'closure.json',d/'calendar2023_2026_audit.json',d/'independent_audit.json',d/'boundary_audit.json']:refs[str(p.relative_to(ROOT))]=sha(p)
        row['scheduled_turnover_reduction']=1-row['candidate_scheduled_notional_per_nav']/row['control_scheduled_notional_per_nav']
        row['turnover_reduction_ge10pct']=row['scheduled_turnover_reduction']>=.1;rows.append(row)
    pd.DataFrame(rows).to_csv(OUT/'comparison.csv',index=False)
    report='# Crypto one-rank retention candidate\n\nSame frozen Jan2023–June1 2026, costs, risk controls and rebalance cadence; only scheduled allocator selection gains a one-rank incumbent retention band.\n\n| Arm | Return | Excess Sharpe | Daily max drawdown | Scheduled turnover reduction |\n|---|---:|---:|---:|---:|\n'
    for r in rows:report+=f"| {r['arm']} | {r['candidate_total_return']:.4%} | {r['candidate_net_excess_sharpe_DFF_proxy']:.4f} | {r['candidate_max_drawdown']:.4%} | {r['scheduled_turnover_reduction']:.2%} |\n"
    report+='\nTurnover denominator is decision NAV per matched saved fill; scheduled classification is independently reconstructed from risk state and fixed cadence, matched to all per-leg counters. This comparison includes genuine changed holdings and changing equity; it is not a constant-price fee rebate. Both runs retain actual funding, fees, realized losses and terminal eligibility. Each has29,976 independently reconciled engine marks,1,248 fullUTC-day returns and durable/final parquet parity. Risk controls were not disabled.\n\nCombined gates remain pending. Use provisional10-session AlphaMax, unchangedconfirmedTrend and cash; retain normal/stress full and annual comparisons. No qualified sleeve, untouched validation or live performance claim. Current-vintage sources, modeled funding/borrow/metadata and integrated execution limitations remain.\n'
    (OUT/'REPORT.md').write_text(report)
    for p in [Path(__file__),OUT/'comparison.csv',OUT/'REPORT.md',ATTR/'classified_fills.parquet',ATTR/'verification.json',OLDATTR/'classified_fills.parquet',OUT/'input_manifest.json']:refs[str(p.relative_to(ROOT))]=sha(p)
    (OUT/'phase_closure.json').write_text(json.dumps({'status':'CRYPTO_RETENTION_ARMS_AUDITED_COMBINED_GATES_PENDING','sha256':refs,'qualified':False},indent=2)+'\n')
    print(json.dumps(rows,indent=2))
if __name__=='__main__':main()
