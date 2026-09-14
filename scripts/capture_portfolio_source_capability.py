"""Bounded read-only capture against previously verified paper account bindings."""
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alphaforge.execution.spot_clock import ClockBlocked, check_host_clock
from alphaforge.execution.spot_paper import PaperCredentials, account_digest
from alphaforge.validation.portfolio_observation import ObservationReader, collect, save_capture

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/portfolio-source-capability-20260913'


async def main():
    OUT.mkdir(exist_ok=False)
    private = Path.home()/'.local/share/alphaforge/portfolio-source-capability-20260913'
    private.mkdir(mode=0o700, parents=True, exist_ok=False)
    source = ROOT/'evidence/spot-dedicated-account-verification.json'
    prior = json.loads(source.read_text())
    configs = [('alpaca_spot.env', prior['account_binding'])] + [
        (r['config'], r['binding']) for r in prior['configured_account_comparisons']
        if r['status'] == 'VERIFIED']
    until = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=5)
    after = until - timedelta(days=1)
    try:
        clock = await check_host_clock()
    except ClockBlocked as exc:
        clock = {'status': 'BLOCKED', 'reason': str(exc), 'clock_adjusted': False}
    rows = []
    for index, (config, binding) in enumerate(configs):
        row = {'configuration': config, 'expected_binding': binding}
        reader = None
        try:
            credentials = PaperCredentials.from_file(Path.home()/'.config/alphaforge'/config)
            reader = ObservationReader(credentials)
            packet = await collect(reader, expected_binding=binding,
                                   after=after.isoformat(), until=until.isoformat())
            target = private/f'account-{index}.json'
            save_capture(target, packet)
            account_receipts = [r for r in packet['receipts']
                                if r['path'] == '/v2/account' and r['status'] == 'RECEIVED']
            matches = [account_digest(r['parsed_response']) == binding for r in account_receipts]
            scan = packet['activity_scan']
            row.update(status='CAPTURED', private_packet=str(target),
                       packet_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                       content_sha256=packet['content_sha256'],
                       receipt_count=len(packet['receipts']),
                       account_identity_reads=len(matches),
                       observed_account_bindings_match=bool(matches) and all(matches),
                       capture_complete='INCOMPLETE_OR_INVALID_CAPTURE'
                       not in packet['blocking_reasons'],
                       activity_count=len(scan['records']) if scan else None,
                       pagination_exhausted=bool(scan and scan['pagination_exhausted']),
                       repeated_response_agreement=packet['repeated_response_agreement'],
                       request_elapsed_ms=[r['elapsed_ns']/1e6 for r in packet['receipts']],
                       blocking_reasons=packet['blocking_reasons'])
        except Exception:
            row.update(status='CAPTURE_UNAVAILABLE',
                       error='credential, capture or persistence failure')
        finally:
            if reader is not None:
                await reader.close()
        rows.append(row)
        print(config, row['status'], 'identity_match=',
              row.get('observed_account_bindings_match'), 'complete=', row.get('capture_complete'),
              flush=True)
    report = {'scope': 'LIVE_READ_ONLY_PAPER_CAPABILITY',
              'prior_verification_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'activity_window': {'after': after.isoformat(), 'until': until.isoformat()},
              'clock': clock, 'accounts': rows,
              'unresolved_prior_configurations': sum(
                  r['status'] != 'VERIFIED' for r in prior['configured_account_comparisons']),
              'valuation_snapshots': 0, 'orders_submitted': 0, 'runtime_clearance': False,
              'epoch_started': False, 'cross_account_atomicity_verified': False}
    (OUT/'capability.json').write_text(json.dumps(report, indent=2)+'\n')
    os.chmod(OUT/'capability.json', 0o600)
    print('Clock:', clock['status'])


if __name__ == '__main__':
    asyncio.run(main())
