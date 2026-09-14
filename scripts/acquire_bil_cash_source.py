"""Two bounded existing-provider requests; no credentials in receipts or errors."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,io
import httpx,pandas as pd
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence/bil-source-capture-20260913'
def write(p,v):
 with p.open('x') as f:json.dump(v,f,indent=2);f.write('\n')
def main():
 write(OUT/'protocol.json',{'symbol':'BIL','from':'2021-01-01','to':'2026-06-01','tables':['funds','actions'],'max_requests':2,'retries':0,'limit':10000,'scope':'current-vintage source acquisition only; no returns','runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
 key=dotenv_values(Path.home()/'.config/alphaforge/sharadar_direct.env')['SHARADAR_API_KEY'].strip()
 with httpx.Client(timeout=40,trust_env=False,follow_redirects=False) as client:
  for table in ['funds','actions']:
   params={'ticker':'BIL','from':'2021-01-01','to':'2026-06-01','format':'csv','sort':'date.asc','limit':10000}
   receipt={'table':table,'params':params,'requested_at':datetime.now(timezone.utc).isoformat()}
   try:
    response=client.get('https://api.sharadar.com/v1.0/data/'+table,params=params|{'api_key':key})
    receipt['http_status']=response.status_code
    if response.status_code!=200:raise ValueError('Request failed')
    data=response.content;(OUT/f'{table}_BIL.csv').write_bytes(data)
    frame=pd.read_csv(io.BytesIO(data),dtype=str,keep_default_na=False)
    assert {'ticker','date'}<=set(frame.columns)
    assert len(frame)<10000 and frame.ticker.eq('BIL').all()
    dates=pd.to_datetime(frame.date,format='%Y-%m-%d',errors='raise');assert dates.between('2021-01-01','2026-06-01').all()
    if table=='funds':assert len(frame)>0 and not frame.duplicated(['ticker','date']).any()
    receipt.update(complete=True,rows=len(frame),sha256=hashlib.sha256(data).hexdigest(),columns=list(frame.columns),received_at=datetime.now(timezone.utc).isoformat())
   except Exception as e:receipt.update(complete=False,error_type=type(e).__name__)
   write(OUT/f'{table}_receipt.json',receipt);print({k:v for k,v in receipt.items() if k in ['table','complete','rows','http_status','error_type']},flush=True)
if __name__=='__main__':main()
