"""Reviewed COP/HON date corrections, retaining frozen event identities."""
from pathlib import Path
from decimal import Decimal
from collections import Counter
import json,hashlib
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';P=R/'evidence/alphamax-payment-schedule-review-v27-20260913';O=R/'evidence/alphamax-payment-schedule-review-v28-20260913'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
review=json.loads((P/'reviewed_schedule.json').read_text());pending=json.loads((P/'unresolved.json').read_text());excluded=json.loads((P/'excluded.json').read_text())
configs={
'COP':('2022-09-29','2022-09-28','2022-09-29','2022-10-14',[S/'COP_2022_cash_adjudication.json',R/'evidence/alphamax-exdate-rule-review-20260913/checkpoint.json'],'IssuerrecordSep29 and prior NYSERule235 ordinary prior-business-day relation support Sep28, agreeing vendor. FrozenSep29 duplicates record date.'),
'HON':('2022-11-10','2022-11-09','2022-11-11','2022-12-02',[S/'HON_2022_exception.web.json',R/'evidence/alphamax-hon-settlement-boundary-20260913/checkpoint.json'],'IssuerrecordNov11 and datedDTCsettlement table show Nov8trade settles before record, Nov9trade afterrecord. NasdaqT+2 framework and vendorNov9 corroborate holiday-adjusted boundary.')}
O.mkdir(exist_ok=False);decisions=[]
for sym,(old,new,record,pay,evidence,reason) in configs.items():
 x,=[x for x in pending if x['symbol']==sym];assert x['ex_date']==old
 vp=S/(sym+'_dividends.bin');v,=[v for v in json.loads(vp.read_text())['results'] if v['ex_dividend_date']==new]
 assert v['record_date']==record and v['pay_date']==pay and v['currency']=='USD'
 assert Decimal(str(v['cash_amount']))==Decimal(str(x['cash_amount']))
 d=O/(sym+'_date_decision.json');decisions.append(d)
 decision={'status':'AMEND_EX_DATE','original_event':x,'corrected_ex_date':new,'vendor_record':v,'rationale':reason+' Reviewed ordinary-distribution inference, not a provider correction or retained event-specific exchange designation.','limitations':'Current-vintage evidence. Does not certify every historical lifecycle or rule exception. Original baseline not overwritten.','sha256':{str(p.relative_to(R)):sha(p) for p in [vp,*evidence,P/'unresolved.json']}}
 d.write_text(json.dumps(decision,indent=2)+'\n')
 review.append({'instrument_id':x['instrument_id'],'symbol':sym,'ex_date':new,'frozen_ex_date':old,'date_decision_file':str(d.relative_to(R)),'amount':str(x['cash_amount']),'pay_date':pay,'record_date':record,'amount_changed':False,'basis':'issuer_and_historical_settlement_rule_date_adjudication'})
 pending=[p for p in pending if p!=x]
for n,v in [('reviewed_schedule.json',review),('unresolved.json',pending),('excluded.json',excluded)]: (O/n).write_text(json.dumps(v,indent=2)+'\n')
assert len(review)==3408 and len(pending)==56 and len(excluded)==2
files=[P/'gate.json',S/'match_audit.json',Path(__file__),R/'scripts/alphamax_payment_source_guard_v3.py',*decisions,*[R/x['decision_file'] for x in excluded],*[O/n for n in ['reviewed_schedule.json','unresolved.json','excluded.json']]]
g={'status':'INCOMPLETE_SOURCE_SCHEDULE_REPLAY_FORBIDDEN','total':3466,'reviewed':3408,'unresolved':56,'excluded':2,'unchanged_amount':3297,'explicit_new_amounts':111,'explicit_date_amendments':2,'unresolved_by_symbol':dict(Counter(x['symbol'] for x in pending)),'qualification':False,'limitations':'Requires sourceguardv3. Date decisions preserve original keys; current-vintage ordinary-rule inference, not complete PIT/lifecycle certification. Gross/net foreign settlement unresolved.','sha256':{str(p.relative_to(R)):sha(p) for p in files}}
(O/'gate.json').write_text(json.dumps(g,indent=2)+'\n');print(g['reviewed'],g['unresolved'])
