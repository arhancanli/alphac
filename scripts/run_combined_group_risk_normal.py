"""Single registered normal combined substitution; no optimization."""
import json,csv,hashlib
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from scipy.stats import skew,kurtosis
from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe
from alphaforge.validation.experiments import ExperimentUnion,hypothesis_hash
from alphaforge.validation.trial_reservation import validate_reservation
from run_bil_cash_experiment import stats
R=Path(__file__).resolve().parents[1];O=R/'artifacts/analysis/combined_group_risk_20260913/normal'
C=R/'artifacts/analysis/trend_group_risk_20260913/baseline';B=R/'artifacts/analysis/bil_cash_20260913/normal'
S=R/'evidence/trend-group-risk-design-20260913/EXPERIMENT_SPEC.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):
 with p.open('x') as f:json.dump(x,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
def main():
 O.mkdir(parents=True,exist_ok=False)
 audit=json.loads((C/'independent_audit.json').read_text());assert audit['status']=='ALL_SESSION_NAV_CASH_RECEIVABLES_RECONCILED'
 for p,h in audit['sha256'].items():assert sha(R/p)==h
 closure=json.loads((C/'closure.json').read_text());assert sha(R/closure['packet'])==closure['packet_sha256']
 spec=json.loads(S.read_text());paths=[S,C/'calendar2023_2026_excess.csv',C/'closure.json',C/'independent_audit.json',B/'daily.csv',B/'result.json',Path(__file__),R/'scripts/run_bil_cash_experiment.py',R/'pyproject.toml',R/'uv.lock']+list((R/'src/alphaforge').rglob('*.py'))
 write(O/'input_manifest.json',{'sha256':{str(p.relative_to(R)):sha(p) for p in paths}})
 config={'family':'trend_fixed_asset_group_risk_combined','arm':'normal','manifest_sha256':sha(O/'input_manifest.json'),'spec_sha256':sha(S)}
 log=ExperimentUnion.discover(O/'experiments.jsonl',R);now=datetime.now(timezone.utc)
 reservation=json.loads((B/'reservation.json').read_text());reservation.update(reserved_at=now.isoformat(),trial_config=config,hypothesis_identity=hypothesis_hash(config),family_trial_account='trend_fixed_asset_group_risk',return_identity_id='trend_group_risk_combined_normal_20260913',packet_public_path='/glassbox/trial-packets/trend-group-risk-combined-normal',paper_public_path='/research/trend-group-risk-combined-normal')
 reservation['governance_epoch']['reservation_ordinal']=log.n_hypotheses()+1
 write(O/'preregistration.json',{'trial_config':config,'reserved_at':now.isoformat(),'gates':spec['gates']['main_combined']})
 refs={'preregistration':O/'preregistration.json','input_data_manifest':O/'input_manifest.json','runner':Path(__file__),'python_project':R/'pyproject.toml','locked_environment':R/'uv.lock'}
 reservation['evidence']={k:{'path':str(p.relative_to(R)),'sha256':sha(p)} for k,p in refs.items()}
 write(O/'reservation.json',reservation);write(O/'reservation_validation.json',validate_reservation(reservation,trial_config=config,repo=R));log.preflight_registration(config,reservation_path=O/'reservation.json')
 base=pd.read_csv(B/'daily.csv');candidate=pd.read_csv(C/'calendar2023_2026_excess.csv')
 expected=XNYSCalendar().expected_bar_opens(1672531200000,1780358400000,Timeframe.D1)
 dates=pd.to_datetime(candidate.session,utc=True)
 assert dates.astype('int64').to_numpy().tolist()==[int(x)*1000000 for x in expected]
 series=pd.Series(candidate['return'].to_numpy(),index=dates.dt.strftime('%Y-%m-%d'))
 assert len(base)==1248 and len(candidate)==855
 frame=base.copy();aligned=series.reindex(base.day)
 assert set(base.day[aligned.isna().to_numpy()])==set(base.day)-set(series.index)
 frame['trend']=aligned.fillna(0).to_numpy()
 frame['total']=base.total+.225*(frame.trend-base.trend);frame['excess']=frame.total-frame.benchmark
 frame.to_csv(O/'daily.csv',index=False)
 result=stats(frame.to_dict('records'));result['baseline']=stats(base.to_dict('records'));result['qualified']=False
 result['annual']={str(y):{'candidate':stats(frame[frame.day.str.startswith(str(y))].to_dict('records')),'baseline':stats(base[base.day.str.startswith(str(y))].to_dict('records'))} for y in [2023,2024,2025,2026]}
 result['gates']={'excess_gain':result['excess_sharpe_proxy']-result['baseline']['excess_sharpe_proxy']>=.1,'return_not_lower':result['return']>=result['baseline']['return'],'full_drawdown':result['max_drawdown']<=.11,'annual_drawdowns':all(x['candidate']['max_drawdown']<=.11 for x in result['annual'].values()),'annual_excess_floor':all(x['candidate']['excess_sharpe_proxy']-x['baseline']['excess_sharpe_proxy']>=-.25 for x in result['annual'].values())}
 result['all_gates_pass']=all(result['gates'].values())
 log.record(config,sharpe_ann=result['excess_sharpe_proxy'],sharpe_per_period=result['excess_sharpe_proxy']/np.sqrt(365),n_obs=len(frame),skew=float(skew(frame.excess,bias=False)),kurtosis=float(kurtosis(frame.excess,fisher=False)),now_ms=int(now.timestamp()*1000),reservation_path=O/'reservation.json')
 write(O/'result.json',result);print(json.dumps(result))
if __name__=='__main__':main()
