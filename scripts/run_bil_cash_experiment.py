"""Registered BIL cash substitution. Research proxy, not sleeve qualification."""
import argparse
import csv
import hashlib
import json
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal as D
from pathlib import Path
import numpy as np
from scipy.stats import skew, kurtosis
from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe
from alphaforge.validation.experiments import ExperimentUnion, hypothesis_hash
from alphaforge.validation.trial_reservation import validate_reservation
from bil_cash_ledger import Price, Distribution, replay, combine_row

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/bil_cash_20260913'
DESIGN=ROOT/'evidence/bil-cash-experiment-20260913'
SPEC=DESIGN/'EXPERIMENT_SPEC.json'
BASE=ROOT/'artifacts/analysis/combined_session_cooldown_20260913'
PRICE=ROOT/'evidence/bil-source-capture-20260913/funds_BIL.csv'
DIST=ROOT/'evidence/bil-issuer-distributions-20260913/BIL_distributions.csv'
LIMIT='Retrospective cash implementation; constant combined weights with unmodeled inter-sleeve execution/collateral. Current-vintage sources; assumed execution costs and end-pay-date settlement. Not untouched OOS, new alpha sleeve, qualification or launch evidence.'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,obj):
    with p.open('x') as f:json.dump(obj,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
def readcsv(p):
    with p.open() as f:return list(csv.DictReader(f))
def prepare():
    original=json.loads((DESIGN/'design_inputs.json').read_text())['sha256']
    for p,h in original.items():
        assert sha(ROOT/p)==h,p
    paths=[SPEC,DESIGN/'design_inputs.json',Path(__file__),ROOT/'scripts/bil_cash_ledger.py',ROOT/'tests/unit/test_bil_cash_ledger.py',ROOT/'pyproject.toml',ROOT/'uv.lock',BASE/'candidate/reservation.json']
    paths+=list((ROOT/'src/alphaforge').rglob('*.py'))
    bindings={**original,**{str(p.relative_to(ROOT)):sha(p) for p in paths}}
    OUT.mkdir(exist_ok=False)
    write(OUT/'protocol.json',json.loads(SPEC.read_text()))
    write(OUT/'input_manifest.json',{'sha256':bindings})
    print(f'Prepared {len(bindings)} bindings; no historical returns or reservation.')
def stats(rows):
    total=np.array([float(x['total']) for x in rows])
    excess=np.array([float(x['excess']) for x in rows])
    nav=np.r_[1.,np.cumprod(1+total)]
    return {'return':float(nav[-1]-1),'raw_sharpe':float(total.mean()/total.std(ddof=1)*np.sqrt(365)),
            'excess_sharpe_proxy':float(excess.mean()/excess.std(ddof=1)*np.sqrt(365)),
            'max_drawdown':float((1-nav/np.maximum.accumulate(nav)).max()),'observations':len(rows)}
def execute(arm):
    for p,h in json.loads((OUT/'input_manifest.json').read_text())['sha256'].items():
        assert sha(ROOT/p)==h,p
    spec=json.loads(SPEC.read_text())
    target=OUT/arm;target.mkdir(exist_ok=False)
    config={'family':spec['family'],'arm':arm,'spec_sha256':sha(SPEC),'input_manifest_sha256':sha(OUT/'input_manifest.json')}
    log=ExperimentUnion.discover(target/'experiments.jsonl',ROOT)
    now=datetime.now(timezone.utc)
    reservation=json.loads((BASE/'candidate/reservation.json').read_text())
    reservation.update(reserved_at=now.isoformat(),trial_config=config,hypothesis_identity=hypothesis_hash(config),
        family_trial_account=spec['family'],return_identity_id=f'bil_cash_{arm}_20260913',
        packet_public_path=f'/glassbox/trial-packets/bil-cash-{arm}-20260913',paper_public_path='/research/bil-cash-20260913')
    reservation['governance_epoch']['reservation_ordinal']=log.n_hypotheses()+1
    write(target/'preregistration.json',{'trial_config':config,'reserved_at':now.isoformat(),'limitations':LIMIT})
    sources={'preregistration':target/'preregistration.json','input_data_manifest':OUT/'input_manifest.json',
             'runner':Path(__file__),'python_project':ROOT/'pyproject.toml','locked_environment':ROOT/'uv.lock'}
    reservation['evidence']={k:{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for k,p in sources.items()}
    write(target/'reservation.json',reservation)
    write(target/'reservation_validation.json',validate_reservation(reservation,trial_config=config,repo=ROOT))
    log.preflight_registration(config,reservation_path=target/'reservation.json')
    try:
        start=date.fromisoformat(spec['evaluation']['start']);end=date.fromisoformat(spec['evaluation']['end_inclusive'])
        stamp=lambda x:int(datetime(x.year,x.month,x.day,tzinfo=timezone.utc).timestamp()*1000)
        expected=XNYSCalendar().expected_bar_opens(stamp(start),stamp(end+timedelta(days=1)),Timeframe.D1)
        sessions=[datetime.fromtimestamp(int(x)/1000,timezone.utc).date() for x in expected]
        prices=[Price(date.fromisoformat(r['date']),D(r['open']),D(r['closeunadj'])) for r in readcsv(PRICE)]
        events=[Distribution(date.fromisoformat(r['ex_date']),date.fromisoformat(r['pay_date']),D(r['total'])) for r in readcsv(DIST)]
        cost=spec['cash_book']['stress_one_way_cost_bps' if arm=='stress' else 'normal_one_way_cost_bps']
        ledger=replay(prices,events,sessions,start,end,D(str(spec['cash_book']['initial_nav_usd'])),D(str(cost)))
        with (target/'ledger.csv').open('x') as f:
            writer=csv.DictWriter(f,fieldnames=list(ledger[0]));writer.writeheader();writer.writerows(ledger)
        baseline=readcsv(BASE/('candidate_stress' if arm=='stress' else 'candidate')/'daily.csv')
        assert len(baseline)==len(ledger)==spec['evaluation']['calendar_days']
        assert [x['day'] for x in baseline]==[str(x['day']) for x in ledger]
        combined=[combine_row(b,x['net_return']) for b,x in zip(baseline,ledger)]
        with (target/'daily.csv').open('x') as f:
            writer=csv.DictWriter(f,fieldnames=list(combined[0]));writer.writeheader();writer.writerows(combined)
        result=stats(combined);result.update(qualified=False,limitations=LIMIT,baseline=stats(baseline))
        result['annual']={str(y):{'candidate':stats([r for r in combined if r['day'].startswith(str(y))]),
                                'baseline':stats([r for r in baseline if r['day'].startswith(str(y))])} for y in spec['evaluation']['annual_slices']}
        excess=np.array([x['excess'] for x in combined])
        record=log.record(config,sharpe_ann=result['excess_sharpe_proxy'],sharpe_per_period=result['excess_sharpe_proxy']/np.sqrt(365),
                          n_obs=len(combined),skew=float(skew(excess,bias=False)),kurtosis=float(kurtosis(excess,fisher=False)),
                          now_ms=int(now.timestamp()*1000),reservation_path=target/'reservation.json')
        write(target/'immutable_measurement.json',record.to_json_obj())
        write(target/'result.json',result)
        write(target/'measurement_status.json',{'status':'MEASURED_REQUIRES_INDEPENDENT_ACCOUNTING_AND_PACKET_CLOSURE','qualified':False})
        print(json.dumps({'arm':arm,'result':result}))
    except Exception as error:
        write(target/'failure.json',{'status':'FAILED_PRESERVE_IDENTITY','error_type':type(error).__name__})
        raise

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');parser.add_argument('--arm',choices=['normal','stress'])
    args=parser.parse_args()
    if args.prepare:prepare()
    elif args.arm:execute(args.arm)
    else:parser.error('choose prepare or arm')
