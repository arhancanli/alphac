# Alpaca session-date continuity correction

**Short title:** Alpaca session-date correction  
**Author:** Arhan Canli  
**Decision:** `CORRECT_TIMESTAMP_SEMANTICS_PRESERVE_RAW_MARKS`

## Finding

The first version of `scripts/audit_record_continuity.py` converted every `equity_curve.ts`
to a UTC calendar date and treated every weekday as an expected US-equity mark. That convention
is correct for the 24/7 crypto sleeve but not for the three Alpaca equity accounts.

Alpaca's `1D` portfolio-history response contains one row per open market day. In the captured
broker histories, the close for trading session D is stamped at `(D + 1) 00:00 UTC`. For example,
the rows stamped `2026-08-11T00:00:00Z` and `2026-08-18T00:00:00Z` are the finalized closes for
the XNYS sessions of Monday 2026-08-10 and Monday 2026-08-17. Reading those timestamps as UTC
calendar labels moved each close forward one day and falsely reported both Mondays as gaps.

The same audit used `weekday() < 5` as its equity-session calendar even though AlphaForge already
has an `XNYSCalendar` backed by `exchange_calendars`. That would falsely classify an exchange
holiday as a missing mark when the record reaches one.

The result was a false published statement that 2026-08-10 was a systemic missing-mark day. The
raw broker rows, account curves and earlier artifact remain preserved. No timestamp or equity value
is rewritten to make continuity look better.

## Correction contract

The corrected audit must:

1. keep 24/7 sleeve marks on UTC calendar dates;
2. map midnight-UTC Alpaca `1D` history rows to the preceding XNYS session;
3. treat a non-midnight current account snapshot as a same-session mark only when its New York
   date is an XNYS session;
4. derive expected equity dates from `XNYSCalendar`, including exchange holidays, rather than
   from weekday arithmetic;
5. regression-test the Friday-to-Monday and holiday boundaries; and
6. publish the timestamp convention and correction in the machine-readable continuity artifact.

The genuine crypto gaps remain findings. Correcting the Alpaca labels must not fill, suppress or
reinterpret any 24/7 absence.

## Evidence

- Alpaca documents that `timeframe=1D` returns entries only for days when the market is open and
  normalizes portfolio-history boundaries in `America/New_York`.
- The three broker-reconciled local curves contain the same midnight-UTC sequence and reconcile
  exactly to their dedicated Alpaca paper accounts.
- `scripts/probe_task3_attrib.py` already records and applies the D-close to D+1-midnight mapping;
  the continuity audit omitted that established convention.

## Claim boundary

This correction changes date classification only. It does not change account equity, returns,
orders, fills, Sharpe, drawdown, sleeve admission, trial accounting or the live configuration. It
does not prove uninterrupted execution; it removes two false equity gaps so that the remaining
gaps can be evaluated on their actual calendars.
