# When Crypto Carry Became Crash Exposure: The LABUSDT Incident

**Short title:** LABUSDT carry-crash incident  
**Author:** Arhan Canli, Founder, System Architect, and Quantitative Researcher, Canli Capital  
**Research system:** ALPHAC / AlphaForge  
**Status:** public incident research; not peer reviewed; not investment advice  
**Evidence date:** 2026-08-23  
**Machine evidence:** `/glassbox/crypto_lab_carry_crash_incident.json`

## Abstract

AlphaForge bought LABUSDT at a paper fill of 16.150421 USDT on 5 July 2026 while its
point-in-time funding signal was negative. It closed the same 114-token long at 0.155300 USDT on
30 July and opened a short at the same rebalance. The long lost 99.04% on price and produced a
net price loss of 1,824.37 USDT after its entry and close fees. Independent dated market records
show that LAB itself collapsed during July; the fill sequence is not evidence of a 100-for-one
symbol remapping or a paper-broker decimal error.

This distinction matters. Rejecting a real 99% move as “bad data” would erase the exact tail risk
that a perpetual-carry strategy is paid to bear. The correct response is to preserve the loss,
identify the strategy mechanism, and improve prospective attribution. The episode closed before
the flagship forward record began on 7 August, so it does not explain the current flagship loss.
The investigation instead exposed an observability defect: historical position snapshots retained
quantity and average entry but not each cycle's exact mark and unrealized profit or loss.

## Claim boundary

This is a forensic description of one paper-traded episode. It spends zero return hypotheses,
does not estimate Sharpe or expected maximum drawdown, does not authorize a parameter or weight
change, and does not rewrite any equity mark. The external sources corroborate market context;
the immutable local fill ledger is authoritative for AlphaForge's own execution claim.

## What happened

The frozen ledger contains three LABUSDT fills:

1. buy 114 LAB at 16.150421 USDT on 5 July 2026;
2. sell 114 LAB at 0.155300 USDT on 30 July, closing the long; and
3. sell 5,467 LAB at 0.155300 USDT, opening the new short.

The long episode's gross price P&L is

```text
114 × (0.155300 − 16.150421) = −1,823.44 USDT
```

Entry and close fees add 0.93 USDT, producing net price P&L of approximately −1,824.37 USDT.
This calculation excludes funding cashflows because the historical store did not retain an
instrument-level funding-payment ledger sufficient to reproduce that component independently.

## Why this was carry risk, not a broken symbol

Funding was negative when the long was selected. A negative rate means shorts pay longs, so the
frozen carry signal ranked LAB as a long candidate. During the holding interval, the funding
regime changed sign. The scheduled rebalance then closed the long and opened a short. That is the
intended direction of the signal; the failure was that the spot-price collapse overwhelmed the
carry payment before the next rebalance.

Independent market context is consistent with the local fills. A dated
[LABUSDT price history](https://chartexchange.com/symbol/crypto-labusdt/historical/) records the
collapse through July, while [Phemex's 13 July delisting notice](https://phemex.com/announcements/phemex-will-delist-labusdt694)
documents a contemporaneous venue response. Neither source proves AlphaForge's execution; the
signed local ledger does that. Together they reject the narrower hypothesis that 16.15 to 0.155
was merely a local decimal or contract-identity error.

## Why no jump filter is being added

A filter that refuses to mark a held position after a large price move would make reported equity
false. A filter that removes LAB only after observing this crash would also be an unregistered,
event-fitted strategy change. Neither is acceptable. The loss remains in the AlphaForge record,
and no live weight or signal parameter changes because of this incident.

The broader tail question remains legitimate: whether a pre-registered liquidity, age,
concentration, or crash-risk rule can improve expected portfolio Sharpe without merely deleting
the realized loser. That requires a new identity, frozen rule, complete historical replay,
multiple-testing charge, and forward transition—not an incident patch.

## Prospective observability correction

The investigation could reproduce aggregate sleeve equity and fills but could not allocate every
subsequent mark-to-market change by instrument. `positions_snapshots` stored quantity, average
entry, and opening timestamp only. Aggregate equity is insufficient to reconstruct historical
instrument marks, and those marks will not be invented.

The paper execution path now prospectively persists, for each open position and cycle:

- the exact order-book mid used in account equity;
- whether the mark came from the order book or the explicit entry-price fallback;
- marked market value; and
- unrealized P&L relative to average entry.

Legacy rows migrate additively and remain null for these fields. This improves future sleeve-risk
diagnosis without changing orders, signals, weights, historical marks, or the governing forward
Sharpe contract.

## Conclusion

LAB was a genuine adverse market event and an example of the left-tail exposure embedded in
crypto carry. The institutional response is not to delete the loss. It is to preserve it, state
what the evidence can and cannot reconstruct, and ensure future position-level losses are
independently attributable from the same marks used in account equity.
