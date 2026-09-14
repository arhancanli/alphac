"""Prepare frozen retrospective actions; next-session dividend payment is modeled."""
from pathlib import Path
from dataclasses import asdict
from decimal import Decimal
import json,hashlib,math
import pandas as pd
import pyarrow.parquet as pq
from alphaforge.execution.corporate_actions import CorporateAction,CorporateActionType
from alphaforge.validation.trend_dividend_settlement import DividendPayment
from alphaforge.core.calendar import calendar_for
from alphaforge.core.types import AssetClass
from alphaforge.core.time import Timeframe
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'evidence/core-2023-2026-frozen-inputs-20260913'
OUT=ROOT/'evidence/earnings-action-schedule-20260913'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ms(v):return int(pd.Timestamp(v).timestamp()*1000)
def main():
 manifest=json.loads((SOURCE/'manifest.json').read_text())
 paths=sorted((SOURCE/'lake/corporate_actions').glob('instrument_id=XUSE*/year=*/data.parquet'))
 actions=[];payments=[];seen=set();bindings=[]
 cal=calendar_for(AssetClass.EQUITY)
 start=ms('2022-12-29T00:00:00Z');end=ms('2026-06-03T00:00:00Z');vintage=ms('2026-09-13T00:00:00Z')
 for p in paths:
  digest=sha(p)
  assert digest==manifest['output_sha256'][str(p.relative_to(SOURCE))]
  bindings.append({'path':str(p),'sha256':digest})
  for row in pq.ParquetFile(p).read().to_pylist():
   ex=ms(row['ex_date'])
   if not start<=ex<end:continue
   cash=row['cash_amount'];cash=None if cash is None or not math.isfinite(float(cash)) else float(cash)
   a=CorporateAction(instrument_id=row['instrument_id'],action_type=CorporateActionType(row['action_type']),ex_date=ex,available_at=ms(row['available_at']),ratio=float(row['ratio']),cash_amount=cash)
   a.require_known_by(vintage)
   key=(a.instrument_id,a.ex_date,a.action_type.value)
   if key in seen:raise ValueError(f'Duplicate frozen action: {key}')
   seen.add(key);actions.append(asdict(a)|{'action_type':a.action_type.value})
   if a.action_type is CorporateActionType.CASH_DIVIDEND:
    event=DividendPayment('modeled:'+a.instrument_id+':'+str(ex),a.instrument_id,ex,cal.next_bar_open(ex,Timeframe.D1),a.available_at,Decimal(str(a.cash_amount)))
    payments.append(asdict(event)|{'cash_per_share':str(event.cash_per_share)})
 result={'status':'PREPARED_NO_SIGNALS_OR_RETURNS','payment_policy':'MODELED_EX_PLUS_NEXT_XNYS_SESSION_NOT_OBSERVED_PAY_DATE','retrospective_vintage_ms':vintage,'start':start,'end':end,'actions':actions,'payments':payments,'source_bindings':bindings,'manifest_sha256':sha(SOURCE/'manifest.json'),'builder_sha256':sha(Path(__file__))}
 (OUT/'schedule.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({'actions':len(actions),'payments':len(payments),'files_verified':len(bindings)}))
if __name__=='__main__':main()
