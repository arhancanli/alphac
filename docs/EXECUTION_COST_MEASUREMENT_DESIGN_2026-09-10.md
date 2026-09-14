# Prospective execution-cost measurement

Status: OFFLINE DESIGN AND PROTOTYPE TESTED; NOT CONNECTED TO TRADING.
Owner approval covers design and fixture testing only. No broker calls, historical
benchmark backfill, production database migration, scheduler changes or publication
were performed in this phase. These measurements do not establish improved Sharpe.

## Findings on the actual code path

- The three equity/ETF sleeves share `scripts/live_cycle.py`. Its `_delta_orders`
  receives the sizing mid but stores the buffered limit as `OrderRequest.decision_price`
  for limit orders. A controlled buy at mid 100 produces 100.75 in this field.
  Neither it nor the persisted `orders.price` is an independent midpoint benchmark.
- The sizing loop obtains `order_book` once per instrument and can fall back to
  `last_trade`. The cycle identifier timestamp precedes individual quote retrievals;
  it cannot stand in for when each price became known. Target artifact/model time,
  sizing/decision time and submission time must remain distinct.
- `AlpacaBroker.order_book` preserves the source quote timestamp but does not persist
  feed identity, raw quote provenance or receipt time. The request does not explicitly
  select a feed. Comments calling it NBBO are not proof of the effective entitlement
  or coverage. `last_trade` returns only a float, losing its source timestamp.
- `_reconcile_fills` stores cumulative order quantities and average prices using
  `INSERT OR REPLACE`, including canceled/expired outcomes. Its timestamp may be an
  update timestamp, not a fill timestamp. There is no per-fill activity identity.
  Repeated cumulative quantities 4, 4, 6 describe six filled units, not fourteen.
- Read-only `PRAGMA table_info(fills)` on `var/trading_equity.sqlite` confirms no
  decision reference, quote provenance or fee column. No holdings were extracted.
- `AlpacaBroker.fetch_order` supplies a hardcoded zero `fee_quote`; this is not
  separately evidenced complete fees. It must not be imported into cost reporting
  as proof of a zero total charge. No broker fee policy was verified externally here.

Source locations: `scripts/live_cycle.py` functions `_delta_orders`, `_audit_order`,
`_reconcile_fills` and the pricing/submission loops; `src/alphaforge/execution/alpaca_broker.py`
functions `order_book`, `last_trade`, `fetch_order` and `closed_orders`.

## Proposed capture contract

| Capture point | Preserve prospectively | Boundary |
| --- | --- | --- |
| Target selection | Profile, execution basis, configuration/epoch hash, target artifact hash and target timestamp | Model intent is not a current executable quote |
| Per-instrument sizing, before limit padding | Actual decision time, sizing price and kind, instrument/currency, bid/ask and sizes or last trade, source time, local receipt time, verified feed, source payload hash and quality flags | Original benchmark is immutable; never infer it by dividing a rounded limit by its buffer |
| Immediately before each submission attempt | Client order identity, attempt identity, local submission time, separate arrival quote and its full provenance, actual order parameters | Arrival is a pre-submit local market reference, not the broker acknowledgment or guaranteed venue-arrival time |
| Acknowledgment/error | Receipt time, accepted/rejected/transport-unknown status, broker identity where returned | Transport timeout is not proof the broker rejected the order; recovery uses the same order identity |
| Broker outcome observation | Retrieval time, original submitted/filled/updated times separately, requested and cumulative filled quantity, average price, status, source/payload hash | Keep snapshots immutable; do not pretend aggregate observations are individual fills |
| Fee/activity observation | Activity identity, amount, currency, charge/rebate sign, observation time, source, attribution and completeness status | Unknown, unavailable and partial fees remain null/incomplete, never inferred zero |

Instrument/currency, profile, configuration epoch and paper/funded basis are join
boundaries. Keep close/open flip legs separate. No account identifiers, API keys or
unredacted credential-bearing responses belong in public evidence. Raw payload
retention and licensing must be reviewed before any export.

Reference quality requires finite positive prices, correct identities, known feed,
valid two-sided quotes when a midpoint is claimed, ordered source/receipt/event
timestamps and an explicitly approved age policy. Stale, crossed, missing or unknown
quotes do not become usable merely because an order filled. The offline prototype
accepts already-extracted benchmark evidence; raw quote parsing/authenticity and
crossed-book detection are still adapter work, not certified by its tests.

## Measurement rules implemented in the offline prototype

For executed quantity q, cumulative average execution price P and independent
reference R, let s = +1 for a buy and -1 for a sell:

`price_cost = s * q * (P - R)`

`slippage_bps = 10000 * price_cost / (q * R)`

Positive is adverse; negative is favorable. Decision and arrival slippage use their
own denominators and must not be added together. Decision all-in cost adds complete,
attributed same-currency fees divided by decision-reference executed notional.
Documented zero fees are allowed; missing fees are not zero. Negative explicitly
attributed fees are rebates. No FX conversion or assumed fee schedule is applied.

Unfilled quantity and fill fraction are reported even when cost is unmeasurable.
Zero fills produce null execution costs. Filled-quantity price cost is NOT full
implementation shortfall: opportunity cost of nonfills, delay decomposition and
portfolio-level impact remain unmeasured. Do not label the prototype as measuring
those effects or as a composite turnover/slippage series.

No portfolio aggregation is implemented. Before one is authorized, define the
reconciliation window, latest valid cumulative observation per order, open/missing
outcome counts, corrections, benchmark coverage and both count/notional denominators.
Publish exclusions with reasons; never average only conveniently measurable fills
and call that the cost of the whole book. Separate paper, funded, feed and epoch strata.

## Prototype and tests

`scripts/prototypes/execution_cost_measurement.py` has no network client, operational
database path or runtime import. Its pure measurement function requires an explicit
freshness policy. A small draft SQLite journal uses a caller-supplied fixture
connection, scoped identities, canonical JSON, SHA-256 payload checks and conflict
rejection. Exact repeats are idempotent; changed evidence requires a new event id.
Transactions remain caller-owned. This is application-level immutability, not a
signed chain or protection against an administrator changing the database.

Tests use disposable SQLite files and block socket connections. They exercise the
actual order builder and reconciliation function against a fake broker; they never
invoke trading `main()` against a real broker. The journal is not wired into that path.

Final verification: **54 prototype tests; 106 tests including existing execution,
zero-crossing and broker regression tests passed in 0.48 seconds.** Cases cover both
sides, favorable/adverse costs, separate references, null and complete fees, rebates,
currency mismatch, chronology, stale/unknown benchmarks, invalid inputs, partial and
unfilled orders, cumulative snapshots, scoped idempotence, conflict rejection,
persistence and rollback. The full engine suite was not run.

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest -o addopts= -q \
  -p no:cacheprovider tests/unit/test_execution_cost_prototype.py \
  tests/unit/test_live_cycle_execution.py \
  tests/unit/test_live_cycle_flip_zero_crossing.py \
  tests/unit/test_alpaca_broker.py
```

Before/after source hashes matched:

- `scripts/live_cycle.py`: `de86cc2347bce101cd96774bf24e519fb35c3bd8b12dcfd1f7aef52063af2288`
- `src/alphaforge/execution/alpaca_broker.py`: `224dd29e704d67b661c7d62d3a9a43b7faa9f5b9e7a8c9f1abd11532022837ee`

## Next implementation phase — separate approval required

1. Build adapters and a versioned sidecar writer in an isolated copy of the running
   path. Do not change order prices, quantities, risk gates, schedules or existing
   broker submission semantics. Keep original timestamps and IDs intact.
2. Prove effective quote feed/permissions and freeze measurement freshness policy
   before viewing measured costs. Budget any extra pre-submit reads and latency.
   Added calls can change timing even without changing orders: do not call this
   behavior-neutral without replay and timing evidence.
3. Freeze decision evidence before submitting; store attempt/ack/outcome events
   separately with reference bindings. Define deterministic snapshot identities,
   correction lineage and restart recovery. The current submission-time cursor on
   closed orders is not proof that late-closing older orders are fully covered;
   outcome completeness needs its own adapter tests before reporting totals.
4. Test database failure, missing quotes, timeout-after-acceptance, late fees,
   replacements, pagination, replay and crashes on the instrumented full path.
   Decide explicitly whether a pre-submit evidence-write failure blocks submission
   or permits an unmeasured order. That decision changes operations and is not made
   by this prototype. A post-submit write failure must never trigger blind resubmission.
5. Prepare an additive, versioned sidecar migration and backup/restore rehearsal on
   copied databases. Refuse unknown schemas. Existing history remains untouched and
   unmeasurable; never recreate missing benchmarks from later data.
6. Seek runtime activation approval separately after reviewing failure semantics,
   latency, costs and privacy. Rollback disables only the new instrumentation hooks
   while preserving accumulated evidence and existing broker idempotency; no drops,
   rewrites, order retries or historical fill deletions as cleanup.

Only after prospective capture and completeness are verified should a further phase
publish cost evidence or use it to evaluate strategy changes. Independent reviewer
coordination and new sleeve trials remain separate approval gates.
