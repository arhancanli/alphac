"""Trace unresolved frozen dividends to raw source without rewriting either."""
import csv,hashlib,io,json,zipfile
from collections import defaultdict,Counter
from decimal import Decimal
from pathlib import Path
R=Path(__file__).resolve().parents[1];P=Path('/Users/arhancanli/alphaforge');O=R/'evidence/alphamax-payment-source-full-20260913'
archive=P/'data/sharadar_raw/ACTIONS.zip';build=P/'artifacts/audit/sharadar_corporate_action_corrected_lake.json'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert 'sha256:'+sha(archive)==json.loads(build.read_text())['lineage']['raw_actions_archive_sha256']
prior=json.loads((O/'component_reconciliation.json').read_text());symbols={x['symbol'] for x in prior['unresolved']}
dividends=defaultdict(list);splits=defaultdict(list)
with zipfile.ZipFile(archive) as z:
 names=[n for n in z.namelist() if n.endswith('.csv')];assert len(names)==1
 with z.open(names[0]) as f:
  for row in csv.DictReader(io.TextIOWrapper(f)):
   if row['ticker'] not in symbols:continue
   if row['action']=='dividend':dividends[(row['ticker'],row['date'])].append(row)
   elif row['action']=='split':splits[row['ticker']].append(row)
rows=[];counts=Counter()
for x in prior['unresolved']:
 raw=dividends[(x['symbol'],x['ex_date'])];factor=Decimal(1)
 for s in splits[x['symbol']]:
  if s['date']>=x['ex_date']:factor*=Decimal(s['value'])
 values=[Decimal(q['value'])*factor for q in raw]
 match=len(values)==1 and abs(values[0]-Decimal(str(x['cash_amount'])))<=Decimal('0.00000001')
 kind='frozen_matches_raw_transformation_vendor_conflict' if match else 'raw_lineage_not_uniquely_matched'
 counts[kind]+=1
 rows.append({'instrument_id':x['instrument_id'],'symbol':x['symbol'],'ex_date':x['ex_date'],'frozen_amount':x['cash_amount'],'raw_dividend_rows':raw,'future_market_split_factor':str(factor),'raw_transformed_amounts':[str(v) for v in values],'classification':kind})
report={'status':'UNRESOLVED_DIVIDEND_RAW_LINEAGE_AUDITED','counts':dict(counts),'rows':rows,'no_amounts_modified':True,'no_new_returns':True,'limits':'Raw ticker/date plus retained split transformation checked, not historical security identity or correctness of either vendor cash basis. Agreement with raw source does not adjudicate payment dates or resolve vendor conflict.','sha256':{str(p):sha(p) for p in [archive,build,O/'component_reconciliation.json',Path(__file__)]}}
with (O/'raw_lineage_audit.json').open('x') as f:json.dump(report,f,indent=2)
print(dict(counts))
