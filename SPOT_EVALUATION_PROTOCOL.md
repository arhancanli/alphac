> Current correction: Alpaca crypto bars include quote midpoints, including at zero
> volume. The earlier positive-volume requirement and rejection of 307 bars were
> incorrect and are superseded by `evidence/spot-coverage/bar-semantics-correction.json`.
> Normalization now succeeds while explicitly preserving 457 unavailable quote
> observations across the full 984-day calendar. Execution-data readiness still fails.

# Spot candidate evaluation protocol — draft before return computation

No real strategy returns have been computed and no new trial identity has been
reserved. The implementation identity remains `alphaforge_spot_trend_v1`, in the
existing crypto trend family. This protocol must become a source-bound canonical
reservation with data manifest, complete runner and locked environment before use.

## Proposed data and observation window

- Alpaca `us` BTC/USD and ETH/USD spot feed. No perpetual candles, USDT conversion,
  Kraken substitution or equity symbol mapping.
- Proposed evaluation: 2024-01-01 through 2026-09-10 inclusive, with 200 completed
  UTC daily closes available before each decision. Fixed decision time 00:05 UTC.
- Construct UTC closes from complete hourly intervals, with an explicit bar-start
  to interval-end conversion. Verify all 24 hours per day; no forward filling.
  Fetch enough pre-window history to construct the first 200-day signal.
- At each fixed decision time, retrieve the latest quote known before the decision
  for each coin. Source age must satisfy the planner's one-second bound. Store
  bid, ask and displayed bid/ask quantity. Do not select a favorable quote after
  seeing the trading result. Missing or stale observations must be reported.
- Vendor history lacks original local receive timestamps. Any modeled receive
  delay must be declared in the reservation, with uncertainty separated from
  actual forward latency measurements. Never label simulated receipts as measured.
- Historical asset increments and tradability need effective-dated evidence.
  Current asset metadata alone cannot prove historical order acceptability.

The window is a proposed coverage target, not a selected profitable interval.
January 2023 sample quotes were empty; January 2024/2025/2026 samples exist for both
coins. These spot checks prove neither full coverage nor an earliest availability
date. Any window change must be documented before return computation.

## Evaluation engine

`src/alphaforge/validation/spot_evaluation.py` reuses the actual fixed signal and
decimal order planner. It marks holdings at bid and applies the generated IOC
limit prices. Modeled fills are capped at displayed side size and rounded to
quantity increments. Unfilled remainders are assumed canceled; actual paper
reconciliation must still verify that assumption against broker order state.

Buy fees deduct base units received; sell fees deduct USD proceeds. Economic fee
debits are immediate in the simulation, distinct from Alpaca's activity posting
schedule. Cash cannot become negative, positions cannot become short, and same-day
sale proceeds cannot fund planned buys. Daily returns compare consecutive
post-decision liquidation values and include execution costs.

The fixed cash reference earns zero interest. The 45/45/10 buy-and-hold reference
uses initial ask plus 10bps and a 25bps fee, then holds without rebalancing. It is
an analytical full-fill reference, not a liquidity-matched capacity comparison.
Its assumption is explicit in the result. No queue priority, book depth beyond
the observed touch, market impact or executable capacity is established.

The output is a modeled path, not an admission verdict. A completed evaluation
runner must reserve the identity, bind all imported source and inputs, account
for the trial in the canonical ledger, seal the daily path and compare net
performance, drawdown, turnover, costs and existing-book overlap under the active
admission policy. Statistical conclusions require the policy's full evidence;
unit tests cannot satisfy performance gates.

## Verified implementation checkpoint

Ten synthetic tests cover base/USD fee denomination, no-liquidity and partial
fills, future-mark isolation, missing days, decision-time drift, revised closes,
cash-only signals and liquidation without shorts. No real observations from the
data probes were passed to the evaluator.

The raw feasibility samples and request parameters are archived under
`evidence/spot-data-feasibility/`. Market-data requests used an existing credential
context only for read access; no trading account was repurposed and no orders were
sent. Dedicated AlphaForge paper credentials remain an activation requirement.

Sources: [Alpaca historical bars](https://docs.alpaca.markets/us/reference/cryptobars-1),
[historical quotes](https://docs.alpaca.markets/us/reference/cryptoquotes-1).

## Pre-result correction: blocked trading days remain in the path

The evaluator now distinguishes trading eligibility from portfolio valuation.
A quote older than one second or wider than the planner's limit blocks the
entire rebalance; existing holdings remain exposed and their gains/losses remain
in the daily path. Valid noncrossed bid/ask quotes up to one minute old may mark
that exposure, with quote age disclosed. Older or absent valuation quotes still
fail the evaluation instead of inventing a price. This valuation convention is
a modeling assumption, not a relaxation of the trading freshness requirement.
Two additional synthetic tests verify retained losses on a blocked rebalance and
rejection of unusable valuation data. No real returns informed this correction.

The complete hourly scan found four missing intraday hours per coin. Targeted
minute queries returned zero observations for all eight coin-hours. None is the
23:00 UTC interval used for a day's final close. The original 24-hour-completeness
requirement remains recorded above; a final manifest must explicitly distinguish
full-day OHLC coverage from availability of the close-only signal input. It must
not claim complete hourly coverage or silently fill the missing intervals.

## Close-input construction adopted before return computation

The normalizer now requires a positive-volume observed 23:00 UTC hourly bar for
every close in the signal window. It does not require all 24 intraday intervals
for this close-only strategy. This supersedes the earlier all-hours input rule,
while retaining the complete-hour audit and its gaps. Missing final-hour bars
are fatal; no preceding price is carried forward. This change follows the
mathematical input requirement of the existing close-only signal, not any
observed strategy result.

`spot_dataset.py` validates raw response hashes, the fixed quote query policy,
the complete date/symbol grid, exact decimals and original nanosecond source
times. Quotes lacking valuation data remain explicit nulls; they cannot silently
shorten the evaluation calendar. Current asset metadata is archived separately
and is not historical lineage. A normalized dataset still cannot authorize
return computation or paper activation.
