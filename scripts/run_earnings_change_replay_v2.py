"""Continuous fixed earnings candidate. Prepare binds inputs; run reserves before scores."""
from pathlib import Path
from datetime import datetime,timezone
from dataclasses import asdict
from decimal import Decimal
import argparse,json,hashlib,copy
import pandas as pd
import pyarrow.parquet as pq
import exchange_calendars as xc
from scipy.stats import skew,kurtosis
from alphaforge.config.settings import Settings
from alphaforge.core.instruments import Instrument,InstrumentStore
from alphaforge.core.types import AssetClass,MarketType
from alphaforge.core.time import Timeframe
from alphaforge.costs import TransactionCostModel
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.backtest.payable_engine import PayableEquityBacktester
from alphaforge.execution.corporate_actions import CorporateAction,CorporateActionType
from alphaforge.validation.trend_dividend_settlement import DividendPayment
from alphaforge.validation.experiments import ExperimentUnion,hypothesis_hash
from alphaforge.validation.trial_reservation import validate_reservation
from alphaforge.analytics.session_metrics import summarize_equity_sessions
from earnings_archive_book import EarningsArchiveBook
from earnings_monthly_strategy import EarningsMonthlyStrategy,callback_routes
from earnings_split_cost_inputs import EarningsSplitCostInputs
from earnings_replay_guards import require_closed_normal
from alphaforge.core.calendar import calendar_for
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/earnings_change_20260913_v2'
SNAP=ROOT/'evidence/core-2023-2026-frozen-inputs-20260913'
ACTION=ROOT/'evidence/earnings-action-schedule-20260913'
MAPPING=ROOT/'evidence/earnings-pair-coverage-20260913/mapping.csv'
SF1=Path('/Users/arhancanli/alphaforge/data/sharadar_raw/SF1.zip')
START=1672272000000 # Dec29 2022 source-session warm start
END=1780444800000 # June3 2026 exclusive label: include June1 source close atJune2

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):
 with p.open('x') as f:json.dump(v,f,indent=2,default=str,allow_nan=False);f.write('\n')
def prepare():
 OUT.mkdir(parents=True,exist_ok=False)
 manifest=json.loads((SNAP/'manifest.json').read_text());bindings={}
 for relative,digest in manifest['output_sha256'].items():
  p=SNAP/relative
  if sha(p)!=digest:raise ValueError(f'Frozen input mismatch: {p}')
  bindings[str(p)]=digest
 files=[SF1,MAPPING,ACTION/'schedule.json',ACTION/'execution_inputs.json',ROOT/'pyproject.toml',ROOT/'uv.lock',Path(__file__),ROOT/'evidence/earnings-pair-coverage-20260913/CANDIDATE_DESIGN.md']
 files+=list((ROOT/'src/alphaforge').rglob('*.py'))
 files +=[ROOT/'scripts'/n for n in ['earnings_archive_book.py','earnings_monthly_strategy.py','earnings_change_candidate.py','earnings_filing_inputs.py','earnings_split_cost_inputs.py','earnings_replay_guards.py']]
 bindings.update({str(p):sha(p) for p in files})
 protocol={'formula':'(netinccmn_current-netinccmn_same_fiscal_quarter_prior_year)/assets_prior_pair','scope':'retrospective continuous research, not untouched OOS','start':START,'end':END,'evaluation':'Jan1 2023 throughJune1 2026 source sessions, combined fullUTCcalendar','alpha_names':['filing_seasonal_common_income_change_v1'],'initial_cash':100000.,'rebalance':'monthly firstsourceopen/priorphysicalclose','allocation':'20long20short equal2.5percent;40eligible minimum;lexicographicstableIDties','no_trade_band':.001,'risk':'half10percent flat15percent cooldown10sessions;recoverymonthly','combined':'10percentcandidate fromcash;22.5percenteachreference316/317subbook','gates':{'standalone_excess_positive_both':True,'combined_excess_gain_each':.10,'combined_return_not_lower':True,'combined_full_and_annual_dd_max':.11,'annual_excess_floor_delta':-.25},'failure_policy':'stop formula/allocation family; no denominator/holding/width/sign/weight sweep','limitations':['historical membership/metadata modeled','dividendpay ex+nextsession modeled','static borrow not observed availability','Cost sigma split-corrected using frozen retrospective action ratios; historical action availability not certified','fixed combined subbook curve not integrated executable book']}
 write(OUT/'protocol.json',protocol);write(OUT/'input_manifest.json',{'sha256':bindings,'protocol_sha256':sha(OUT/'protocol.json')})
 print('Prepared',len(bindings),'bindings; no scores or reservation')

def run(arm):
 manifest=json.loads((OUT/'input_manifest.json').read_text())
 for p,digest in manifest['sha256'].items():
  if sha(Path(p))!=digest:raise ValueError(f'Input changed: {p}')
 if sha(OUT/'protocol.json')!=manifest['protocol_sha256']:raise ValueError('Protocol changed')
 if arm=='stress':require_closed_normal(OUT/'normal')
 directory=OUT/arm;directory.mkdir(exist_ok=False)
 inputs=json.loads((ACTION/'execution_inputs.json').read_text())['arms']['2' if arm=='stress' else '1']
 settings=Settings(**inputs['settings']);ids=[r['instrument_id'] for r in inputs['instruments']]
 config=json.loads((OUT/'protocol.json').read_text())|{'cost_arm':arm,'allocator':'earnings_monthly_equal_notional','instrument_ids':ids,'input_manifest_sha256':sha(OUT/'input_manifest.json'),'cost_sigma_basis':'split_corrected_log_returns_v1','resolved_costs':settings.costs.model_dump()}
 now=datetime.now(timezone.utc);log=ExperimentUnion.discover(directory/'experiments.jsonl',ROOT)
 reservation=copy.deepcopy(json.loads((ROOT/'artifacts/analysis/alphamax_session_cooldown_20260913/candidate/reservation.json').read_text()))
 reservation.update(reserved_at=now.isoformat(),trial_config=config,hypothesis_identity=hypothesis_hash(config),family_trial_account='filing_seasonal_common_income_change',return_identity_id=f'earnings_change_{arm}_20260913',packet_public_path=f'/glassbox/trial-packets/earnings-change-{arm}-20260913',paper_public_path=f'/research/earnings-change-{arm}-20260913')
 reservation['governance_epoch']['reservation_ordinal']=log.n_hypotheses()+1
 write(directory/'preregistration.json',{'trial_config':config,'reserved_at':now.isoformat(),'protocol_sha256':sha(OUT/'protocol.json')})
 evidence={'preregistration':directory/'preregistration.json','input_data_manifest':OUT/'input_manifest.json','runner':Path(__file__),'python_project':ROOT/'pyproject.toml','locked_environment':ROOT/'uv.lock'}
 reservation['evidence']={k:{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for k,p in evidence.items()}
 write(directory/'reservation.json',reservation)
 write(directory/'reservation_validation.json',validate_reservation(reservation,trial_config=config,repo=ROOT))
 log.preflight_registration(config,reservation_path=directory/'reservation.json')
 book=EarningsArchiveBook(SF1,MAPPING,expected_sf1_sha256=manifest['sha256'][str(SF1)],expected_mapping_sha256=manifest['sha256'][str(MAPPING)])
 cal=xc.get_calendar('XNYS',start='2022-12-28',end='2026-06-05')
 routes=callback_routes([(s.date(),cal.session_open(s).to_pydatetime(),cal.session_close(s).to_pydatetime()) for s in cal.sessions])
 files=sorted((SNAP/'lake/universe_membership').glob('instrument_id=XUSE*/year=*/data.parquet'))
 membership=pd.concat([pq.ParquetFile(p).read().to_pandas() for p in files],ignore_index=True)
 metadata={r['instrument_id']:r for r in inputs['instruments']}
 def eligible(t):
  ms=int(t.timestamp()*1000)
  current=membership[(membership.effective_from<=t)&(membership.effective_to.isna()|(membership.effective_to>t))]
  return [i for i in current.instrument_id.unique() if metadata[i]['listed_ts']<=ms and (metadata[i]['delisted_ts'] is None or metadata[i]['delisted_ts']>ms)]
 strategy=EarningsMonthlyStrategy(routes=routes,score_provider=book.scores,stable_ids=book.stable_ids,eligible_provider=eligible)
 schedule=json.loads((ACTION/'schedule.json').read_text())
 actions=[CorporateAction(**(a|{'action_type':CorporateActionType(a['action_type'])})) for a in schedule['actions']]
 payments=[DividendPayment(**(e|{'cash_per_share':Decimal(e['cash_per_share'])})) for e in schedule['payments']]
 split_events=[]
 for path in sorted((SNAP/'lake/corporate_actions').glob('instrument_id=XUSE*/year=*/data.parquet')):
  for row in pq.ParquetFile(path).read().to_pylist():
   if row['action_type']=='split':split_events.append((row['instrument_id'],int(pd.Timestamp(row['ex_date']).timestamp()*1000),float(row['ratio'])))
 reader=PITDataReader(LakePaths(SNAP/'lake'))
 cost_inputs=EarningsSplitCostInputs(reader,ids,start=START,end=END,calendar=calendar_for(AssetClass.EQUITY),split_events=split_events)
 with InstrumentStore(directory/'ops.sqlite') as store:
  for r in inputs['instruments']:store.upsert(Instrument(**(r|{'asset_class':AssetClass(r['asset_class']),'market_type':MarketType(r['market_type'])})),as_of=1)
  engine=PayableEquityBacktester(reader,store,TransactionCostModel.from_settings(settings),tf=Timeframe.D1,asset_class=AssetClass.EQUITY,cost_inputs=cost_inputs,payments=payments,retrospective_vintage_ms=schedule['retrospective_vintage_ms'],retrospective_actions=actions,no_trade_band_frac=.001,max_order_adv_frac=settings.risk.max_order_adv_frac,clamp_reduce_only_adv=settings.risk.clamp_reduce_only_adv,config_echo=config)
  book.enable_after_reservation(validated=True)
  result=engine.run(strategy,ids,start=START,end=END,initial_cash=100000.)
 result.save(directory/'run');write(directory/'strategy_audit.json',strategy.audit)
 summary=summarize_equity_sessions(result.equity,fills=result.fills,funding=result.funding,positions=result.positions)
 returns=result.equity.pct_change(fill_method=None).dropna()
 log.record(config,sharpe_ann=float(summary.sharpe),sharpe_per_period=float(returns.mean()/returns.std(ddof=1)),n_obs=len(returns),skew=float(skew(returns,bias=True)),kurtosis=float(kurtosis(returns,fisher=False,bias=True)),now_ms=int(now.timestamp()*1000),reservation_path=directory/'reservation.json')
 write(directory/'session_summary.json',asdict(summary));write(directory/'execution_complete.json',{'status':'MEASURED_REQUIRES_INDEPENDENT_ACCOUNTING_AND_ADMISSION_REVIEW','qualified':False})
 print(arm,'measured; independent audit required')
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('command',choices=['prepare','normal','stress']);args=parser.parse_args()
 try:
  prepare() if args.command=='prepare' else run(args.command)
 except Exception:
  import traceback
  failure_dir=OUT if args.command=='prepare' else OUT/args.command
  if failure_dir.exists():
   stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
   (failure_dir/f'failure_{stamp}.txt').write_text(traceback.format_exc())
  raise
