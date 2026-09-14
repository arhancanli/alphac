# Share-class relative value v1 — pre-return proposal

Status: one fixed proposed hypothesis; not formally registered or admitted.
The source and execution prerequisites below must be met before historical
returns are calculated. API/MCP product work remains deferred.

## Hypothesis and scope

Alphabet's public share-class price ratio may revert toward its recent level
within a trading day. This is a relative-value hypothesis with voting/liquidity
risk, not a conversion arbitrage or a claim that the ratio should equal one.
GOOG/GOOGL is the first feasibility pair because both have sampled direct-feed
quotes and explicit short-sale restriction state. This selection used data
coverage, not returns. One issuer cannot establish diversified sleeve capacity.
Berkshire's conversion mechanism is a separate hypothesis and is not pooled here.

At 10:00 America/New_York each regular session, compute
`x = log(mid_GOOGL / mid_GOOG)`. Standardize x using the mean and sample standard
deviation of the preceding 60 sessions' valid 10:00 observations, excluding the
current session. Require all 60 observations; missing or nonpositive dispersion
blocks the decision. For z >= 2, propose short GOOGL / long GOOG; for z <= -2,
reverse. Otherwise remain flat. Use equal integer share quantities based on the
reviewed economic rights. No threshold, sign, lookback or entry-time search.
This formula has not been evaluated on actual sample prices.

Submit no more than one opening pair per session, with a fixed 250 ms modeled
latency. Exit at 15:50 local time with the same latency. No profit target,
optimized stop, overnight roll or conversion assumption. Use the exchange
calendar, including early closes: sessions without the registered exit time
are ineligible before entry. Dividends and corporate actions require dated
handling even though the intended hold is intraday.

## Execution requirements

The sample establishes direct-feed quote access, not broker routing to Nasdaq.
Choose and document the executable routing model before registration. Never
substitute venue quotes for broker NBBO fills without evidence. Require known
trading state, known short-sale restrictions and dated broker-specific borrow
evidence on the actual short leg. For Alpaca ETB, preserve the contemporaneous
ETB status and applicable broker policy; a separate HTB locate request is not
the documented ETB workflow. For HTB, require an approved, unexpired,
quantity-bounded locate. Unknown SSR is not unrestricted; unrestricted SSR
is not borrow availability.

Quote age <= 1 second and pair receive skew <= 100 ms remain diagnostic filters,
not proven standing-book rules. Full replay must settle book continuity and
standing-quote treatment before adopting or changing these into execution rules.
Any change is recorded before returns, not selected using profitable outcomes.
At arrival, sweep the observed side within a precommitted size/participation
limit. No mid-price fills or duplicated liquidity across overlapping feeds.

Register gross allocation, margin limits, commission schedule, regulatory fees,
borrow rates and their day-count convention, collateral financing, locate costs,
and deterministic partial-leg/unwind handling before running returns. They remain
unresolved; neither zero costs nor instant paired fills are defaults. Denied
entry remains cash. Failed exits remain open obligations and visible failures,
not dropped observations. End-of-data unresolved positions block completion.

## Current evidence and limits

Databento status schemas exist on XNAS.ITCH and XNYS.PILLAR, not EQUS.MINI.
Full-day samples returned 8 and 10 records respectively. Joining as-of status
by instrument ID to the unchanged quote grid leaves 53 Alphabet clocks with
valid quotes, open trading and explicit unrestricted SSR on both legs. Berkshire
has 9 quote/open clocks but no explicit unrestricted SSR; its source field is
unknown. These counts do not prove continuous feed integrity or fill capacity.
`evidence/share-class-status/audit.json` retains the per-clock evidence.

The existing borrow engineering contract explicitly lacks historical lending
feed ingestion. The local filename search found engineering/backtest artifacts,
not a verified source of this sample's security-level locates and rates.
Alpaca's zero-fee ETB policy began October 1, 2025, after the sample; current flags
cannot establish August availability. Paper trading omits borrow fees and does
not constrain order fills by NBBO size. [Dated fee change](https://alpaca.markets/blog/zero-borrow-fees-on-short-selling-etb-stock-shares-alpaca-trading-api/),
[paper assumptions](https://docs.alpaca.markets/us/docs/paper-trading).

Borrow accounting now accepts quote-specific ACT/360 or ACT/365, including the
actual engine ledger path. Existing inputs retain ACT/365. This is continuous
accrual support, not full broker nightly rounding/valuation replication. The
change does not justify assigning a basis or rate without source evidence.
[Alpaca's documented HTB convention](https://docs.alpaca.markets/us/docs/margin-and-short-selling)
illustrates why a universal divisor is unsuitable; it is not an August ETB rate.

## Validation and admission

Fifty-seven borrow/engine/contract/golden-master tests pass. One optional real-lake
funding integration test is skipped because that lake is absent in this checkout.
New tests cover ACT/360 fractional days, invalid bases, and the engine charge ratio;
the latter caught and led to removal of a second hard-coded 365 divisor.
Changed Python files pass Ruff. Changes are isolated in the research worktree.

Historical sources, execution policy and lineage review must be complete before
formal trial reservation. Apply the canonical out-of-sample, costs, capacity,
DSR/PBO and portfolio-correlation gates unchanged. Report overlap with existing
reversal/statistical-arbitrage and lending research. Neither this proposal nor
the two legal cases count toward the 14-sleeve target. No return trial was run.

## September 11 prospective borrow checkpoint

Two GET-only requests to the existing general paper credential context returned
HTTP 200 for GOOG and GOOGL. Both responses explicitly report active, tradable,
marginable, shortable and `borrow_status="easy_to_borrow"`. The receipt is
`evidence/alphabet-prospective-borrow/observation-20260911.json`. No account was
repurposed; no orders or locate requests were made. The local host clock is not
calibrated, and asset responses have no source event timestamp. These are current
paper observations, not a historical lending dataset or execution clearance.

The previous blanket requirement for an explicit locate on every short leg was
too restrictive for Alpaca's documented ETB workflow. It is corrected above
before any return trial. HTB still requires an approved locate; a quote does not
reserve inventory. Current policy must never be backdated to August 2025.

[Alpaca's June 5 changelog](https://docs.alpaca.markets/us/changelog/2026-06-05-borrow-status-6b96a5a)
schedules removal of the legacy `easy_to_borrow` field on September 22, 2026.
The new observer uses `borrow_status`; missing or unrecognized values stay unknown.
[The current ETB/HTB guide](https://docs.alpaca.markets/us/docs/margin-and-short-selling)
distinguishes broker-established ETB locates from explicit HTB requests.

The practical next route is prospective timestamped observation on an explicitly
chosen execution account and verified quote feed. It still needs the 60-session
signal history, synchronized decision/arrival evidence, account permissions,
size/margin rules and a frozen cost/partial-fill policy before paper orders.
The original historical experiment remains incomplete. One observation is not
continuous monitoring; no scheduler was installed.
