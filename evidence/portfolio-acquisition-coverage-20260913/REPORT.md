# Portfolio acquisition coverage — September 13, 2026

This phase completed a read-only adapter and tested the four retained sleeve sources at September 12, 2026, 00:00 UTC. **None supplies a complete synchronized valuation under the draft contract.** This is progress in measurement infrastructure, not evidence of improved strategy performance or qualification against the combined Sharpe >2, maximum drawdown ≤11%, and 15+ sleeve goals.

The adapter preserves source rows and their interpretation, identifies missing evidence, and returns no valuation snapshot. It opens existing SQLite databases in read-only transactions, requires the exact requested row, and rejects ambiguous duplicate records and nonfinite values. It does not replace missing observations, infer zero liabilities, or substitute the reader's clock for original receipt timestamps. Legacy floating-point arithmetic is diagnostic rather than exact decimal accounting.

| Source | Retained evidence | Missing capability |
|---|---|---|
| AlphaForge crypto | NAV, cash, nine position marks, cycle timing/status; cash plus positions reconciles within approximately $0.0000000000064 | Cycle starts 10 minutes 15.794 seconds after the declared midnight label; no individual price as-of/receipt timestamps, account partition binding, or complete flow/accrual/liability inventory |
| AlphaMax | NAV row labeled September 12 midnight | Under the history-label convention this refers to the September 11 XNYS close, four hours earlier; row origin is unverified and current-cut holdings, cash, accruals, flows, account identity and original receipt times are absent |
| AlphaTrend | Same history-label interpretation and NAV coverage | Same gaps as AlphaMax |
| AlphaVintage | Same history-label interpretation and NAV coverage | Same gaps as AlphaMax |

The crypto cycle timestamp is not a price-source timestamp. The equity exporter mixes broker history and current-account observations without per-row origin metadata, so the calendar interpretation does not authenticate individual rows. The adapter rejects invalid history labels rather than shifting them to an earlier session.

The combined book also lacks a funded overlay ledger, dated cash benchmark and complete external/internal flow inventory. Per-database consistent reads do not establish an atomic cross-account observation.

Source review found that the existing Alpaca reconciliation exporter replaces local history rows. It was inspected but not executed. The existing spot account reader checks repeated account/position agreement, which is useful but does not establish an atomic common-cut valuation. This phase made no broker calls, remote queries, production edits, backfills, new observation epoch, new market-return trials or admissions. The draft policy remains out of force.

Validation: 59 focused tests passed (19 acquisition tests and 40 valuation tests); Ruff passed for the adapter, acquisition tests and audit runner. Tests cover read-only behavior, exact-cut selection, missing/duplicate records, session interpretation, incomplete position evidence, arithmetic inconsistencies and malformed values. Four packet hashes and nine source snapshot bindings are independently checked in `verification.json`; `manifest.json` binds the saved evidence files. Hashes establish content integrity, not source authentication.

Commands run from the isolated research checkout:

```sh
PYTHONPATH=src /Users/arhancanli/alphaforge/.venv/bin/python -m pytest tests/unit/test_portfolio_acquisition.py tests/unit/test_portfolio_valuation.py -o addopts='' -q
/Users/arhancanli/alphaforge/.venv/bin/python -m ruff check src/alphaforge/validation/portfolio_acquisition.py tests/unit/test_portfolio_acquisition.py scripts/audit_portfolio_acquisition_coverage.py
PYTHONPATH=src /Users/arhancanli/alphaforge/.venv/bin/python scripts/audit_portfolio_acquisition_coverage.py
```

Next proposed bounded phase: implement a raw observation collector with request start/end times, monotonic receipt timing, account identity and complete account/position/activity evidence. Establish what timing guarantees the sources actually support before selecting a shared valuation cutoff and freshness limits. If midnight is unsupported, revise the draft prospectively with the original baseline preserved. Collection alone will not prove synchronization or source authentication. No collector or scheduled operation was started in this phase.
