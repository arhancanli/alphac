# Point-in-time securities-borrow foundation

AlphaForge now has tested primitives for security-level borrow availability, locates, fees,
recalls, and forced-buy-in deadlines, plus optional event-driven integration for locate caps,
dynamic fees, and recall cover orders. This is engineering evidence, not historical borrow
coverage, return evidence, or a sleeve-admission result. No market returns were opened and no
research hypothesis was spent.

## What is enforced

- Borrow quotes carry observation, availability, and exact validity timestamps.
- Easy, hard, and unavailable states are explicit. An unavailable quote cannot report lendable
  quantity.
- Locates may be granted, quantity-capped, or denied; a grant cannot exceed requested or observed
  availability.
- The required locate covers only incremental short exposure after netting long inventory and
  existing shorts.
- Security-level fees accrue on ACT/365 only when one quote covers the entire interval.
- Recall notices are point-in-time and cover no more than the recalled quantity or remaining short.
- A missed cover deadline becomes an explicit forced-buy-in instruction. No execution price or fill
  is fabricated.

When a borrow provider is supplied to the event-driven backtester, incremental short orders are
denied or quantity-capped from the PIT locate, and open shorts accrue the security-level fee whose
quote covers the complete holding interval. With no provider, the existing general-collateral path
and golden master remain unchanged.

Known recalls become reduce-only next-bar cover orders. Conflicting strategy orders are
superseded, deadline breaches are labeled `forced_buy_in`, and an obligation is reduced only by
the quantity actually filled. Dropped or partial orders therefore retry on later bars.

## Deliberate boundary

The platform does not yet ingest a historical securities-lending feed, reserve broker locates,
model rebates/collateral, persist outstanding obligations across process restarts, allocate
partial recalls across strategies, simulate buy-in auctions, or route and reconcile live orders.
Existing general-collateral assumptions and current broker
`easy_to_borrow` flags are not historical evidence.

The machine-readable capability statement is published at
[`/glassbox/borrow_execution_contract.json`](/glassbox/borrow_execution_contract.json).
