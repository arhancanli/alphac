# Execution realism and model boundary

This page describes what AlphaForge actually models as of 2026-08-18. It is an engineering
capability statement, not evidence of investment performance. The compatibility default remains
`NextOpenFill`; research that claims bar-liquidity realism must explicitly select
`ParticipationCappedFill` and publish that choice in its run config.

## Implemented and tested

| Risk | Current contract | Evidence boundary |
|---|---|---|
| Commissions and spreads | Venue/asset-aware fees and half-spread in one shared cost model | Unit-tested exact arithmetic |
| Nonlinear impact | Square-root impact with a 1% ADV build cap and hard 5% validity edge | Out-of-regime use fails loudly |
| Latency | Configured adverse price add-on | Placeholder until calibrated from paper fills |
| Partial fills | Optional next-bar participation cap, lot-flooring, explicit canceled residual | Missing/zero quote volume fails closed |
| Rejected/unfilled orders | Missing bars, missing cost inputs, missing liquidity and final-bar orders are counted and labeled; broker recovery ingests full or partial venue executions | No synthetic fallback fill |
| Holidays | Equity D1 execution follows exchange sessions | Weekend/holiday hopping is tested |
| Corporate actions | PIT split and cash-dividend replay, queued-order split rescaling, and metadata-confirmed delisting force-flat | No complex reorganizations, full historical coverage, dedicated delisting returns, or live broker path |
| Delistings | Point-in-time membership and metadata-confirmed conservative administrative force-flat | Dedicated delisting-return data remains a promotion requirement |
| Borrow and financing | General-collateral equity borrow and stored perp funding accrue; optional PIT locates, dynamic fees, recall buy-ins, cash credit, margin debit, and segregated short-sale-proceeds rates | No broad historical lending/rate coverage, multicurrency collateral, margin-call liquidation, broker reservation, restart persistence, auction replay or live broker path |
| Stale/missing data | Signal staleness holds, price collars, missing-bar drops and feed-quality checks | Historical venue-outage replay is not implemented |
| Market status/outages | Optional PIT OPEN/HALTED/OUTAGE/AUCTION_ONLY/CLOSE_ONLY replay blocks impossible fills in the event-driven engine | No historical status ingestion, auction-price model, smart routing or live status polling |
| Crowding and liquidation | Optional PIT ownership, short-interest, borrow-utilization and flow gate; ADV-haircut liquidation stress in shared pre-trade | No broad historical ownership/flow coverage, empirical unwind calibration or correlated-depth model |
| Operational controls | Pre-trade limits, reconciliation, risk-event storage, drawdown ladder and absorbing kill switch; three consecutive fill-outcome reconciliation failures persistently engage the kill and block submission | Live effectiveness still requires prospective paper evidence |
| Dated futures lifecycle | PIT contract metadata, session-counted first-notice/last-trade exits, immediate-next rolls, locked-limit classification and variation margin | Domain primitives only; no futures data, product calendar, cost schedule, backtest or broker path |
| Options lifecycle and surface integrity | PIT terms/quotes/official settlement/assignment notices; premium-currency-local static-arbitrage checks; single-underlying active surfaces; displayed bid/ask-bound strike monotonicity and convexity; ratio-preserving multi-leg IOC/FOK replay with homogeneous premium currency, side-specific displayed-size caps and net debit/credit limits; optional per-leg OPEN/HALTED/OUTAGE/AUCTION_ONLY/CLOSE_ONLY replay with proven reduce-only integrity; exact PIT side/liquidity/event-scoped fee revisions with declared rounding, minima, caps and rebates; complete-matrix internal scenario margin with cross-leg netting, locked model/input hashes, short floors and concentration add-ons; signed cash/physical expiry; source-bound adjusted baskets; immutable SHA-256 OCC memo archive; strict reviewed manifests and exact vendor reconciliation | Domain/data primitives only; no historical option-status corpus, complex-order auction model or live status polling/failover; internal margin is not broker/OCC/regulatory equivalent and excludes opening premium, margin calls and liquidation; no validated stress repricer/calibrated scenario corpus or verified historical fee corpus/production adapter; package replay assumes an atomic cross of independently displayed legs and has no fill probability, queue, price-improvement or beyond-size impact model; live OCC acquisition is Cloudflare-challenge-blocked; no historical fitted surface or reviewed adjustment corpus, parity/rate-dividend inputs, exercise model, backtest or broker path |

## Participation-capped fill semantics

For an order presented to a bar with open price `P`, observed quote volume `V`, lot size `L`, and
participation ceiling `p`, executable quantity is:

`min(order_qty, floor((p × V) / (P × L)) × L)`

The executed slice is priced by the same commission, spread, impact and latency model used by the
default fill. If the slice is smaller than the order, the engine records
`partial_fill_residual_canceled`; it does not silently assume the remainder traded. If quote volume
is absent/non-positive or the cap cannot support one valid minimum lot/notional, the engine records
`dropped_no_bar_liquidity` and executes nothing.

Residual cancellation is intentionally conservative and deterministic. Multi-bar child-order
scheduling, queue position and venue-specific rejection probabilities remain future work.

## Local engineering benchmark

The reproducible synthetic microbenchmark executes 100,000 fill-model calls per repeat across
seven repeats on the recorded CPython 3.12.13/arm64 Darwin runtime. In the 2026-08-17 snapshot,
median call time was 887 ns for the compatibility full-fill path and 2,004 ns for the
participation-capped path (2.26× the baseline). Deterministic checksums accompany every timing
sample.

These figures measure isolated Python fill-call overhead on one local machine. They are not
end-to-end backtest throughput, capacity, latency-to-market, or return evidence. The complete
machine-readable samples, workload, runtime metadata, guardrails and source hashes are published
at [`/glassbox/execution_models_benchmark.json`](/glassbox/execution_models_benchmark.json).

## Explicitly not implemented

- End-to-end securities lending: historical quote/locate/recall ingestion, broker reservations, restart persistence, buy-in auction replay, and live reconciliation.
- End-to-end financing: historical rate schedules, multicurrency cash/collateral, broker-specific haircuts and rehypothecation, margin calls/liquidation, and live reconciliation.
- End-to-end futures ingestion and trading: product calendars, dated quotes/settlements, fees and margin schedules, continuous-series attribution, broker routing, and historical limit/outage replay.
- End-to-end options ingestion and trading: historical fitted surfaces, put-call-parity inputs,
  operational unattended OCC acquisition (direct and headless-browser clients received a
  Cloudflare HTTP 403 managed challenge on 2026-08-18), automated PDF text extraction, reviewed
  historical adjustment coverage, a production vendor adapter, calibrated early-exercise/
  assignment modeling, quote repair, a verified historical fee corpus, broker-equivalent margin,
  validated scenario repricing, opening-premium collateral, margin calls/liquidation,
  complex-order-book execution, queue and
  beyond-displayed-size impact, historical option-status ingestion, complex-order auction
  execution, live outage polling/failover, backtest ledger, and broker reconciliation.
- Calibrated queue position, partial-fill continuation, auction imbalance/price formation, historical status ingestion, and live outage failover.
- Historical crowding coverage and calibration: point-in-time ownership/flows, cross-manager overlap, and correlated liquidation-depth feedback.

No sleeve may claim these risks are modeled merely because the platform has a generic cost or
staleness control. Candidates requiring one of these capabilities remain data- or engine-gated.
