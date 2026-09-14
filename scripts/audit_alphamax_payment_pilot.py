"""Match vendor payment-date reference to frozen action amounts; no performance."""
import json,hashlib
from pathlib import Path
from decimal import Decimal
R=Path(__file__).resolve().parents[1];O=R/'evidence/alphamax-payment-source-pilot-20260913'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
protocol=json.loads((O/'protocol.json').read_text());expected=json.loads((O/'expected_actions.json').read_text())
rows=[];bindings={}
for symbol in protocol['symbols']:
 path=O/f'{symbol}_dividends.bin';receipt=json.loads((O/f'{symbol}_dividends_receipt.json').read_text());assert receipt['http_status']==200 and sha(path)==receipt['sha256']
 body=json.loads(path.read_bytes());assert body['status']=='OK' and not body.get('next_url');bindings[str(path.relative_to(R))]=sha(path)
 for e in [x for x in expected if x['symbol']==symbol]:
  matches=[x for x in body['results'] if x['ticker']==symbol and x['ex_dividend_date']==e['ex_date']]
  valid=[x for x in matches if x.get('currency')=='USD' and abs(Decimal(str(x['cash_amount']))-Decimal(str(e['cash_amount'])))<=Decimal('0.00000001') and x.get('pay_date','')>=e['ex_date']]
  rows.append({**e,'matching_vendor_rows':len(matches),'valid_payment_rows':len(valid),'accepted':len(matches)==len(valid)==1,'vendor_records':matches})
for p,h in protocol['source_bindings'].items():assert sha(R/p)==h
report={'status':'PILOT_SOURCE_MATCH_AUDITED','expected':len(rows),'accepted':sum(x['accepted'] for x in rows),'rejected':sum(not x['accepted'] for x in rows),'matches':rows,'qualification':False,'limits':'Current-vintage reference; ticker/date/amount match is not historical security identity or publication timing certification. No new strategy returns computed.','sha256':{**bindings,str(Path(__file__).relative_to(R)):sha(Path(__file__)),str((O/'protocol.json').relative_to(R)):sha(O/'protocol.json'),str((O/'expected_actions.json').relative_to(R)):sha(O/'expected_actions.json')}}
with (O/'match_audit.json').open('x') as f:json.dump(report,f,indent=2)
print({k:v for k,v in report.items() if k not in ['matches','sha256']})
