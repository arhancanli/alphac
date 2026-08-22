# Stablecoin par dislocations: locked no-return feasibility protocol

**Short title:** Stablecoin par dislocations: feasibility

**Declared:** 2026-08-16  
**Return data:** prohibited  
**Hypotheses spent:** zero  
**Family trial account:** `stablecoin_dislocation`

## Question

Can an eligible institution reconstruct and execute USDC secondary-to-primary redemption with
point-in-time legal, operational, venue, chain, and banking fidelity sufficient to justify one later
return preregistration?

This stage may inspect schemas, timestamps, terms, account eligibility, fee schedules, venue and
chain status, market depth, transfer timing, mint/burn records, reserve disclosures, and missingness.
It may not calculate strategy P&L, Sharpe ratio, drawdown, return correlation, or optimize an entry
discount or holding period.

## Frozen identity

- Token: native issuer-supported USDC only; bridged, wrapped, algorithmic, and
  crypto-collateralized tokens are excluded.
- Mechanism: acquire USDC in an executable secondary USD market and redeem directly through the
  issuer. Exchange-to-exchange convergence without issuer redemption is a different family.
- Actor: the same named Canli Capital legal entity and accounts that would trade the strategy.
  Historical access cannot be inferred from another institution's eligibility.
- Unit of account: executable USD proceeds in the linked bank account, not a USDT or DAI quote.
- History: from the first date all required source states coexist through the current sealed cutoff,
  including March 2020, May and November 2022, March 2023, weekends, holidays, and venue outages.
- No direction, discount threshold, venue ranking, chain ranking, size, or holding rule is selected.

## Source hierarchy

1. Effective-dated Circle terms, account agreement, fee schedule, supported-chain state, and
   timestamped proof that the production legal entity is eligible and in good standing.
2. Circle API and bank records for prospective dry-run mint, transfer, redemption, rejection, delay,
   fee, and fiat-settlement evidence.
3. Kaiko or equivalent synchronized tick trades, order-book snapshots, venue status, and symbol
   lineage for eligible USD markets; raw vendor parts and revisions are hash-bound.
4. Official exchange public archives and APIs as independent trade and listing checks, never as a
   substitute for historical depth.
5. On-chain canonical-contract transfers, mint/burn events, fees, finality, congestion, reorgs, and
   issuer-supported chain status known at the time.
6. Effective-dated reserve disclosures and official notices, used as state variables only when their
   publication timestamps are reconstructable.

## Locked feasibility gates

Every gate must pass before a return protocol can be written:

1. The production legal entity has documented Circle Mint approval, direct redemption permission,
   linked-bank verification, applicable limits, and jurisdictional eligibility. Screenshots or
   another firm's status do not pass.
2. Historical terms, fees, minimums, bank cutoffs, holidays, supported chains, blocklisting policy,
   and conversion interruptions are effective-dated for every retained observation; coverage and
   changes are published.
3. At least three independent eligible USDC/USD venues have synchronized trades, best bid/ask,
   displayed size, sequence or snapshot time, fee tier, symbol status, and deposit/withdrawal status.
4. At least 99.5% of retained messages have unique venue, market, timestamp, side, price, size, and
   source identity; clock uncertainty is bounded and crossed/stale books fail closed.
5. Mandatory stress windows are complete: March 2020, May 2022, November 2022, March 2023, the ten
   largest observed USDC deviations, all known venue outages, and all issuer conversion pauses.
   Missing stress data cannot be replaced by calm-period coverage.
6. For each supported chain and venue path, deposits, withdrawals, confirmations, gas, congestion,
   reorg handling, address screening, and issuer support are point-in-time. Cross-chain bridges are
   prohibited.
7. Prospective dry runs complete the full secondary purchase-to-bank-fiat cycle on at least 60
   deterministic sessions, including 20 weekends or holidays and 10 stressed-liquidity sessions.
   Every rejection, manual review, delay, and fee is retained.
8. The execution simulator models taker/maker fees, book walking, nonlinear impact, queue uncertainty,
   partial and rejected fills, cancel latency, transfer fees, finality, withdrawal limits and halts,
   redemption minimums and fees, bank-wire timing, fiat availability, and trapped inventory.
9. Principal-loss scenarios cover issuer insolvency, reserve impairment, bank failure, venue default,
   frozen or blocklisted addresses, chain halt, smart-contract defect, cyberattack, legal restraint,
   and simultaneous loss of redemption and secondary liquidity. No re-peg is assumed.
10. Capacity is the minimum of executable book depth, venue and transfer limits, issuer redemption
    limits, bank limits, and a predeclared fraction of observed stressed liquidity—not reported ADV.
11. An overlap audit is specified against AlphaForge crypto carry, BTC/ETH stress, exchange credit,
    dollar funding, and banking stress. Crisis conditional correlation and co-expected-shortfall are
    mandatory; a low unconditional correlation cannot pass.
12. The data manifest, legal-state manifest, raw checksums, parser source hash, and audit result form
    one reproducible chain, and return data opened and return identities spent remain exactly zero.

## Decisions

- `PASS_TO_RETURN_PREREGISTRATION`: every gate passes and one production entity can execute the
  full cycle; this permits one separately sealed return identity and does not admit a sleeve.
- `DATA_GATED`: named institutional data, direct redemption approval, or prospective operational
  evidence is absent but could resolve the gate.
- `KILL_FEASIBILITY`: direct redemption is unavailable, stress books are irrecoverable, capacity is
  immaterial, or principal risk cannot be bounded honestly.
- `REJECT_GOVERNANCE`: return data were opened, terms were backfilled from current pages, stress
  windows were excluded after inspection, or token/venue/threshold choices changed post hoc.

## Current decision

`DATA_GATED`. Direct Circle Mint eligibility for the production entity is not evidenced, historical
effective-dated redemption and outage state is not sealed, synchronized historical L2 books are not
configured, and no prospective end-to-end redemption ledger exists. Binance trades and Coinbase
candles can support integrity checks but cannot satisfy these gates.

No Alpaca key is requested: Alpaca cannot prove issuer redemption access or historical multi-venue
depth. The first useful credentials are institutional Circle Mint access and a licensed synchronized
order-book dataset. Secrets belong only in environment variables or a managed secret store.

