> Update: the owner has selected the separate spot-only Alpaca restart. See [SPOT_RESTART.md](SPOT_RESTART.md) for the current implementation and remaining gates; any venue-choice blocker below describes the earlier checkpoint.

# AlphaForge repair and restart preparation

11 September 2026. Implemented on the isolated branch
`codex/alphaforge-prospective-pause`; not deployed.

## Record diagnosis and preservation

The old record is not a clean forward execution of the intended algorithm. Four
weekly rebalances failed because of cross-asset instrument lookup, and risk-state
restoration required prior repairs. Those are established defects. No new numerical
balance error was established by this phase, and a loss cannot be removed merely
because it occurred while the intended strategy was impaired.

`evidence/legacy-record-preservation.json` binds the existing frozen database, curves,
and performance analysis by hash. No source history was deleted, no broker account
was reset and no new epoch was started. A repaired version needs a separately dated
record; it must not be spliced onto the old curve as one unchanged experiment.

## Concrete additional repair

The funding monitor initialized `_funding_dry_cycles` to zero for every new process.
Under the hourly `--once` runtime, it therefore could not accumulate enough failures
to reach its critical threshold. Its purported held-position check actually examined
universe metadata, so a flat account could count as holding perpetuals.

The repair adds an append-only `funding_health` table to TradingStore and records one
idempotent observation per cycle. The count survives close/reopen and process-object
replacement. It is rebuilt from the durable latest observation when recording the
next cycle, without inventing past health records. Conflicting same-cycle observations
and out-of-order insertion fail. A SQLite write failure does not advance the count.

The loop now checks nonzero held perpetual positions, records an unavailable source,
and recognizes a valid zero-rate settlement for a held instrument. Events for unheld
instruments do not reset the counter. Critical alerts remain visible on subsequent
failed cycles after the threshold. Position membership is read once per successful
source batch rather than once per settlement.

This is a HEALTH monitor, not a funding settlement ledger or a return improvement.
It retains the existing aggregate 'any held instrument settled' semantics; it does not
prove complete settlement coverage for every held instrument. Cashflow persistence,
event-level settlement idempotency, missing-interval recovery and full cost attribution
remain separate concerns. Monitoring storage failures can fail a cycle through the
existing error path; that behavior needs operational review before deployment.

## Validation

The pre-change regression of signal scoping, loop recovery and crypto health passed
56 tests. The funding repair then passed 92 focused tests, including eight new cases:
restart persistence, flat accounts, zero-rate settlements, unheld events, source
failure, replay/ordering, additive upgrade and failed database writes.

Final combined regression: **114 passed in 4.60 seconds**. Receipt:
`evidence/repaired-baseline-final-tests.xml`.
Earlier receipts are retained. These tests used fixture brokers and temporary SQLite
files, not the production trading database. The full repository suite was not run.

## Alpaca restart blocker

The previous authenticated, GET-only paper asset probe returned 73 tradable spot
assets and zero perpetuals in that existing credential context. It did not create a
dedicated AlphaForge account. Spot cannot reproduce the present short-perpetual and
funding-carry mechanics. The user has been asked whether to design a new spot-only,
long-or-cash AlphaForge for Alpaca, or retain carry and verify a perpetuals venue.
That choice changes the strategy; it cannot be silently resolved by dropping shorts.

`config/alphaforge_restart_plan.json` records the blocked restart and its concrete
requirements. A dedicated paper account, compatible instrument semantics, validation,
reconciliation, clock verification and dated epoch disclosure precede activation.
No credentials should be pasted into chat or included in the evidence package.

The earlier prospective composite-removal proposal remains prepared but inactive;
its cash-versus-redistribution choice is also unresolved.

## Broader sleeve research

The current atlas already contains 40 families and 240 candidate cells. Those cells
are not 240 independent strategies. The 13-item current queue still has data, identity
or independent-label blockers; no new sleeve is admitted by this work.

`evidence/research-frontier-refresh.json` records three source-feasibility leads,
with overlap checks and kill conditions before any new return is opened:

- Leveraged-ETF rebalance pressure: need pre-decision fund-flow information, not just
  a mechanical leverage-times-return estimate. Federal Reserve studies disagree on
  impact once investor flows are included; that is a falsification requirement.
- Treasury-buyback liquidity: TreasuryDirect publishes operation announcements,
  results and schemas, but historical executable bond quotes, known-at eligibility,
  duration-hedge costs and overlap with auction-concession research remain unresolved.
- FX fixing inventory pressure: a relevant primary presentation was located by search
  but its direct PDF returned 404. This lead remains SOURCE_RETRIEVAL_INCOMPLETE;
  no return-effect claim is based on that unavailable paper.

Sources supporting the first two source screens:
https://www.federalreserve.gov/econres/feds/are-leveraged-and-inverse-etfs-the-new-portfolio-insurers.htm
https://www.federalreserve.gov/econres/feds/are-concerns-about-leveraged-etfs-overblown.htm
https://treasurydirect.gov/auctions/announcements-data-results/buy-backs/

The target is more economically distinct, validated return sources. None of these
leads is described as top-tier alpha before data, costs, selection-aware validation
and portfolio contribution are established. No new return hypotheses were tested.
