"""Classify saved fills by replayed risk states and fixed rebalance calendar; no returns."""
import hashlib
import json
from pathlib import Path
import pandas as pd
from alphaforge.risk.monitors import DrawdownLadder, DDState
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'artifacts/analysis/crypto_rank_retention_20260913'
OUT=ROOT/'evidence/crypto-retention-fill-attribution-20260913'
HOUR=3600000

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    OUT.mkdir(exist_ok=False);refs={};allrows=[];checks=[]
    def read(p):refs[str(p.relative_to(ROOT))]=sha(p);return p
    settings=json.loads(read(SOURCE/'state/settings.json').read_text());risk=settings['risk']
    for arm in ['candidate','candidate_stress']:
        d=SOURCE/arm;wf=json.loads(read(d/'run/walkforward.json').read_text())
        ladder=DrawdownLadder(dd_half_frac=abs(risk['dd_halve_gross']),dd_flat_frac=abs(risk['dd_flat_halt']),flat_cooldown_bars=risk['flat_cooldown_bars'])
        for leg in wf['legs']:
            folder=d/f"run/legs/leg_{leg['leg']:02d}"
            eq=pd.read_parquet(read(folder/'equity.parquet'));orders=pd.read_parquet(read(folder/'orders.parquet'));fills=pd.read_parquet(read(folder/'fills.parquet'));pos=pd.read_parquet(read(folder/'positions.parquet'))
            counters=leg['risk_counters'];assert counters['hold_stale_signal']==0 and counters['hold_cov_cold_start']==0 and counters['hold_degenerate_xsection']==0
            decisions=[];next_rebalance=None
            for row in eq.itertuples():
                previous=ladder.state
                state=ladder.update(float(row.equity))
                if state is DDState.FLAT_HALTED:
                    decisions.append({'decision_ts':int(row.ts),'state':state.name,'category':'risk_halt','equity':float(row.equity)})
                    continue
                scheduled=next_rebalance is None or row.ts>=next_rebalance
                if scheduled:next_rebalance=int(row.ts)+168*HOUR
                label='scheduled' if scheduled else ('half_transition' if state is DDState.HALF_GROSS and previous is not DDState.HALF_GROSS else 'half_maintenance' if state is DDState.HALF_GROSS else 'normal_hold')
                decisions.append({'decision_ts':int(row.ts),'state':state.name,'category':label,'equity':float(row.equity)})
            dec=pd.DataFrame(decisions)
            assert int(dec.category.eq('scheduled').sum())==counters['n_rebalances']
            assert int(dec.state.eq('HALF_GROSS').sum())==counters['bars_half_gross']
            assert int(dec.category.eq('risk_halt').sum())==counters['bars_halted_flat']
            assert int(dec.category.eq('normal_hold').sum())==counters['hold_between_rebalance']
            orders=orders[orders.client_order_id.notna() & orders.client_order_id.ne('')].copy()
            assert not orders.client_order_id.duplicated().any()
            joined=fills.merge(orders[['client_order_id','decision_ts','decision_price']],on='client_order_id',how='left',validate='many_to_one').merge(dec,on='decision_ts',how='left',validate='many_to_one')
            assert joined.category.notna().all() and not joined.category.eq('normal_hold').any()
            held=pos[['ts','instrument_id','qty']].rename(columns={'ts':'decision_ts','qty':'held_qty'})
            joined=joined.merge(held,on=['decision_ts','instrument_id'],how='left',validate='many_to_one');joined['held_qty']=joined.held_qty.fillna(0)
            delta=joined.qty.where(joined.side.eq('buy'),-joined.qty)
            joined['reduces_absolute_qty']=(joined.held_qty+delta).abs()<joined.held_qty.abs()
            joined['below_nav_band_at_decision']=joined.qty*joined.decision_price < .001*joined.equity
            joined['notional_per_nav']=joined.notional/joined.equity
            joined['arm']=arm;joined['leg']=leg['leg'];allrows.append(joined)
            checks.append({'arm':arm,'leg':leg['leg'],'risk_and_schedule_counters_match':True,'fills_classified':len(joined)})
    data=pd.concat(allrows,ignore_index=True);data.to_parquet(OUT/'classified_fills.parquet',index=False)
    grouped=data.groupby(['arm','category']).agg(fills=('fee','size'),fees_quote=('fee','sum'),notional_per_nav=('notional_per_nav','sum'),notional_quote=('notional','sum'),reducing_fills=('reduces_absolute_qty','sum'),below_band_fills=('below_nav_band_at_decision','sum')).reset_index();grouped.to_csv(OUT/'summary.csv',index=False)
    for p in [Path(__file__),ROOT/'src/alphaforge/risk/monitors.py',ROOT/'src/alphaforge/portfolio/strategy.py',ROOT/'src/alphaforge/backtest/engine.py']:read(p)
    (OUT/'verification.json').write_text(json.dumps({'status':'RISK_AND_SCHEDULE_COUNTERS_MATCH_ALL_LEGS','legs':checks,'new_strategy_returns':False,'qualification':False},indent=2)+'\n');(OUT/'source_manifest.json').write_text(json.dumps({'sha256':refs},indent=2)+'\n')
    print(grouped.to_string(index=False))
if __name__=='__main__':main()
