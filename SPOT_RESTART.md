> Current correction: Alpaca crypto bars include quote midpoints, including at zero
> volume. The earlier positive-volume requirement and rejection of 307 bars were
> incorrect and are superseded by `evidence/spot-coverage/bar-semantics-correction.json`.
> Normalization now succeeds while explicitly preserving 457 unavailable quote
> observations across the full 984-day calendar. Execution-data readiness still fails.

# AlphaForge spot restart — implementation checkpoint, 2026-09-11

The owner selected a separate Alpaca spot, long-or-cash restart. The legacy
impaired record remains preserved under `evidence/legacy-record-preservation.json`.
There has been no account reset, production deployment, portfolio restatement,
order submission or new performance epoch. No superior performance is claimed.

## Frozen implementation candidate

`alphaforge_spot_trend_v1` is a transparent baseline for evaluation:

- Universe: BTC/USD and ETH/USD, requiring active, tradable crypto asset metadata.
- Signal: last completed UTC daily close strictly above the mean of exactly 200
  contiguous completed daily closes. Equal to or below the mean means cash.
- Allocation: 45% per active coin, leaving at least 10% cash before execution
  costs; inactive allocations remain cash. No shorting, borrowing or funding carry.
- Cadence: one reserved decision per UTC day; the first observed decision freezes
  the payload. A changed replay blocks rather than placing a new allocation.
- Execution: IOC limits, at most 10bps price displacement, maximum observed spread
  50bps, quantity rounded down to metadata increments, prices rounded toward the
  quote, maximum $200,000 requested limit notional per order. Unmarketable rounded
  limits and subminimum quantities are skipped. Dust remains held and disclosed.
- Buys use available cash above the 10% reserve and non-marginable buying power,
  reserving an additional 25bps. BTC is processed before ETH; constrained cash can
  therefore leave unequal allocations. Sell proceeds cannot finance this batch.
- Quote source age at most one second, ordered source/receipt/decision timestamps;
  account snapshot at most five seconds. These checks do not certify clock accuracy.
- Foreign/negative positions, malformed numbers, mismatched account binding,
  open orders, uncertain intents or an unreconciled account block the entire plan.

The numerical choices were fixed without opening new real return data. They are
engineering/research choices, not fitted optima. The family overlaps existing
crypto momentum/trend; changing venue does not create an independent sleeve.
This document is not a completed return-trial reservation or admission packet.
The canonical reservation validator must pass before historical return computation.

## Implemented and tested

`portfolio/spot_restart.py`: pure signal computation with completed-bar validation.

`execution/spot_plan.py`: pure decimal order planning. It does not reuse the equity
adapter's symbol mapping or zero-fee assumptions. Same-day client IDs bind strategy,
epoch, account, UTC day and symbol. IDs alone do not establish broker idempotency.

`execution/spot_intents.py`: SQLite FULL-sync journal, atomically binding an account
and epoch, reserving all daily intents, and preventing conflicting/reordered
decisions. A pending reservation blocks subsequent days, including after process
restart. Concurrent connections yield only one NEW result. Replayed reservations
never authorize retry. Terminal evidence is stored against the reserved payload.
Its authenticity and completeness remain the responsibility of a future broker
reconciler; arbitrary caller-supplied terminal evidence is not production clearance.

`execution/spot_rehearsal.py`: composes signal, planner and daily journal on injected
inputs, always returning `submission_authorized=false`. No broker transport exists
in this path. All new tests use synthetic data, without any performance evaluation.

Validation: 37 new spot tests plus 114 funding/live regression checks, **151 passed**.
Receipt: `evidence/spot-and-repair-tests.xml`. Covered cases include insufficient
cash, deferred sale proceeds, unavailable base quantity, invalid/stale prices,
metadata increments, repeated daily decisions, competing journal connections,
account mismatch, write failure rollback and immutable reconciliation evidence.

## Remaining work before paper activation

1. Dedicated credentials in `~/.config/alphaforge/alpaca_spot.env`; the existing
   sleeve accounts cannot be reused. Verify paper origin, actual account identity,
   crypto eligibility and no foreign positions/orders; persist an account binding.
2. Seal the data manifest, runner and environment and validate a canonical trial
   reservation. The isolated worktree has no `artifacts/research` evidence tree;
   read the current canonical artifacts before reserving, without fabricating them.
3. Evaluate the fixed rule on point-in-time data with conservative fees, spreads,
   turnover, drawdowns, comparison to cash and buy-and-hold, and book overlap.
   Any altered signal/allocation identity requires its own trial accounting.
4. Implement bounded paper-only transport and authenticated reconciliation of
   fills, open orders, IOC cancellations and fee activities. Crypto buy fees debit
   received base units; reported gross fills cannot be treated as net holdings.
   Reserve pending base fees before selling available quantity. Timeouts remain
   uncertain until broker reconciliation; never blindly retry a POST.
5. Verify clock and runtime readiness, initialize a separately dated paper ledger,
   and activate only after these gates pass. Paper is execution observation, not
   proof of achievable live returns.

The prospective legacy portfolio pause is separately prepared in
`evidence/pause-options.json`; the cash-versus-redistribution choice remains pending.
No negative history is removed retroactively. A fresh paper record is a new epoch.

## Sleeve discovery

The existing 40-family, 240-cell atlas remains the search scope. Current leads and
their data/identity gates are in `evidence/research-frontier-refresh.json`. None
has gained an admission from this engineering work. The next research actions are
source/data feasibility for leveraged ETF flows and Treasury buyback liquidity,
plus completing the source review for FX fixing pressure. Return testing remains
behind identity reservation and data lineage. Existing killed hypotheses stay killed.

## Venue sources consulted 2026-09-11

[Alpaca crypto spot documentation](https://docs.alpaca.markets/us/docs/crypto-trading)
documents fractional quantity/price increments, IOC limits, non-marginable buying
power, no short selling, crypto fees charged in received assets, and fee activities.
Its base tier lists 25bps taker fees; the planner reserves that amount conservatively.
Metadata and account eligibility must be verified again at activation.

## Read-only adapter and governance checkpoint

`execution/spot_paper.py` now provides bounded GET-only paper reads and strict
fresh-account and order-recovery validation. `scripts/preflight_alphaforge_spot.py`
uses only the dedicated spot credential file and never falls back to existing
sleeve credentials. The actual local probe found the file absent: zero requests
and zero orders. The adapter does not prove dedication from an empty exclusion
list, does not bind an epoch, and exposes no submission or cancellation operation.

Twenty-four new mocked-transport tests cover restrictive accounts, other-sleeve
bindings, malformed numeric fields, redirect rejection, timeout/no retry, response
size limits, credential origin, partial IOC cancellation and conflicting fills.
Combined validation: **175 passed**, receipt `evidence/spot-paper-and-repair-tests.xml`.

`evidence/spot-governance-preflight.json` records canonical read-only validation:
historical packet coverage passes with 228 retired legacy identities, and the one
existing forward identity has a complete packet. These checks are prerequisites;
they are not a full reservation and do not authorize new return computation.

Treasury buyback source feasibility advanced to retrieved schema and schedule,
with hashes in `evidence/treasury-buyback-source/manifest.json`. The current
schedule cannot prove historical publication times; no bond prices or strategy
returns were read. Historical vintages, executable quotes and mechanism overlap
remain gates before any return trial.

## Evaluation engine checkpoint

The deterministic evaluation engine is implemented and has 10 synthetic tests;
the combined regression suite now passes 185 tests. See
`SPOT_EVALUATION_PROTOCOL.md` for assumptions and remaining runner/data work.
Historical bars and quotes are accessible in sampled dates, with raw coverage
probes archived under `evidence/spot-data-feasibility`. No real strategy returns
were computed, no identity was reserved, and no historical coverage was inferred
from the limited samples.

## Full coverage collection started

`scripts/collect_spot_evaluation_coverage.py` collects a fixed 2024-01-01 through
2026-09-10 window, plus hourly-bar warmup, using only market-data GET requests.
The bounded collector saves exact request/response hashes and resumes cached
pages. The initial ten-page allowance proved insufficient because the API
returned approximately 167 hourly observations per page; after verified process
exit, the allowance was increased to 400 pages and 2700 requests. No date window,
quote-age threshold or strategy parameter changed.

Seven collector tests pass. Full collection is in progress; the eventual
`evidence/spot-coverage/coverage.json` is the coverage result, not this checkpoint.
The active tool session is recorded for resuming observation. Its live state must
be checked through the tool before concluding it has finished or restarting it.
No real strategy returns or admission result exist.

## Completed coverage audit: performance evaluation remains data-gated

The collector completed all 984 dates and exited successfully. Source quotes
satisfied the one-second freshness condition for both coins on only 7 dates.
381 dates lacked at least one quote in the preceding valuation minute; these
dates cannot be removed from the return sample. Of 2366 final-hour bars, 307
had zero volume. The normalizer rejected those bars instead of treating them
as observed traded closes. No normalized dataset or real strategy return path
was produced. Evidence: `evidence/spot-coverage/data-quality-decision.json`.

The current data feed and fixed-time sampling policy cannot support the proposed
evaluation as specified. Next work must establish a defensible signal/valuation
data source and observe actual quote delivery behavior, or revise the modeling
protocol explicitly before registration. The one-second execution check has not
been loosened, missing days have not been dropped, and source limitations are
not trading losses or profits. Historical asset metadata and original receive
timestamps remain unverified. Dedicated paper credentials remain absent.

The combined relevant regression suite now passes 200 tests, including the
zero-volume failure observed in the real data audit. This validates rejection
behavior, not strategy quality.

## Current order-book integration checkpoint

`execution/spot_book.py` validates full REST book snapshots, including ordered
unique levels, positive quantities, noncrossed best prices and timestamp order.
`PaperReader.read_books()` now uses a fixed Alpaca US market-data endpoint and
preserves decimal numbers. Planner freshness and account-routing verification
remain separate gates; parsing a book does not authorize submission.

Twelve REST quote samples and eight REST book samples were collected without
orders. Book timestamps were generally more recent in this short, non-simultaneous
sample. The host clock offset was not removed: some local ages are negative.
These observations cannot certify latency or account-specific venue suitability.
Evidence is in `current-quote-timing.json` and `current-book-timing.json` under
`evidence/spot-coverage`. No historical quotes were replaced with current books.

Seventy-four focused tests pass for bar semantics, book parsing, read integration
and the existing spot planner. No real strategy returns or new paper epoch exist.
