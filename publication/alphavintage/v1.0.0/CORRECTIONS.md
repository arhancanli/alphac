# AlphaVintage corrections ledger

## 2026-08-16 — missing adjacent CPI release

The former signal path could reuse an older computable monthly change when the newest release and
its immediately preceding month were not both finite. The sealed correction fails closed and skips
the vintage. No return hypothesis was added.

## 2026-08-16 — active-day portfolio calendar

The former curve omitted zero-exposure exchange sessions and overstated annualized Sharpe. The
corrected curve retains all 6,296 sessions; active-day Sharpe 0.3382 is superseded by calendar-
correct net Sharpe 0.2298. The locked Newey-West t gate fails and the verdict is KILLED.

## 2026-08-19 — public correction latency

The public state retained the withdrawn 0.3403 Sharpe and 1.82 t-statistic for three days after the
sealed correction. The current source is bound to the corrected artifacts. The latency remains
disclosed as a deployment and publication-governance failure.
