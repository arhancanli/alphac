"""Review specific O total cash distributions; preserve the frozen source version."""
import json, re, hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R = Path(__file__).resolve().parents[1]
S = R / 'evidence/alphamax-payment-source-full-20260913'
U = R / 'evidence/alphamax-payment-schedule-review-v4-20260913/unresolved.json'
source = S / 'O_2025_issuer_web_extract.json'
t = json.loads(source.read_text())['result']
assert 'Total' in t and 'Distribution' in t and 'Per Share' in t
assert 'Report Date: January 23, 2026' in t
iso = lambda x: datetime.strptime(x, '%m/%d/%Y').date().isoformat()
rows = [dict(zip(['record_date', 'ex_date', 'pay_date', 'amount'], [iso(a), iso(b), iso(c), d])) for a,b,c,d in re.findall(r'Common 756109104 O (\d+/\d+/2025) (\d+/\d+/2025) (\d+/\d+/2025) \$(\d+\.\d+)', t)]
assert len(rows) == 12
assert sum(Decimal(x['amount']) for x in rows) == Decimal('3.2170000')
index = {x['ex_date']:x for x in rows}
assert len(index) == 12
resolved = []
for x in json.loads(U.read_text()):
    if x['symbol'] != 'O' or not x['ex_date'].startswith('2025'): continue
    i = index[x['ex_date']]
    assert len(x['vendor_records']) == 1
    v = x['vendor_records'][0]
    assert Decimal(i['amount']) == Decimal(str(v['cash_amount']))
    assert i['pay_date'] == v['pay_date'] and i['record_date'] == v['record_date']
    assert v['currency'] == 'USD' and v['ex_dividend_date'] == x['ex_date']
    assert Decimal(str(x['cash_amount'])) != Decimal(i['amount'])
    resolved.append({'instrument_id':x['instrument_id'], 'symbol':'O', **i, 'frozen_amount':str(x['cash_amount']), 'amount_changed':True, 'basis':'specific_issuer_total_cash_distribution_correction', 'vendor_id':v['id']})
assert len(resolved) == 9
report = {'status':'NINE_SPECIFIC_ISSUER_CORRECTIONS_REVIEWED_NOT_APPLIED', 'issuer_rows':rows, 'resolved':resolved, 'limits':'Total distribution column, not ordinary taxable portion. PDF text obtained through web extraction; direct GET 403, raw PDF unavailable. Current-vintage source, not historical dissemination proof. Frozen lake unchanged; new source version and registered replay required.', 'sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__), U, source]}}
with (S / 'O_2025_adjudication.json').open('x') as f: json.dump(report, f, indent=2)
print('Reviewed', len(resolved))
