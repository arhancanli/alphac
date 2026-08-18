# Corporate-action and delisting lifecycle replay

AlphaForge now replays point-in-time splits, cash dividends, and metadata-confirmed delistings
inside the event-driven backtester. This is engineering evidence, not a claim of complete
historical coverage or investment performance. No return data was opened and no research
hypothesis was spent.

## Enforced behavior

- Every split and cash dividend retains its ex date and source availability timestamp.
- An event published after its ex boundary fails closed; the engine will not rewrite an earlier
  holding with information that was unavailable then.
- Splits convert held shares, average entry prices, and pre-ex queued quantities before the ex-date
  fill. A price-discontinuity guard rejects inconsistent split records.
- Cash dividends accrue against the signed position entering the ex date: longs receive and shorts
  pay. The current schema lacks a payable date, so this is explicitly booked as an ex-date
  receivable or payable.
- Applied transformations and cashflows persist in `corporate_actions.parquet` with each backtest.
- A terminal price history is liquidated only when SCD2 instrument metadata supplies a qualifying
  `delisted_ts`. If metadata still says active, the run halts instead of inventing an exit.

## Defects closed

The prior engine ignored dividend rows already present in the point-in-time lake. It also treated
any terminal price history as a delisting and sold at the last close, even when lifecycle metadata
said the instrument was active. Finally, a split converted an existing position but did not rescale
a pre-ex order when the book was flat, allowing a reverse split to multiply intended exposure.
Focused regressions now pin all three cases.

## Deliberate boundary

The platform does not yet model payable-date settlement, withholding tax, fractional-share
cash-in-lieu, mergers, tender consideration, spin-offs, rights, symbol changes, bankruptcy
recoveries, delisting auctions, vendor correction histories, or live broker reconciliation.
Complex same-boundary split/dividend combinations fail closed when the holding is exposed because
the current lake does not encode deliverable-basis ordering.

The machine-readable contract is available at
[`/glassbox/corporate_action_contract.json`](/glassbox/corporate_action_contract.json).
