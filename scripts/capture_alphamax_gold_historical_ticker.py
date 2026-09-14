"""One bounded AMRK query justified by retained raw ticker-change evidence."""
import json,csv,io,zipfile,hashlib
from pathlib import Path
from datetime import datetime,timezone
import httpx
from dotenv import dotenv_values
R=Path(__file__).resolve().parents[1];O=R/'evidence/alphamax-gold-ticker-route-20260913';P=Path('/Users/arhancanli/alphaforge/data/sharadar_raw/ACTIONS.zip')
O.mkdir(exist_ok=False);events=[]
with zipfile.ZipFile(P) as z:
 with z.open(next(n for n in z.namelist() if n.endswith('.csv'))) as f:
  for row in csv.DictReader(io.TextIOWrapper(f)):
   if row['ticker']=='GOLD' and row['action'].startswith('tickerchange'):events.append(row)
assert any(x['contraticker']=='AMRK' and x['date']=='2025-12-02' for x in events)
protocol={'status':'SOURCE_IDENTITY_ROUTE_NO_RETURNS','raw_ticker_events':events,'raw_archive_sha256':hashlib.sha256(P.read_bytes()).hexdigest(),'query_ticker':'AMRK','start':'2022-01-01','end':'2025-12-01','max_requests':1,'retries':0,'limits':'Raw mapping supports reference lookup; independent historical security identity verification remains required.'}
(O/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
key=dotenv_values(Path.home()/'.config/alphaforge/polygon.env')['POLYGON_API_KEY']
params={'ticker':'AMRK','ex_dividend_date.gte':'2022-01-01','ex_dividend_date.lte':'2025-12-01','limit':1000}
r=httpx.get('https://api.polygon.io/v3/reference/dividends',params={**params,'apiKey':key},timeout=15,follow_redirects=False,trust_env=False)
(O/'AMRK_dividends.json').write_bytes(r.content)
(O/'receipt.json').write_text(json.dumps({'http_status':r.status_code,'retrieved_at':datetime.now(timezone.utc).isoformat(),'sha256':hashlib.sha256(r.content).hexdigest(),'request_params':params},indent=2)+'\n')
assert r.status_code==200;body=r.json();assert body['status']=='OK' and not body.get('next_url');print('Complete records',len(body['results']))
