"""Bounded GET-only capability probe using an existing paper credential context.

Does not create or repurpose an account, place orders, or log response bodies.
"""
import asyncio
import json
from pathlib import Path
from datetime import UTC,datetime
import httpx

async def probe():
    values={}
    for line in (Path.home()/'.config/alphaforge/alpaca.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k,v=line.split('=',1)
            if k.strip() in ('APCA_API_KEY_ID','APCA_API_SECRET_KEY','APCA_API_BASE_URL'):
                values[k.strip()]=v.strip().strip('\"\'')
    if values.get('APCA_API_BASE_URL','https://paper-api.alpaca.markets').rstrip('/')!='https://paper-api.alpaca.markets':
        raise ValueError('Paper origin required')
    headers={'APCA-API-KEY-ID':values['APCA_API_KEY_ID'],'APCA-API-SECRET-KEY':values['APCA_API_SECRET_KEY']}
    result=dict(observed_at=datetime.now(UTC).isoformat(),method='GET',paper_origin=True,
                dedicated_alphaforge_account=False,orders_submitted=0,maximum_requests=2,retries=0,assets=[])
    async with httpx.AsyncClient(headers=headers,timeout=4,follow_redirects=False,trust_env=False) as client:
        for kind in ('crypto_perp','crypto'):
            entry=dict(requested_class=kind)
            try:
                async with asyncio.timeout(5):
                    async with client.stream('GET','https://paper-api.alpaca.markets/v2/assets',params={'asset_class':kind,'status':'active'}) as response:
                        entry['http_status']=response.status_code
                        buf=bytearray()
                        async for chunk in response.aiter_bytes():
                            buf.extend(chunk)
                            if len(buf)>1048576: raise ValueError('Response budget')
                        if response.status_code==200:
                            body=json.loads(buf)
                            if not isinstance(body,list): raise ValueError('Unexpected schema')
                            entry.update(returned_count=len(body),matching_tradable_count=sum(a.get('class')==kind and a.get('tradable') is True for a in body),
                                returned_classes=sorted({str(a.get('class')) for a in body}))
            except (TimeoutError,httpx.HTTPError,ValueError,TypeError,AttributeError):
                entry['status']='UNVERIFIED_ERROR'
            result['assets'].append(entry)
    return result

if __name__=='__main__':
    result=asyncio.run(probe())
    output=Path(__file__).resolve().parents[1]/'evidence/alpaca-capability.json'
    with output.open('x') as f: json.dump(result,f,indent=2); f.write('\n')
    print(json.dumps(result,indent=2))
