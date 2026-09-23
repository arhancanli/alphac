# PRE-REGISTRATION DRAFT — AlphaForge v2: hedged funding carry (cash-and-carry)

**Status:** DRAFT. Not sealed, no identity reserved, no return computed. Author approval required
before the reservation (Arhan Canli). Written 2026-09-23 while the spot archive was being ingested.
**Family trial account:** `crypto_carry` (well under the single-family tripwire of 40).
**Batch:** two selectable identities (PBO is defined only for a batch of two or more), one
reservation each, sealed as one batch before the first return of either.

## Why a redesign, and what it may not claim

AlphaForge was suspended from the book on 2026-09-23. Its live record decomposes, for
2026-08-24..09-23, into funding received +$919, fees −$60, and price moves −$4,711 (net −$3,852):
the funding it exists to earn is real (about 37% a year on the ~$30k it deploys) and it is
swamped by the price legs, because its long and short books hold different coins. AXIOM's
decomposition (2026-08-11) says the same about the mechanism: the carry leg is positive in both
windows it measured, and the price leg flipped sign between them.

The redesign earns the funding without the price bet: for each selected coin it shorts the USDT
perpetual and holds the same coin on spot in equal notional, so the two price legs cancel up to
basis. This draft claims nothing about returns. Everything below is fixed before any is computed.

## Mechanism and locked direction

When a perpetual's funding rate is positive, shorts are paid by longs. Short perpetual plus long
spot of the same coin collects that payment with near-zero delta. The risks are basis moves
between spot and perpetual, funding turning negative, exchange and custody risk, and the margin
on the short leg. Direction is locked: the book only ever holds short-perpetual / long-spot
pairs; it never takes the opposite pair and never holds an unhedged leg.

## Data (point in time)

- Funding: `data/lake/funding`, Binance USDT-M, 777 perpetuals since 2020-01, joined on
  `available_at` (settlement plus publication lag), never on `ts_funding`.
- Perpetual prices: `data/lake/ohlcv` (existing, 1h).
- Spot prices: `data/lake_spot` (Binance public archive, 1h; rights recorded in
  `config/data_source_rights_policy.json`).
- Universe membership: a coin is eligible on a date only if both its perpetual and its spot have
  bars for the prior 30 days and its 30-day median daily perpetual quote volume is at least
  $20 million. Delisted coins stay in the history (the archive keeps them).

## The two identities

| identity | selection at each rebalance |
|---|---|
| **v2a, top-K** | the 10 eligible coins with the highest trailing 7-day mean funding rate, provided that mean exceeds the cost hurdle below |
| **v2b, threshold** | every eligible coin whose trailing 7-day mean funding, annualized, exceeds 15%, capped at 20 coins by that mean |

Common to both: equal notional per selected pair; rebalance every 168 hourly bars (weekly),
matching v1; a pair is closed at the next rebalance when its coin leaves the selection; no
position when nothing qualifies (cash earns nothing, disclosed).

**Cost hurdle (v2a):** trailing 7-day mean funding must exceed the round-trip cost of opening and
closing the pair spread over one week: (2 × perpetual taker 5 bp + 2 × spot taker 10 bp) / 21
eight-hour settlements.

## Capital, margin and costs

Each unit of capital is split half to spot and half to perpetual margin, so each pair is 0.5 short
perpetual against 0.5 long spot (1× on the perpetual leg). Costs: perpetual taker 5 bp, spot
taker 10 bp, half-spread and square-root impact from the existing cost model on both legs,
funding booked at each settlement on the perpetual leg only. Stressed scenarios (declared now):
costs ×2; funding lagged one extra settlement; a 5% adverse basis shock on entry.

## Evaluation window and walk-forward

2021-06-01 to 2026-06-01, the window v1 used, with the same 25 purged walk-forward legs
(6,048-bar train, 1,512-bar test). The factor has no fitted parameters, so the walk-forward
exists for comparability and the stitched out-of-sample path is effectively pure out-of-sample.
Disclosure: this window has been tested before by other identities in the family; every one of
them is in the complete-union deflation, and so are these two.

## Gates (the admission contract in force, v7)

Every applicable gate of `config/sleeve_admission_contract.json`: at least 756 out-of-sample
observations, net Sharpe ≥ 0.15, Newey-West t gates, batch PBO ≤ 0.20, capacity ≥ $500,000 at no
fewer than three capital points, stress gates, absolute beta ≤ 0.1, and the book gates (book
Sharpe delta lower 95% > 0, correlation to the existing book ≤ 0, drawdown). A pass re-admits
AlphaForge only through a declared live change that starts a new evidence epoch.

## Kill rules

- Any gate fails → KILL; the identity is closed, not re-tuned.
- Out-of-sample basis loss exceeding 25% of cumulative funding received → KILL (the hedge failed).
- Any selection, universe, cost, timing or sizing change after the seal is a new identity.

## Open questions for the author (must be answered before the seal)

1. The $20M liquidity floor and the 15% threshold: accept, or set other values now?
2. Top-K = 10 and the 20-coin cap: accept, or set other values now?
3. Spot is held outright (no spot margin or borrowing). Accept?
4. The shared 2021-06..2026-06 window, disclosed as re-tested. Accept, or hold out 2025-06..2026-06
   as an untouched confirmation period?
