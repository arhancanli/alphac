"""Map private retained provider captures without broker calls or cash application."""
import hashlib
import json
from pathlib import Path

from alphaforge.execution.provider_payment_mapping import map_capture
from alphaforge.validation.portfolio_observation import save_capture

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT/'evidence/provider-payment-mapping-20260913'
    out.mkdir(exist_ok=False)
    private = Path.home()/'.local/share/alphaforge/provider-payment-mapping-20260913'
    private.mkdir(mode=0o700, exist_ok=False)
    prior_path = ROOT/'evidence/portfolio-source-capability-20260913/capability.json'
    prior = json.loads(prior_path.read_text())
    rows = []
    for i, source in enumerate(prior['accounts']):
        path = Path(source['private_packet'])
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source['packet_sha256']:
            raise ValueError('retained capture differs from prior audit')
        mapped = map_capture(json.loads(raw))
        target = private/f'account-{i}.json'
        save_capture(target, mapped)
        rows.append({'configuration': source['configuration'],
                     'capture_sha256': mapped['capture_sha256'],
                     'records': len(mapped['records']), 'coverage': mapped['coverage'],
                     'bookable_payments': len(mapped['bookable_payments']),
                     'blocking_reasons': sorted({reason for row in mapped['records']
                                                for reason in row['blocking_reasons']}),
                     'private_mapping': str(target),
                     'mapping_sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    (out/'summary.json').write_text(json.dumps({'accounts': rows, 'broker_calls': 0,
                                               'cash_mutations': 0}, indent=2)+'\n')
    print('Accounts:', len(rows), 'records:', sum(r['records'] for r in rows),
          'bookable payments:', sum(r['bookable_payments'] for r in rows))


if __name__ == '__main__':
    main()
