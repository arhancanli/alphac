"""Private date-level annotations for retained captures; no cash mutation."""
import hashlib
import json
from pathlib import Path

from alphaforge.execution.daily_fee_reconciliation import annotate_fees
from alphaforge.validation.portfolio_observation import save_capture

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT/'evidence/daily-fee-annotations-20260913'
    out.mkdir(exist_ok=False)
    private = Path.home()/'.local/share/alphaforge/daily-fee-annotations-20260913'
    private.mkdir(mode=0o700, exist_ok=False)
    prior_path = ROOT/'evidence/portfolio-source-capability-20260913/capability.json'
    prior = json.loads(prior_path.read_text())
    rows = []
    for index, source in enumerate(prior['accounts']):
        raw = Path(source['private_packet']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != source['packet_sha256']:
            raise ValueError('source changed since capture audit')
        report = annotate_fees(json.loads(raw))
        target = private/f'account-{index}.json'
        save_capture(target, report)
        rows.append({'configuration': source['configuration'],
                     'fee_groups': [{k: v for k, v in g.items() if k != 'source_records'}
                                    for g in report['fee_groups']],
                     'fee_records': sum(len(g['source_records']) for g in report['fee_groups']),
                     'unclassified_records': len(report['unclassified_record_hashes']),
                     'receipt_span_ns': report['receipt_span_ns'],
                     'cash_unchanged': report['observed_cash_delta'] is not None
                     and float(report['observed_cash_delta']) == 0,
                     'missing_balance_fields': report['missing_balance_fields'],
                     'reconciled': report['reconciled'], 'private_annotation': str(target),
                     'annotation_sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    summary = {'accounts': rows, 'cash_mutations': 0}
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print('Accounts:', len(rows), 'fees:', sum(r['fee_records'] for r in rows),
          'reconciled:', sum(r['reconciled'] for r in rows))


if __name__ == '__main__':
    main()
