"""Audit saved equity sessions and independently reconstruct each ledger mark."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/analysis/alphamax_extended_reference_20260913'
DAY = 86400000


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    arm = argparse.ArgumentParser()
    arm.add_argument('arm')
    directory = OUT / arm.parse_args().arm
    assert (directory / 'execution_complete.json').exists()
    wf = json.loads((directory / 'run/walkforward.json').read_text())
    reservation = json.loads((directory / 'reservation.json').read_text())
    multiplier = reservation['trial_config']['research_engine']['scenario']['execution_cost_multiplier']
    settings = json.loads((OUT / 'state/settings.json').read_text())
    rate = settings['costs']['equity_borrow_bps_annual'] * multiplier * 1e-4 / 365
    calendar = XNYSCalendar()
    initial = 100000.0
    audits, curves, labels = [], [], []
    for leg in wf['legs']:
        folder = directory / f"run/legs/leg_{leg['leg']:02d}"
        durable = directory / f"durable_legs/{leg['leg']:03d}"
        assert (durable / 'SAVE_COMPLETE').exists()
        for file in folder.glob('*.parquet'):
            assert sha(file) == sha(durable / file.name)
        eq = pd.read_parquet(folder / 'equity.parquet').set_index('ts').equity
        opens = calendar.expected_bar_opens(leg['test_start'], leg['test_end'], Timeframe.D1)
        marks = [calendar.next_bar_open(t, Timeframe.D1) for t in opens]
        np.testing.assert_array_equal(eq.index.to_numpy(), marks)
        fills = pd.read_parquet(folder / 'fills.parquet')
        pos = pd.read_parquet(folder / 'positions.parquet')
        actions = pd.read_parquet(folder / 'corporate_actions.parquet')
        funding = pd.read_parquet(folder / 'funding.parquet')
        financing = pd.read_parquet(folder / 'financing.parquet')
        assert funding.empty and financing.empty
        fill_marks = fills.ts.map(lambda t: calendar.next_bar_open(int(t), Timeframe.D1))
        fill_marks = fill_marks.where(fills.reason != 'forced_flat', fills.ts)
        assert set(fill_marks).issubset(set(marks))
        realized = (fills.realized_pnl_quote - fills.fee).groupby(fill_marks).sum().reindex(marks, fill_value=0)
        action_marks = actions.action_ts  # ledger records application/mark time, not ex-date
        assert set(action_marks).issubset(set(marks))
        dividends = actions.cashflow_quote.groupby(action_marks).sum().reindex(marks, fill_value=0)
        short = pos[pos.qty < 0].assign(value=lambda x: x.qty * x.mark).groupby('ts').value.sum().reindex(marks, fill_value=0)
        gaps = pd.Series(marks, index=marks).diff().fillna(0) / DAY
        borrow = short.shift(1, fill_value=0) * gaps * rate
        unreal = pos.groupby('ts').unreal_pnl.sum().reindex(marks, fill_value=0)
        reconstructed = initial + (realized + dividends + borrow).cumsum() + unreal
        residual = float((eq - reconstructed).abs().max())
        meta = json.loads((folder / 'run_meta.json').read_text())['config']
        assert abs(borrow.sum() - meta['borrow_total']) < 1e-6
        assert abs(dividends.sum() - meta['corporate_action_cashflow_total']) < 1e-6
        assert residual < 1e-6, (leg['leg'], residual)
        audits.append({'leg': leg['leg'], 'observations': len(marks), 'max_abs_residual': residual,
                       'borrow': float(borrow.sum()), 'dividends': float(dividends.sum())})
        initial = float(eq.iloc[-1])
        curves.append(eq)
        labels.extend(opens)
    full = pd.concat(curves)
    saved = pd.read_parquet(directory / 'run/equity.parquet').set_index('ts').equity
    pd.testing.assert_series_equal(full, saved)
    expected = calendar.expected_bar_opens(1672531200000, 1780358400000, Timeframe.D1)
    mapped = pd.Series(full.to_numpy(), index=labels)
    predecessor = 1672358400000  # actual Dec30 2022 session, marked Jan3 2023
    assert predecessor in mapped.index and set(expected).issubset(mapped.index)
    year = mapped.loc[[predecessor, *expected]]
    returns = year.pct_change().dropna()
    assert len(returns) == len(expected) == 855
    frame = pd.DataFrame({'session': pd.to_datetime(expected, unit='ms', utc=True),
                          'equity': year.iloc[1:].to_numpy(), 'return': returns.to_numpy()})
    frame.to_csv(directory / 'calendar2023_2026.csv', index=False)
    report = {'status': 'SAVED_MARKS_RECONCILED_SESSION_YEAR_VERIFIED', 'legs': audits,
              'session_returns': len(returns), 'predecessor_equity': float(year.iloc[0]),
              'total_return': float(year.iloc[-1] / year.iloc[0] - 1),
              'raw_sharpe': float(returns.mean() / returns.std(ddof=1) * np.sqrt(252)),
              'max_drawdown': float((1 - year / year.cummax()).max()),
              'net_excess_sharpe': None, 'qualified': False,
              'timing': 'Engine mark at next XNYS open maps to previous source session, not minus one day.',
              'limitations': 'Retrospective modeled metadata/action timing and static borrow. Excess benchmark audit pending. No combined qualification.',
              'source_sha256': {str(p.relative_to(ROOT)): sha(p) for p in sorted((directory / 'run').rglob('*.parquet'))}}
    with (directory / 'independent_audit.json').open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'source_sha256'}))


if __name__ == '__main__':
    main()
