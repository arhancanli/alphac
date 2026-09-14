"""Version reviewed issuer cash corrections; never mutate the frozen source."""
import json,hashlib
from pathlib import Path
from decimal import Decimal
R=Path(__file__).resolve().parents[1];O=R/'evidence/alphamax-payment-source-full-20260913'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
source=json.loads((O/'component_reconciliation.json').read_text())
index={(x['symbol'],x['ex_date']):x for x in source['unresolved']}
reviewed=[('DELL','2024-04-22','0.45','0.445','2024-05-03','2024-04-23'),('DELL','2024-07-23','0.45','0.445','2024-08-02','2024-07-23'),('CEG','2024-08-12','0.35','0.3525','2024-09-06','2024-08-12'),('VST','2024-12-20','0.22','0.2215','2024-12-31','2024-12-20'),('ALB','2025-03-14','0.41','0.405','2025-04-01','2025-03-14')]
patches=[]
for symbol,ex,old,new,pay,record in reviewed:
 row=index[(symbol,ex)];assert Decimal(str(row['cash_amount']))==Decimal(old)
 vendor=row['vendor_records'];assert len(vendor)==1
 v=vendor[0];assert Decimal(str(v['cash_amount']))==Decimal(new) and v['currency']=='USD' and v['pay_date']==pay and v['record_date']==record
 path=O/f'{symbol}_issuer_rounding_review.json';issuer=json.loads(path.read_text());assert issuer['evidence']
 patches.append({'instrument_id':row['instrument_id'],'symbol':symbol,'ex_date':ex,'frozen_cash_amount':old,'reviewed_cash_amount':new,'pay_date':pay,'record_date':record,'issuer_url':issuer['url'],'issuer_evidence_sha256':sha(path),'vendor_id':v['id'],'ex_date_boundary':'Frozen and vendor date matched; issuer record date is independently checked, not substituted for exdate.'})
result={'status':'EXPLICIT_ISSUER_CORRECTION_OVERLAY_PREPARED_NOT_APPLIED','patches':patches,'corrections':len(patches),'frozen_source_modified':False,'new_returns_computed':False,'unchanged_amount_matches_or_adjudications':3249,'reviewed_alternative_amounts':5,'still_unresolved_events':212,'limits':'Proposed new source version requires preregistration and replay; cannot splice changes into old measured results. Issuer-derived amounts match vendor reference; publication timing and full historical identity qualification remain unproven. This overlay covers five specific events, not every event of each issuer.','next':'Finish remaining ADR/missing-source cases or document exact gate; build continuous equity replay separately from data amendment. Avoid silent timing-only acceptance of conflicting amounts.','sha256':{str(p.relative_to(R)):sha(p) for p in [Path(__file__),O/'component_reconciliation.json',O/'raw_lineage_audit.json',*[O/f'{s}_issuer_rounding_review.json' for s in ['DELL','CEG','VST','ALB']]]}}
with (O/'issuer_cash_correction_overlay.json').open('x') as f:json.dump(result,f,indent=2)
print({k:v for k,v in result.items() if k not in ['patches','sha256']})
