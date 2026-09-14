"""Capture the first allocation of the pinned reproduction; stop before any orders."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / 'artifacts/analysis/alphamax_durable_replay_20260912/workspace'
OUT = ROOT / 'evidence/alphamax-initial-allocation-20260912'


def write(name, value):
    with (OUT / name).open('x') as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write('\n')


class Captured(BaseException):
    pass


def main():
    OUT.mkdir(exist_ok=False)
    write('protocol.json', {
        'scope': 'FIRST_ALLOCATION_DIAGNOSTIC_NO_ORDERS_OR_RETURN_MEASUREMENT',
        'hypothesis': '5bb3bb225a077910', 'new_hypotheses': 0,
        'union_hypotheses': 238,
        'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'pinned_source': str(PIN / 'src'),
        'original_forecasts_available': False,
    })
    work = OUT / 'workspace'
    work.mkdir()
    (work / 'data').symlink_to((PIN / 'data').resolve(), target_is_directory=True)
    shutil.copytree(PIN / 'var', work / 'var')
    shutil.copytree(PIN / 'configs', work / 'configs')
    os.chdir(work)
    sys.path.insert(0, str(PIN / 'src'))
    from alphaforge.cli.main import app
    from alphaforge.portfolio.strategy import BlendStrategy

    original = BlendStrategy._rebalance
    captured = {}

    def profile(frame, event, arg):
        if frame.f_code is original.__code__ and event == 'return':
            captured.update(frame.f_locals)

    def trace(self, ctx, mu_map):
        sys.setprofile(profile)
        try:
            targets = original(self, ctx, mu_map)
        finally:
            sys.setprofile(None)
        if targets is None:
            return None
        ids = captured['ids']
        mu = captured['mu']
        order = np.argsort(-mu, kind='stable')
        rank = np.empty(len(ids), dtype=int)
        rank[order] = np.arange(1, len(ids) + 1)
        frame = pd.DataFrame({
            'instrument_id': ids, 'mu_ann': mu, 'rank_desc': rank,
            'sigma_ann': np.sqrt(np.diag(captured['cov_ann'])),
            'shortable': captured['shortable'],
            'allocator_weight': captured['result'].weights,
            'target_weight': [targets[i] for i in ids],
        })
        frame.to_parquet(OUT / 'allocation.parquet', index=False)
        pd.DataFrame(captured['cov_ann'], index=ids, columns=ids).to_parquet(
            OUT / 'covariance.parquet')
        captured['closes'].to_parquet(OUT / 'close_panel.parquet')
        focus = frame[frame.instrument_id.str.contains('TEAM|CVS')]
        write('result.json', {
            'decision_ts': int(ctx.ts), 'cross_section': len(ids),
            'vol_overlay_scale': float(captured['scale']),
            'focus': focus.to_dict(orient='records'),
            'short_boundary': frame.sort_values('rank_desc').iloc[-33:-27].to_dict(
                orient='records'),
            'orders_generated': 0,
            'limitation': 'Fresh-input ranking only; original forecast/covariance absent',
        })
        raise Captured()

    BlendStrategy._rebalance = trace
    command = json.loads((PIN.parent / 'replay.json').read_text())['command'][3:]
    command[-1] = 'unused_output'
    try:
        app(args=command, standalone_mode=False)
    except Captured:
        write('inventory.json', {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(OUT.iterdir()) if p.is_file()
        })
        print((OUT / 'result.json').read_text())
    else:
        raise RuntimeError('No allocation captured')


if __name__ == '__main__':
    main()
