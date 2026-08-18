# FINDING — the walk-forward engine cannot complete a long equity backtest, and it is not a data problem

**Measured 2026-08-07/08 across FOUR runs.** Recorded here because four attempts produced the same
failure and three different explanations from me, two of which were wrong.

## The failure

```
CostModelMisuse: sqrt impact law invalid: notional 132.0 exceeds 5% of ADV 434.0
                 (pre-trade checks should have rejected this at 1% of ADV)
```

Identical numbers every time:

| run | universe | lake | result |
|---|---|---|---|
| 1 | 8,017 pinned cohort | `data/lake` | crash at 2h07m |
| 2 | 6,724 PIT ∩ cohort | `data/lake` | crash |
| 3 | 6,724 PIT ∩ cohort | `data/lake_sharadar` | crash |
| 4 | 6,464 (+ $250k static liquidity floor) | `data/lake_sharadar` | crash |

**Identical numbers across three universes and two lakes.** That is the tell: a genuinely
data-dependent illiquid name would trip different numbers when the universe changes.

## Root cause

The engine caps per-order participation at 1% of the decision bar's **30-session rolling median**
dollar volume. When that cap floors below one lot it deliberately returns the order UNCLAMPED so
the cost model halts (`backtest/engine.py`, `# sub-lot cap: let the 5%-ADV tripwire halt loudly`).
The comment calls it a broken-guard tripwire, i.e. it assumes an upstream filter should have made
this impossible.

**No upstream filter can.** The condition is TRANSIENT. Measured over the pinned cohort, many
ordinary names pass through a 30-day median dollar volume near $434 at some point in 26 years —
BXMT (2000-09), AMRN (2003-09), ALBO, CARB, CBRI, CETX, CRMD, DIAL1 in the first sample alone. A
name with a $10M lifetime median can have a 30-day stretch at a few hundred dollars: halts,
delisting run-ups, crisis windows, post-reverse-split gaps.

So over 26 years and ~6,500 names, encountering at least one such window is not an edge case, it
is a certainty. **The engine halts the entire run on the first one.**

## What this invalidates

* **`PREREG_SLEEVE4_INVESTMENT.md` (AlphaLedger v1) cannot be executed.** Its evidence
  (21y Sharpe 0.83, NW t +3.19, rho -0.367 to AlphaMax) comes from an artifact dated 2026-06-21,
  and `backtest/engine.py` was rewritten 2026-08-04 for the live trading system. v1 ran against a
  different engine. Its numbers are not reproducible today and should not be quoted as if they were.
* **`PREREG_ALPHALEDGER_V2.md` cannot be executed either.** Its $250k floor is applied to a static
  full-history median while the engine checks a rolling 30-session median. Filtering the wrong
  statistic cannot prevent a transient condition. That document should be marked unexecutable
  rather than quietly amended — amending a floor after four failures to make a run pass is the
  behaviour its own "what would make this dishonest" section prohibits.

## The decision this needs, which is the owner's and not mine

The engine's behaviour is defensible as written: it refuses to price an order it cannot model. But
"halt the whole 26-year run" is a strange response to "one name was untradeable for one month in
2003". The realistic options:

1. **Drop the order, count it.** An order that cannot be clamped to one lot is skipped and recorded
   in a counter (`orders_adv_unfillable`), the same way non-shortable names are already handled.
   Honest, and the counter makes the frequency auditable. **Changes measured results for every
   sleeve**, so every published equity number would need re-deriving.
2. **Force-flat the position** at the last valid close, as delisting already does.
3. **Accept that long-history equity walk-forwards are not runnable** on this engine and stop
   quoting numbers that depend on them.

Option 1 is the most defensible, but it is a change to shared infrastructure that moves AlphaMax's
and AlphaTrend's numbers too. That is not a 1am decision.

## Correction to the record

I attributed this failure to the wrong cause three times before measuring it: first to the pinned
universe containing untradeable names, then to the wrong lake, then to a missing liquidity floor.
The lake diagnosis in particular was published in a memory file and a script docstring as though it
were established. It was not. Only the fourth investigation looked for the actual instrument, and
the answer was that there is no single instrument — which is what made the first three stories all
sound plausible and all be wrong.
