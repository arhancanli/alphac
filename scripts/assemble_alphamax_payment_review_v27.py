"""Resolve Ferguson USD ordinary dividend against explicit issuer timetable."""
import json, re, hashlib
from collections import Counter
from pathlib import Path
from decimal import Decimal
R=Path(__file__).resolve().parents[1]
S=R/'evidence/alphamax-payment-source-full-20260913'
P=R/'evidence/alphamax-payment-schedule-review-v26-20260913'
O=R/'evidence/alphamax-payment-schedule-review-v27-20260913'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
source=S/'FERG_2022_cash.web.json'
t=' '.join(re.sub(r'L\d+:','',json.loads(source.read_text())['result']).split())
assert 'quarterly dividend of $0.75 per share' in t
assert 'Ex-dividend date: December 15, 2022' in t
assert 'Record date: December 16, 2022' in t
assert 'Payment date: February 3, 2023' in t
assert 'default currency for dividends is US dollars' in t
assert 'NYSE of Ferguson plc ordinary shares' in t
accepted=json.loads((P/'reviewed_schedule.json').read_text())
pending=json.loads((P/'unresolved.json').read_text())
excluded=json.loads((P/'excluded.json').read_text())
x,=[x for x in pending if x['symbol']=='FERG']
v,=x['vendor_records']
assert x['ex_date']==v['ex_dividend_date']=='2022-12-15'
assert v['record_date']=='2022-12-16' and v['pay_date']=='2023-02-03'
assert Decimal(str(x['cash_amount']))==Decimal('1.5')
assert Decimal(str(v['cash_amount']))==Decimal('0.75') and v['currency']=='USD'
row={'instrument_id':x['instrument_id'],'symbol':x['symbol'],'ex_date':x['ex_date'],
     'amount':'0.75','pay_date':v['pay_date'],'record_date':v['record_date'],
     'basis':'issuer_explicit_FERG_USD_ordinary_dividend_timetable',
     'amount_changed':True,'frozen_amount':str(x['cash_amount'])}
O.mkdir(exist_ok=False)
D=O/'FERG_adjudication.json'
decision={'status':'FERG_USD_ORDINARY_CASH_TERMS_CORROBORATED','original_event':x,'resolved':row,
 'rationale':'Issuer December6 2022 release gives ordinary-share quarterly USD0.75 and exact ex/record/pay dates matching vendor. Explicit correction from frozen1.50, not an annualized amount or depositary ratio conversion.',
 'limitations':'Current-vintage issuer evidence. USD share election assumed for USD research account; no GBP election modeled. Payment crosses year end and must remain receivable if held in separate2022 replay. Does not prove publication timestamp, settlement execution or complete security lifecycle.',
 'sha256':{str(p.relative_to(R)):sha(p) for p in [source,P/'unresolved.json',S/'match_audit.json',Path(__file__)]}}
D.write_text(json.dumps(decision,indent=2)+'\n')
accepted.append(row);pending=[a for a in pending if a!=x]
assert len(accepted)==3406 and len(pending)==58 and len(excluded)==2
for n,a in [('reviewed_schedule.json',accepted),('unresolved.json',pending),('excluded.json',excluded)]:
 (O/n).write_text(json.dumps(a,indent=2)+'\n')
files=[P/'gate.json',S/'match_audit.json',D,Path(__file__),R/'scripts/alphamax_payment_source_guard_v2.py',*[O/n for n in ['reviewed_schedule.json','unresolved.json','excluded.json']],*[R/x['decision_file'] for x in excluded]]
gate={'status':'INCOMPLETE_SOURCE_SCHEDULE_REPLAY_FORBIDDEN','total':3466,'reviewed':3406,'unresolved':58,'excluded':2,'unchanged_amount':3295,'explicit_new_amounts':111,'unresolved_by_symbol':dict(Counter(x['symbol'] for x in pending)),'qualification':False,
 'limitations':'Source guardv2 required; current-vintage gross terms, not full PIT/lifecycle qualification. Baseline split-only features invariant to cash edits (separate tested checkpoint); dividend-aware candidates require consistent source corrections. No lake mutation or returns.',
 'sha256':{str(p.relative_to(R)):sha(p) for p in files}}
(O/'gate.json').write_text(json.dumps(gate,indent=2)+'\n')
print(gate['status'],gate['reviewed'],gate['unresolved'])
