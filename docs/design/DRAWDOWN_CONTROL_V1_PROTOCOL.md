# Drawdown control v1: protocol

**Author:** Arhan Canli (operating session under the owner's delegation of 2026-09-14)  
**Frozen:** 2026-09-14, before executing the study  
**Capital boundary:** research and paper trading only; nothing here changes a live loop  
**Trial accounting:** existing-return risk remeasurement; zero new hypothesis identities  
**Owner goal served:** "Combined portfolio maximum drawdown no greater than 11 percent. This is
stronger than an expected-maximum-drawdown target. Show realized, historical scenario, simulated
expected and tail drawdowns separately." (`ALPHAC_OWNER_GOALS_2026-09-12.md`, outcome 2)

## Question

Can the combined ALPHAC book carry a **hard** 11 percent maximum-drawdown bound, and what does the
mechanism that makes it hard cost?

A backtest cannot promise a maximum drawdown: the published current-composition study
(`CURRENT_BOOK_DRAWDOWN_STUDY_PROTOCOL.md`) puts the two-year expected maximum drawdown at 9.3
percent and the 95th percentile at 16.5 percent under the admission contract's permitted stressed
correlation, and no configuration in the fourteen-sleeve sweep held the 95th percentile at 11. A
bound that holds in the tail is therefore a **brake**, not a forecast: a book-level drawdown ladder
that cuts gross exposure as the drawdown from the high-water mark grows and flattens the book at
the bound. The forward-drawdown evidence records that the live book declares **no** book-level
ladder and no book-level volatility target today (`production_equivalence.passes = false`).

## The declared ladder (fixed before any result was seen)

Every number below is derived from the bound, not fitted to a path.

| parameter | value | derivation |
| --- | --- | --- |
| bound `B` | 0.11 | the owner's goal, and `book_expected_max_drawdown_max` in the admission contract |
| half-gross level | 0.055 | `B / 2` |
| flat level | 0.11 | `B` |
| half-gross release | 0.04125 | `0.75 x` the half level, the existing `DrawdownLadder.RELEASE_FRAC` hysteresis |
| flat state | absorbing | a bound, not a rate limit: rearming after a halt is an owner review, never a timer |
| measurement | book daily close equity vs its high-water mark | the same definition the live crypto ladder uses (`alphaforge.risk.monitors.DrawdownLadder`) |
| exposure applied | the multiplier in force at the previous close scales the next day's book return | sizing acts on the next bar, as it does live |

The existing live ladder auto-rearms after a cooldown with the high-water mark reset to current
equity. That is correct for an unattended single sleeve (a permanently dead sleeve is worse than a
ratchet) and wrong for a bound: after a rearm the next 11 percent loss is again permitted, so the
drawdown from the all-time peak is unbounded across episodes. The book-level ladder is therefore
absorbing in this study. A secondary scenario with the live ladder's 14-day auto-rearm is also
measured and published so the difference is visible, not asserted.

## Frozen inputs and estimators

Exactly those of the current-composition study, reused by replaying its generators with its seeds
(`analyze_current_book_drawdown.py`: `PATHS = 10,000`, `HORIZON_DAYS = 730`, bootstrap seed
20260823 with the 63-day primary block, correlation-regime seed 20260824 with equicorrelation 0.50
stress at a 12 percent unconditional share and 40-day mean runs). The study script asserts, before
reporting anything, that its no-ladder baseline reproduces the published study's expected and
95th-percentile maximum drawdowns to 1e-12; if the published study moves, this study fails closed.

Two drift conventions are published for every cell:

- **zero drift**, as the published study (sample mean removed), which is the right basis for the
  drawdown bound and does not borrow the research window's Sharpe; and
- **research-window drift added back**, labelled as such, which is the only basis on which the
  cost of the brake (foregone compounding while de-risked) is visible at all. It is a research
  simulation over a paper specification, not forward evidence.

## What is measured, per model and drift convention, with and without the ladder

- expected, median, 95th, 99th percentile and maximum of the two-year maximum drawdown from the
  all-time peak (not from the ladder's internal high-water mark, which resets on rearm);
- probability of a flat halt within the horizon, and the mean day it first fires;
- mean fraction of days at reduced gross, and (auto-rearm scenario) mean rearms per path;
- mean terminal wealth and the mean two-year return, with and without the ladder;
- the overshoot: the distribution of `max_drawdown - B` on halted paths, which is the one-day move
  at half gross that a close-to-close brake cannot pre-empt.

## Decision rule, declared now

The ladder is **acceptable as the bound's mechanism** if, on the conservative model (the worse of
bootstrap-63 and the correlation regime), the 95th-percentile maximum drawdown with the absorbing
ladder is at most `B + 0.01` and the 99th percentile at most `B + 0.02`, i.e. the brake holds the
bound up to a one-day overshoot. The return cost is **published as the price**, not used as a gate:
the owner set a bound and the study prices it.

Whatever the result, it is published. If the rule fails, the finding is that a close-to-close
ladder cannot hold this bound at this volatility and the next design is intraday or a lower
half-gross level, declared in a v2 protocol before it is measured.

## What this study does not decide

Activating the ladder on the live loops is a live-configuration change under
`config/live_change_contract.json`. It changes the book's fingerprint and therefore **starts a new
forward-evidence epoch**; the 36-return record accrued since 2026-08-07 would not be pooled with
the post-change record. That trade (a bound the record can support, against five weeks of record)
is the owner's, recorded separately. Nothing in this study reserves an identity, opens a holdout,
or touches a live setting.

## Prohibitions

No parameter is chosen after seeing a result. No scenario is dropped. The published baseline is
not recomputed with different seeds. The research-window Sharpe is never presented as expected
forward performance.
