# Dated-futures execution foundation

**Capability status:** domain primitives only  
**Research effect:** zero market data opened, zero returns evaluated, zero hypotheses spent  
**Claim boundary:** architecture evidence, not sleeve-admission or performance evidence

AlphaForge can now represent a dated futures contract as a first-class `FUTURE` instrument and
make deterministic lifecycle decisions without using information unavailable at the decision
time. The current AlphaTrend implementation remains a managed-futures **ETF proxy**. Nothing in
this foundation relabels its evidence as direct futures evidence.

## Implemented contract

Each dated contract carries its canonical instrument identity, root, contract month, listing time,
metadata availability time, first-notice time, last-trade time, multiplier and tick size. Contract
metadata or liquidity stamped after a decision raises `LookaheadError`.

The roll policy is locked in exchange sessions rather than guessed calendar days:

1. Compute the first-notice exit session and last-trade exit session from the supplied session
   index.
2. Use the earlier deadline.
3. At or after that deadline, roll only to the immediate next listed expiry when its metadata is
   known and it remains safely before its own deadline.
4. If that immediate successor is missing or unsafe, flatten. Never skip the lineage gap by
   jumping farther down the curve.
5. Before the mandatory deadline, a liquidity-led roll requires the next contract to exceed the
   locked volume ratio for every required confirmation observation. Missing data means hold.

The execution guard separately identifies locked limit-up, locked limit-down and generic missing
liquidity from a point-in-time effective price band. Daily variation margin is an explicit signed
cashflow: `contracts × multiplier × (current settlement − prior settlement)`.

## Fail-closed integration boundary

The shared instrument taxonomy accepts dated futures, but the generic calendar and transaction
cost paths reject them. There is deliberately no fallback to NYSE sessions, 24/7 crypto time, or
Binance spot commissions. Product-specific sources must land before an end-to-end futures run can
be valid.

Still required:

- exchange/product calendars and settlement schedules;
- dated-contract settlements, executable quotes, volume and open interest with PIT lineage;
- exchange, clearing, initial-margin and maintenance-margin schedules;
- continuous-series construction with explicit roll-return attribution;
- backtest ledger and broker integration;
- historical limit-event and exchange-outage replay.

The machine-readable capability contract, source hashes, invariants and missing components are at
[`/glassbox/futures_execution_contract.json`](/glassbox/futures_execution_contract.json).
