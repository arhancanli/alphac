# AlphaForge restart: current requirements audit

This is a current-state checkpoint, not activation clearance. The selected
strategy remains a separate spot long-or-cash candidate; profitability and
independence from existing crypto trend mechanisms are unproven.

| Requirement | Evidence and actual state | Remaining work |
| --- | --- | --- |
| Preserve legacy record | `evidence/legacy-record-preservation.json`; separate worktree and candidate identity | Verify the manifest again before creating the new epoch; never splice histories |
| Spot strategy and planning | `spot_restart.py`, `spot_plan.py`; synthetic tests pass | Connect the tested components to a complete runtime |
| Historical input semantics | Corrected Alpaca bar semantics; all 984 dates retained in `normalized.json` | Historical metadata and original receive timestamps remain unknown |
| Executable historical evaluation | One-minute quote window leaves 457 unavailable observations | Establish a defensible execution/valuation observation policy and dataset before computing returns |
| Trial registration | Canonical preliminary governance checks passed | Full runner, sealed inputs/environment, canonical reservation and trial accounting still incomplete |
| Account identity and permissions | Dedicated `alpaca_spot.env` remains absent | Configure a dedicated paper account; verify actual account/venue routing and exclude other sleeve accounts |
| Submission and recovery | Durable daily intent reservations, read-only paper adapter, strict full-book parser | Implement and test the submission coordinator; uncertain requests must remain reserved |
| Settlement | `spot_settlement.py` verifies supplied terminal orders, fill quantities, received-asset fees and exact cash/position conservation | Verify the bounded activity reader against the dedicated account; consistent account snapshots and journal integration remain |
| Clock and execution readiness | Local quote/book timing samples include negative source ages; no clock calibration pass | Resolve host clock offset and verify calibrated runtime timing |
| New paper epoch | Not created; no orders sent | Create and start only after account, data, execution and readiness gates pass |
| Broader sleeve discovery | Existing atlas and feasibility queue preserved; Treasury sources and FX-fixing primary summaries retrieved | Data, execution, independence, trial and admission gates remain; no new qualified sleeve yet |

## Latest findings

An extended one-hour lookback recovered a preceding quote for all twelve
deterministically sampled one-minute query misses. Ages ranged approximately
63–186 seconds. This distinguishes a narrow query-window miss from an absence
of historical quotes. It does not make those observations fresh, establish that
the quoted liquidity persisted, or change the declared trading policy.
Evidence: `evidence/spot-coverage/extended-lookback-diagnostic.json`.

The settlement kernel requires exact supplied balance conservation and evidence
of fees in the received asset, capped at the fixed 25bps assumption. It refuses
open/uncertain orders, missing fee evidence, duplicate activities and unexplained
account changes. It neither authenticates the supplied records nor marks a journal
terminal. Its caller must prove complete broker data and account binding first.
The current focused settlement/reader/journal suite passes 44 tests.

## Next implementation sequence

1. Connect the implemented activity reader/converter and settlement kernel to
   consistent account snapshots, and complete order-submission coordination
   around the durable intent journal, with paper-only origins and no blind retry.
2. Establish a source-faithful historical protocol, or explicitly separate a
   diagnostic research model from a venue-execution validation. Register any
   return computation before running it; do not present a proxy as executable P&L.
3. With dedicated credentials and corrected timing, verify the complete runtime
   against the actual paper account before activating its separately dated epoch.

There is no claim that this checkpoint completes the user's goal. Passing tests
of isolated components does not prove the integrated runtime or investment quality.

## Activity ingestion implementation checkpoint

`PaperReader.read_activities()` now retrieves all activity types within a fixed
UTC creation-time interval of at most seven days. It checks the expected account
binding before and after the scan, uses the last activity ID as the next token,
and continues to an empty page even after a short page. It limits scans to 2000
records, 21 pages and 45 seconds; duplicates or incomplete traversal return no
partial success. Exhaustion does not prove that delayed fee posting has finished.

`spot_activities.py` converts known BTC/USD and ETH/USD gross fills and received-asset
fee debits. It preserves exact decimals and rejects unknown flows, ambiguous fee
denominations, credits/corrections, pending fees and unsupported symbols. It does
not silently discard deposits or withdrawals. The full relevant regression suite
passes 241 tests. These are mocked/synthetic validations; the dedicated account
has not been contacted because its credentials remain absent.

Source: [Alpaca activity API](https://docs.alpaca.markets/us/reference/getaccountactivities-2).
Creation-time filtering is distinct from settlement dates, including fees posted
on a later day. This is why a single trade-date query is insufficient.

## Durable submission-attempt checkpoint

The intent journal now stores a `submission_attempts` row before any future
network transmission. Atomic claims bind the exact reserved order; competing
connections cannot obtain a second claim. A process crash before or after the
request leaves the attempt uncertain and never permits blind resubmission.
An unacknowledged attempt blocks further claims in pending decisions.

First broker acknowledgements are validated against the reserved intent, stored
with an allowlist of fields, and immutable. Unknown statuses and mismatched
quantities do not clear uncertainty. An acknowledgement never marks the daily
decision terminal. No HTTP order submission is connected to these methods yet;
claiming an attempt is not account/data/clock readiness clearance.

Sixty-seven focused journal/planner/reader tests pass, including competing
connections, restart persistence, failed SQL writes, changed intents, and
immutable acknowledgements. The next step is the submission coordinator and
transport behind verified runtime activation, followed by complete settlement
integration. Dedicated paper credentials and the data/clock gates remain open.

## Paper-only submission transport implemented, activation disabled

`spot_submit.py` now connects durable claims to a fixed paper `/v2/orders`
endpoint. It is disabled by default and requires an application readiness
provider. No production provider is installed. The provider is a trusted
application boundary: this transport does not independently certify historical
data, source bindings, account routing or clock calibration.

Before claiming, the transport checks the journal's account/epoch binding,
re-reads the authenticated account, validates cash or available sell quantity,
then runs readiness immediately before the claim. Exact IOC limit payloads and
the $200k order cap are enforced. A maximum five-second deadline uses both wall
and monotonic time, and a greater-than-10ms discontinuity blocks preparation.
The deadline is checked again after the durable claim.

Only one POST attempt is made. Redirects, HTTP rejections, malformed responses,
timeouts and cancellation never permit blind resend or clear the journal. The
first valid acknowledgement is immutable and still not settlement. Position
exits can proceed with zero buying power if available long quantity covers them.

All submission tests used MockTransport; no real orders were submitted. The
combined relevant regression suite passes 260 tests. Remaining integration is
the verified readiness provider, consistent account/baseline snapshots and
authenticated settlement-to-journal coordination. Dedicated credentials, clock
calibration, a defensible research protocol and activation remain unresolved.

## Account-to-settlement integration checkpoint

`spot_account.py` requires two matching cash, position, availability and buying-
power observations with no open orders. Changing mark-to-market equity alone
does not fail the comparison. Repeated REST observations are not an atomic
broker lock, and the implementation does not claim otherwise.

The journal now seals a decision baseline before any submission attempt.
Baselines are immutable and bound to the journal's account. The paper submitter
requires that baseline. `spot_reconcile.py` joins the observed account, reserved
orders, complete activity scan, conversion and conservation checks, then records
terminal evidence only on success. Missing fees or changed balances stay pending.
A repeat settlement call returns the already-recorded status without new requests.

A new baseline must numerically match the prior settlement's ending cash and
positions. Decimal formatting differences do not count as account changes; real
late corrections cannot be hidden by resetting the baseline. Pending decisions
with unattempted orders still require a separate abandonment path.

The combined regression suite passes 267 tests, including mocked reader-to-
settlement-to-journal integration. No dedicated account integration or real order
submission occurred. Remaining work includes runtime readiness, handling partly
unsubmitted batches, the complete driver and the unresolved account/data/clock
requirements. No research returns or sleeve admissions have been produced.

## Interrupted batch recovery checkpoint

Reconciliation now durably stops further submissions before reading broker
state. The stop and attempted-ID snapshot share an immediate SQLite transaction,
so another journal connection cannot claim an unsent order after the stop.
Already claimed requests may still be in flight and must reconcile through actual
broker records; missing records never become synthetic rejections.

Only attempted orders enter fill/fee conservation. Unattempted IDs remain reserved
and are recorded as abandoned in terminal evidence. An entirely unsent batch
requires an exhausted empty activity scan and unchanged cash/positions. Any
reconciliation failure leaves the decision pending and submissions stopped; the
read-only reconciliation can be retried. Legacy records remain preserved.

Validation: 241 spot and live loop/store/funding tests plus 31 existing health,
funding-source and signal-service tests passed (272 total). The five added cases
cover partly submitted recovery, durable cross-connection stops, unchanged and
changed unsent balances, and failed reconciliation retaining uncertainty. Ruff
checks passed. No real broker orders, deployment, performance claims or sleeve
admissions. Runtime readiness and the complete driver remain unfinished;
dedicated credentials, clock calibration and research data gates remain.

## One-shot dispatch integration checkpoint

`spot_driver.dispatch_decision` now connects an already reserved decision to
sealed baseline capture and sequential paper submission. A durable dispatch start
excludes replacement drivers after process loss. The batch shares one deadline
and wall/monotonic continuity check, including bounded baseline acquisition.
Acknowledgements do not settle decisions. An uncertain response stops the batch.
Every normal, exceptional or cancellation exit stops further submissions; a hard
kill retains the durable start and any pre-I/O attempt claims for recovery.

Tests connect the real driver, submitter, journal and reconciler through mocked
HTTP: complete dispatch, lost response, cancellation, absent broker record,
disabled operation, process reopening and slow baseline acquisition. An absent
broker record remains pending rather than being treated as a rejection. The
instantaneous driver tests inject an empty activity receipt; authenticated
activity pagination remains covered by its separate existing integration tests.
All 279 relevant regression tests pass; Ruff and whitespace checks pass.

This is a dispatch component, not a complete installed trading service. The
source-bound runtime readiness provider, fresh market-data/planning integration,
scheduler and operator recovery interface remain unfinished. A crash before
baseline sealing requires explicit recovery; no historical balance is fabricated.
Dedicated spot credentials are still absent. No production activation, real
orders, return computations or new sleeve admissions occurred.

## Broker-input preparation checkpoint

`spot_prepare.prepare_daily_decision` collects repeated account observations,
current asset metadata and full REST books, computes the spot plan, reserves
the UTC day and seals the observed cash/position baseline. Existing daily
decisions return replay status without network requests or replanning. Pending
earlier decisions block preparation. Account changes, stale books, missing
metadata, clock discontinuities and UTC-day transitions block reservation.

The decision time is conservatively rounded upward to milliseconds, as is book
receipt time, so sub-millisecond processing does not falsely place receipt after
decision. This does not certify clock accuracy. Cash-only decisions now retain
baselines; continuity checks reject unanchored older terminal decisions and
unexplained changes following a cash-only day. Reservation and baseline sealing
are separate durable writes: interruption between them remains an explicit
recovery requirement, not automatic permission to trade.

The 284-test combined regression suite passes. New preparation tests use mocked
HTTP with the actual reader and planner. Ruff checks pass. Daily history remains
caller-supplied with source verification explicitly false. Research admission,
account dedication, clock clearance, source-bound readiness, scheduler and the
operator recovery interface remain outstanding. No dedicated account was
connected, no real orders were sent, and no new performance was computed.

## FX fixing research checkpoint

A targeted review of the retrieved 2021 working paper's data and cost sections
changed the FX lead's next action: executable venue costs and historical timing
are prerequisites before any return trial. The publisher PDF is locally hashed;
`FX_FIXING_FEASIBILITY.md` records the source evidence, ECB timing discrepancy,
failed LSEG methodology retrieval, and remaining published-paper/appendix review.
The research frontier now reflects the stronger gate and expanded overlap review.
No strategy returns were computed, no canonical trial was reserved, and no new
sleeves were admitted. This turn changed research evidence only; the last code
regression result remains 284 passing tests. The paper restart remains inactive.

## Atomic daily preparation checkpoint

Daily preparation now calls `reserve(..., baseline=...)`, which validates and
seals the baseline inside the same immediate SQLite transaction as the decision
and client-order identities. Failed validation or a failed baseline write rolls
back all three. This supersedes the separate-write limitation described above
for new decisions produced by `spot_prepare`. Existing legacy callers may still
reserve without a baseline; they do not gain automatic execution clearance.

The full relevant regression suite passes 288 tests. New checks cover cash-only
and order-bearing write failures, immutable replay after reopening, and abrupt
subprocess exit after baseline insertion but before commit. The crash test
reopened the journal and confirmed that no partial decision, order identity or
baseline survived. Ruff and whitespace checks pass. No real network requests or
orders were needed for these tests; production remains inactive.

Account/data/clock readiness, the verified history source, installed runtime
service and operator recovery remain outstanding. Research candidates retain
their evidence gates; no new sleeve was admitted or performance computed.

## Operator interface checkpoint

Added `scripts/operate_alphaforge_spot.py` with local read-only status and explicit
GET-only broker recovery. `SPOT_OPERATIONS.md` documents commands and recovery
semantics. Status identifies durable attempts, missing baselines and stopped
batches without credentials. Recovery checks the supplied account/epoch against
the journal before loading dedicated credentials and invokes the existing
reconciler; it cannot submit orders.

294 combined regression tests pass, including read-only status, missing/foreign
database rejection, and binding checks before credential access. CLI help was
checked. Real dedicated-account recovery remains untested because the account
is not configured; the reconciler's broker paths retain mocked integration
coverage. No activation, performance computation or new sleeve admission.

## Authenticated daily history checkpoint

`spot_history.collect_daily_history` now retrieves the last 200 completed daily
closes through the bounded Alpaca reader, using observed final UTC hourly bars.
It rejects duplicates, out-of-window or unfinished hours, invalid values,
missing final-hour closes and looping pagination. Zero-volume quote-derived
bars remain legitimate observations. Receipt hashes bind canonical decoded
JSON, not original HTTP bytes or historical publication timestamps.

A real market-data-only run completed 47 pages and obtained 200 closes per coin
through the UTC boundary September 11, 2026. One intraday hour per coin is
missing; no required final-hour close is missing. Raw decoded receipts and the
summary are in `evidence/spot-history-live-read*.json`. The initial 24-page bound
failed closed on short API pages; the successful implementation allows 64 pages
within the existing 45-second and 9600-record limits. The first failed run did
not produce usable history or a trading decision.

`prepare_daily_decision` can collect this history directly when caller history
is omitted. It requires an exclusive, flushed receipt file before account/market
planning and reservation. Mocked integration covers collection through plan
reservation and sealed baseline. All 300 relevant tests pass; Ruff passes.

The actual read used existing credentials only for the market-data endpoint.
No positions, account trading state or orders were accessed, and no returns
were computed. Dedicated-account routing and clock accuracy are not verified.
The history receipt still needs binding to the production readiness decision;
research admission, runtime readiness and service installation remain open.

## Evidence-bound submission checkpoint

Preparation now commits a canonical evidence packet atomically with the day,
order identities and account baseline. The packet contains the history receipt
path/checksum and the exact histories, snapshot, assets and quotes used by the
planner. Replays cannot replace evidence or add it retroactively.

`spot_evidence.verify_preparation` checks receipt integrity, account/epoch/day
binding, observation ordering, the sealed baseline, and reconstructs targets
and exact orders. The submitter invokes it before any claim or broker request.
Injected-history plans lack collection receipts and cannot pass this gate.
Checksum binding establishes consistency with retained evidence, not protection
against an actor rewriting the entire local journal and receipts.

301 combined regression tests pass. A subsequent focused integration check also
passes after adding the valid prepared-plan-to-submission path. The same test
confirms that altering a receipt blocks submission with no network or durable
attempt. Existing arbitrary transport/driver fixtures mock evidence verification
explicitly; preparation integration uses the actual verifier. All broker POSTs
remain mocked. Dedicated spot credentials are still absent.

This completes evidence binding and reconstruction, not full runtime readiness.
Current account/market risk, calibrated clock, research admission and verified
account routing still require the production readiness provider. No real orders
or returns were produced and the restart remains inactive.

## Current-market risk checkpoint

The submitter now invokes `spot_risk.check_current_risk` inside its bounded
pre-claim deadline, after the external readiness callback. It re-reads the
authenticated account, long spot positions, open orders, current asset metadata
and current full books. Foreign holdings, open orders, stale/disordered books,
changed quantity/tick constraints or limits outside the current price cap block.

Buys must preserve cash using conservative current equity and the original
baseline budget. Attempted buys count at full reserved quantity/cost, and sale
proceeds receive no credit toward new purchases. Whole-batch per-coin/gross
limits include existing holdings and potential buys. Risk-reducing sales can
proceed with zero cash/buying power when available spot quantity covers them.
Conservative bounds may stop a later order after prices or equity change; they
do not modify a reserved order to make it pass.

310 regression tests pass, including changed prices, equity, cash, buying power,
increments, stale books, partly filled batches and overweight exits. Prepared
history-to-submission integration uses the actual current-risk collector with
mocked HTTP. Transport-only fixtures explicitly mock this boundary. Ruff passes.

Dedicated spot credentials remain absent. Clock calibration, account routing and
dedication, research admission and the installed readiness/service configuration
remain unverified. Account reads are sequential REST observations, not an atomic
broker snapshot. No actual orders or return computations occurred.

## Mandatory host clock checkpoint

The submitter now takes a bounded read-only host clock sample after the external
readiness callback and before current market-risk reads. The macOS SNTP command
uses no clock adjustment flags. Offset beyond 50 ms or uncertainty beyond 100 ms,
missing tooling, ambiguous output or failed sampling blocks before the durable
submission claim. Cancellation kills and reaps the probe process. Wall/monotonic
deadline checks remain active across preparation.

319 regression tests pass. New tests cover signed offset and uncertainty limits,
malformed output, cancellation cleanup and no submission claim on clock failure.
Other broker/strategy fixtures explicitly mock the host clock. The first current
manual observation was +462.750 ms with 269.760 ms uncertainty. A separate run
through the new checker also blocked; its receipt is
`evidence/spot-clock-current-probe.json`. No system clock adjustment occurred.

This is an operational SNTP check, not authenticated time or certification of
exchange timestamp accuracy. Dedicated spot credentials were rechecked and
remain absent. Account integration cannot start until the dedicated credentials
are configured and time synchronization is corrected during appropriate
maintenance for the existing scheduled jobs. Research/routing/admission and
installed service readiness remain outstanding. No orders or returns produced.

## Owner-supplied dedicated paper keys verified

The saved spot credentials authenticated successfully. Read-only preflight
observed an active funded USD paper account with no positions or open orders
and tradable BTC/ETH metadata. The owner designated this AlphaForge subaccount.
It differs from all three other account bindings successfully verified in this
pass. Three additional historical/configured credential files could not be
verified; complete exclusion coverage is not claimed. The sanitized evidence
is `evidence/spot-dedicated-account-verification.json`.

This supersedes earlier statements that the dedicated credentials are absent.
The fresh host clock probe still failed policy. No orders were submitted, no
new performance epoch was started, and remaining research/routing/readiness
requirements are not automatically satisfied by successful authentication.

## Owner-requested breadth focus resumed

The owner requested renewed sleeve discovery toward Sharpe 2 and 14+ sleeves.
`ALPHAC_BREADTH_PHASE.md` records that forward net aspiration, distinguishes it
from the existing 1.5 canonical headline target, and retains admission gates.
Three provisional leads were added to the research frontier: agricultural
forecast revisions, drug exclusivity transitions and convertible issuance
pressure. No independence or admission claims are made.

Official USDA/FDA samples were retrieved and hashed. Failed guessed historical
USDA URLs were followed by successful retrieval through the official archive
for August 2024. The next research action is an archive-derived agricultural
release/vintage manifest, not a return backtest. No prices or new return trials
were opened. The post-settings-update clock probe still blocked activation.

## Deeper breadth source review completed

See `BREADTH_SOURCE_REVIEW.md`. Fifteen hashed WASDE archive pages yield
131 date labels in 130 months during 2015–2025. Two December 2018 versions
of report 584 have different milk-table values; both were retained with a diff.
Publication times remain unverified. The targeted current FDA sample contains
31 patent entries, seven without submission dates, and no established historical
public-vintage coverage. Convertible issuance is parked after targeted primary
methods/results review failed to establish the proposed return predictor.

Archive collection passed lint and offline replay/error checks. Research
priorities and frontier stages were updated; zero new return trials or
admissions. Dedicated paper account activation remains blocked as previously
recorded; no clock adjustment, orders or new performance epoch in this pass.

## Agricultural source features reconstructed

109 archived text reports now yield 981 crop/year balance-sheet records and
291 source revision rows across wheat, corn and soybeans. Twenty-two dates
remain format/version gated. Publication availability is unknown; all rows
are nontradable. Nine parser tests and source integrity checks pass. See
`WASDE_RECONSTRUCTION.md`. No returns, new admissions or orders.

The owner added transparent algorithm-analysis APIs and MCP servers to the
long-term product direction. `PRODUCT_VISION.md` records them; current work
remains focused on algorithm research.

## Indexed agricultural source coverage completed

All 131 indexed report-date entries reconstruct into 1,179 crop/year records
and 354 source revision rows. Twenty-one XML recoveries and six-way November
2019 selected-field equivalence close the earlier format/version gaps. Sixteen
parser tests and full source-hash/lineage checks pass. `WASDE_RECOVERY.md`
records the limits: scheduled noon timing is supported, exact version
availability and executable costs are not. No returns, admissions or orders.

## First agricultural research signal and market metadata

A signed stocks-to-use revision basket is implemented for research only.
28 extraction/signal tests pass; all 131 real groups remain blocked on missing
availability or comparable revisions. Metadata access and sample retrieval
cost quotes succeeded using the existing data credential. No market records
were downloaded or purchased. See `WASDE_TEST_SPECIFICATION.md` for the
single proposed hypothesis, execution design and remaining pre-trial work.
No new sleeve admission, performance estimate or broker order.

## Existing-data breadth search and provider decision

Databento remains the first choice for the fixed roughly $6 futures sample,
with CME DataMine as an unpriced fallback. Full downloads were rejected for
insufficient account budget; the one-record diagnostic is not quality evidence.
Polygon minute aggregates worked for the tested date; historical quotes returned
403. The local metadata screen yields 186 provisional share-class pairs after
heuristic exclusions, with legal/historical identity still unverified.

Three leads were added: share-class relative pricing, expected earnings-event
demand, and recurring intraday flow. Prior profitability, investment, seasonality
and momentum histories were preserved. See `DATA_SOURCE_AND_EQUITY_SEARCH.md`.
No returns, new admissions or orders. Databento portal opened in Safari.

## Databento budget fix verified through completed downloads

All nine fixed sample requests completed at a fresh quoted total of $5.9667.
Nine file hashes verify, and 34,716,488 depth records were audited. The 2015
sample fails receive-timestamp requirements; 2018/2025 have unflagged valid
quote updates for all three grains in the diagnostic event minute. Definition
files lack an explicit first-notice field. `WASDE_MARKET_SAMPLE_RESULTS.md`
records the remaining replay/fill/availability work. No returns, admissions
or orders. This supersedes the account-budget blocker for this sample.

## Modern agricultural depth scenarios implemented

Completed the fixed 2018/2025 dated-contract depth probe: 72 independent size/side
scenarios at 12 contract/time points. Initial result: 63 full displayed-depth,
three partial-depth, six stale-book blocks. This is not a strategy fill or return
backtest. Twenty-two new tests plus existing signal/quality checks pass (35 total).
No new purchase, return trial, admission or broker order. See the continuation
section in `WASDE_MARKET_SAMPLE_RESULTS.md`; lifecycle and report availability
remain the next evidence requirements.

## Agricultural timing and lifecycle source audit

Nine public source files frozen and hash-verified. All four sampled release
pages encode 12:00 UTC (08:00 Eastern), so those archive fields remain excluded
as historical public-availability evidence. Four dated-contract expiration dates
match CME notices; notices postdate the research decisions and first-notice
fields remain unknown. `WASDE_TIMING_AND_LIFECYCLE.md` records findings and
source-access limits. No return trial, sleeve admission, purchase or order.

## Research queue advanced to share-class legal feasibility

An additional official USDA policy source confirms noon equal-access policy,
but does not close the archived-byte timing gate. Agricultural research remains
data-gated; repeated general schedule searches are no longer the next task.
Two fixed share-class cases now link reviewed rights to local metadata/actions:
Alphabet has equal economic claims without ordinary A/C conversion; Berkshire
has 1:1500 economic units and one-way conversion. The local 2010 B-share split
matches issuer history. `SHARE_CLASS_FEASIBILITY.md` records source limits and
next quote/timeline work. Zero return trials, admissions, purchases or orders.

## Share-class quote coverage tested

Three files acquired at a total quoted $0.028883; 94,920 records and all hashes
verified. Alphabet passes 47/60 and 53/60 fixed paired-quote clocks across two
feeds. NYSE mapping and longer warm-up recover Berkshire observations; 9/60 clocks
pass unchanged age/skew limits. Ten targeted tests and Ruff pass. Pre-sample
quarterly filings were identified for both issuers. No returns, admissions or
orders. See `SHARE_CLASS_QUOTE_RESULTS.md` for exact scope and remaining work.

## Share-class status, cost convention and fixed proposal

Status samples downloaded at a combined quote of $0.000010728836. Alphabet has
53 quote/open/unrestricted-SSR clocks; Berkshire's SSR remains unknown. No
historical locate/rate feed was established, and Alpaca's October 2025 zero-ETB-fee
policy cannot be backdated to August. Borrow quotes and the engine now support
explicit ACT/360 or ACT/365; the legacy default remains 365. 57 tests pass, one
optional real-lake funding test skips, Ruff passes. Research-only proposal is
`SHARE_CLASS_TEST_SPECIFICATION.md`. No return trial, admission, order or deployment.
