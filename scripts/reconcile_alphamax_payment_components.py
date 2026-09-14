"""Append bounded component reconciliation; preserve first source-match failures."""
import json,hashlib
from pathlib import Path
from dividend_component_match import reconcile
R=Path(__file__).resolve().parents[1];O=R/'evidence/alphamax-payment-source-full-20260913'
a=json.loads((O/'match_audit.json').read_text());resolved=[];pending=[]
for row in a['matches']:
 if row['accepted']:continue
 result=reconcile(row['symbol'],row['ex_date'],row['cash_amount'],row['vendor_records'])
 if result:resolved.append({**row,'component_reconciliation':result})
 else:pending.append(row)
keys={(x['instrument_id'],x['ex_date']) for x in resolved}
prior=json.loads((O/'triage_v2.json').read_text())
retained=[x for x in prior['retained_applied'] if (x['instrument_id'],x['ex_date']) not in keys]
report={'status':'COMPONENT_RECONCILIATION_COMPLETE_REMAINING_CONFLICTS_OPEN','resolved_component_events':len(resolved),'total_exact_or_component_matches':a['accepted']+len(resolved),'unresolved_events':len(pending),'resolved':resolved,'unresolved':pending,'retained_normal_unresolved':retained,'retained_normal_unresolved_count':len(retained),'limits':'Same date/currency, distinct ids and economic terms, common pay date, summed amount within1e-8. Duplicate-looking rows remain rejected. Vendor matching is not issuer adjudication, historical security identity or publication proof. Frozen raw amounts unchanged; no new returns.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),R/'scripts/dividend_component_match.py',R/'tests/unit/test_dividend_component_match.py',O/'match_audit.json',O/'triage_v2.json']}}
with (O/'component_reconciliation.json').open('x') as f:json.dump(report,f,indent=2)
print({k:v for k,v in report.items() if k not in ['resolved','unresolved','retained_normal_unresolved','sha256']})
