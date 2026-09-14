"""Match former-ticker dividends under issuer-confirmed rename route."""
import json,hashlib
from decimal import Decimal
from pathlib import Path
R=Path(__file__).resolve().parents[1];O=R/'evidence/alphamax-gold-ticker-route-20260913';U=R/'evidence/alphamax-payment-schedule-review-v2-20260913/unresolved.json'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
receipt=json.loads((O/'receipt.json').read_text());assert receipt['http_status']==200 and sha(O/'AMRK_dividends.json')==receipt['sha256']
body=json.loads((O/'AMRK_dividends.json').read_text());assert body['status']=='OK' and not body.get('next_url')
identity=json.loads((O/'issuer_identity.json').read_text());assert len(identity['lines'])==2
resolved=[];pending=[]
for x in json.loads(U.read_text()):
 if x['symbol']!='GOLD':continue
 assert x['ex_date']<'2025-12-02'
 rows=[v for v in body['results'] if v['ticker']=='AMRK' and v['ex_dividend_date']==x['ex_date']]
 if len(rows)==1 and rows[0].get('currency')=='USD' and abs(Decimal(str(rows[0]['cash_amount']))-Decimal(str(x['cash_amount'])))<=Decimal('0.00000001') and rows[0].get('pay_date','')>=x['ex_date']:
  resolved.append({'instrument_id':x['instrument_id'],'symbol':'GOLD','historical_query_symbol':'AMRK','ex_date':x['ex_date'],'amount':str(x['cash_amount']),'pay_date':rows[0]['pay_date'],'basis':'issuer_confirmed_former_ticker_exact_cash_match','amount_changed':False,'vendor_id':rows[0]['id']})
 else:pending.append(x)
assert len(resolved)+len(pending)==15
report={'status':'HISTORICAL_TICKER_ROUTE_ADJUDICATED','resolved':resolved,'pending':pending,'resolved_count':len(resolved),'limits':'Issuer filing corroborates2025rename for this entity; retrospective raw source uses latest ticker for history. Does not certify all historical universe selection, metadata, prices or point-in-time dissemination. Original current-ticker misses preserved.','sha256':{str(p.relative_to(R)):sha(p) for p in [Path(__file__),U,O/'AMRK_dividends.json',O/'receipt.json',O/'protocol.json',O/'issuer_identity.json']}}
with (O/'adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print('Resolved',len(resolved),'pending',len(pending))
