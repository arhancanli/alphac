# Point-in-time options execution foundation

AlphaForge now has tested domain primitives for option terms, quote snapshots, displayed-size
package execution, fee assessment, internal scenario margin, adjusted deliverables, expiration,
exercise, and assignment. This is
engineering evidence, not an options backtest, investable track record, or sleeve-admission
result. No market returns were opened to
build it and no research hypothesis was spent.

## What is enforced

- Option identities are distinct from cash equities, futures, spot, and perpetuals.
- Contract terms, quotes, official settlements, and assignment notices each carry an explicit
  availability timestamp. Future-known inputs fail closed.
- Quotes carry an explicit uppercase premium currency. Cross-strike integrity checks are
  currency-local; values denominated differently are never compared as one series.
- A surface contains one underlying, active contracts, and unique economic terms. Quotes outside
  the listed-to-last-trade lifecycle are rejected.
- Crossed and stale quotes are rejected. Within homogeneous expiry/right/exercise/settlement/
  multiplier series, positive-size bid/ask bounds must satisfy call/put strike monotonicity and
  nonuniform-strike convexity. Missing strikes remain missing; the engine does not interpolate,
  smooth, or repair a surface.
- Multi-leg orders use signed integer ratios and explicit IOC or FOK handling. Positive ratios
  cross the displayed ask and consume ask size; negative ratios cross a strictly positive bid and
  consume bid size. The smallest whole-number leg capacity controls the entire package, so IOC
  partial execution preserves every ratio and cancels the residual while an undersized FOK order
  executes nothing.
- Every package has a maximum net debit per unit; a negative ceiling expresses a minimum required
  credit. All legs must share one explicit premium currency. Premium cash is multiplier-aware and
  must reconcile exactly across the package record.
  Missing quotes, zero bids, sub-ratio size, future-submitted orders, malformed evidence records,
  and non-marketable debit/credit limits fail closed.
- Package execution can require point-in-time market-status coverage for every leg. OPEN may cross;
  HALTED and OUTAGE block; AUCTION_ONLY cannot use the continuous displayed-leg assumption; and
  missing or future-known coverage fails closed. Each queried leg's effective status and reason is
  retained on the execution evidence record.
- Status inputs can be normalized through strict reviewed manifests bound to the exact SHA-256 of
  supplied source bytes. Publication, event observation, historical availability, local capture,
  and review timestamps remain separate. Qualification requires dual review; exact reconciliation
  requires distinct official-exchange and vendor bytes to agree on status, scope, and the complete
  effective interval. The generic contract accepts canonical OPTION instrument identities.
- A reconciliation-only preflight can require complete explicit status coverage over each option
  instrument interval. Source silence never implies OPEN; instrument status retains precedence,
  future-known specific status cannot fall back to a venue-wide event, and every missing interval
  is labeled while covered plus gap milliseconds must reconcile to the requirement.
- CLOSE_ONLY permits a package only when it is explicitly reduce-only and supplied integer-contract
  positions prove that every full requested ratio leg moves toward zero without increasing or
  flipping exposure. The same integrity check applies to reduce-only packages in OPEN markets, so
  the flag cannot become a leverage exemption.
- Option fee schedules are immutable point-in-time revisions keyed by venue, account class,
  product group, and premium currency. Every revision binds effective and local-availability
  intervals plus a credential-free HTTPS source URL and SHA-256 digest; revision identities are
  contiguous and cannot regress in availability or effective time.
- Fee components use exact decimal arithmetic and can scope per-contract or premium-rate charges
  by buy/sell side, maker/taker/auction liquidity, and trade/exercise/assignment event. Explicit
  order minima, caps, rebates, and component-level no-rounding, half-up, or ceiling-to-increment
  policies are supported. Rounding occurs before contractual minima and caps. Accepted package
  legs supply the contract counts and premium notionals; rejected packages cannot be charged, and
  every fee line must reconcile to the exact assessment total.
- Internal scenario margin consumes a complete stressed-price matrix from a locked upstream model.
  Every scenario must price every held option exactly once in one premium currency. Model and input
  artifacts carry SHA-256 identities; future-known, stale, duplicate, incomplete, extra-instrument,
  cross-currency, negative-price, or inexact-number inputs fail closed.
- Scenario P&L nets all legs before selecting the worst loss. Separate point-in-time initial and
  maintenance policies can apply an explicit loss multiplier, per-short-contract floor,
  gross-short-mark add-on, and underlying-group concentration add-on. The assessment records every
  parameter and re-derives every component and total; the snapshot model identity must exactly
  equal the policy risk method. Mismatched methodology and coherent-looking arithmetic tampering
  fail closed.
- Expiry uses an official settlement observation available after expiration, not a convenient
  last trade or midpoint.
- Cash-settled and physically settled call/put positions produce signed, multiplier-aware cash
  and underlying delivery. Below-threshold contracts lapse explicitly.
- Early assignment requires an observed broker/clearing notice and American physical terms.
  The platform does not invent assignment from an uncalibrated probability.
- Each adjusted deliverable has a source reference, contiguous revision number, effective time,
  source-observation time, and platform-availability time. Replay selects only the latest revision
  both effective and available at the decision; future-known revisions fail closed.
- An adjusted package can contain multiple canonical assets and currencies plus explicit exercise
  cash. Expiry and observed assignment convert it into one deterministic option-close, asset, and
  cash basket whose signs are tested for calls, puts, long positions, and short positions.
- OCC adjustment documents enter through a strict reviewed-extraction manifest. Every observation
  binds the raw source URL and SHA-256 digest, exact decimal economics, source publication time,
  local availability time, effective time, stable contract-class key, and contiguous revision.
  Unknown fields and malformed official memo identities fail closed.
- The source archive accepts only the canonical HTTPS OCC memo endpoint, refuses redirects,
  bounds response size, validates PDF media type/signature/terminator, and writes immutable
  SHA-256-addressed blobs plus point-in-time manifests. Repeated observations are idempotent;
  changed source bytes become visible history, while conflicting claims at the same observation
  time fail closed. Every reviewed OCC extraction must bind exact archived bytes observed no later
  than its local availability time.
- Anticipated terms, fewer than two independent reviews, unresolved/TBD consideration, delayed
  settlement, reused source content, and non-final revisions remain auditable but cannot qualify
  for replay. A numeric suffix identifies a non-standard option class; it never defines its terms.
- A separately captured vendor observation must exactly match OCC on effective time, adjusted root,
  multiplier, strike-cash multiplier, exercise currency, settlement state, canonical assets,
  source identifiers, quantities, and fixed cash. Every disagreement is named and blocks
  qualification rather than being resolved by preference or tolerance.
- Generic crypto routing and transaction-fee schedules reject options.

These rules follow OCC/OIC's published boundary: adjusted roots can be revised again without a new
suffix, adjustments are case-specific, and deliverables may include multiple securities, fixed
cash, cash in lieu, or components whose settlement is delayed. Representative primary sources are
[OCC Information Memo 26853](https://infomemo.theocc.com/infomemos?number=26853), the
[OIC corporate-actions FAQ](https://www.optionseducation.org/referencelibrary/faq/splits-mergers-spinoffs-bankruptcies),
and [OCC Information Memo 59573](https://infomemo.theocc.com/infomemos?number=59573).

## Deliberate boundary

These checks establish quote-bound integrity, an explicit atomic displayed-leg crossing model, a
fail-closed adjusted-deliverable representation, an immutable source-byte archive, and a reviewed
normalization/reconciliation contract—not actual simultaneous package fillability or historical
adjustment coverage. Displayed bid/ask sizes on independent legs do not prove that a complex order
would fill atomically; the replay therefore publishes its assumption as
`atomic_cross_of_independently_displayed_bid_ask_without_fill_probability` and does not invent
hidden liquidity, queue priority, complex-order-book price improvement, or beyond-displayed-size
impact. Fee semantics are implemented, but no historical venue/account/product schedule corpus,
content-verified fee-source archive, calibrated rate set, or production adapter is bundled; no
default option commission is invented. Internal scenario margin is an AlphaForge risk measure,
not a broker, OCC, exchange, regulatory, TIMS, STANS, or portfolio-margin replica; the supplied
stress prices are not independently validated by an option repricer, and opening premium cash is
outside the requirement. Status replay consumes supplied point-in-time events and the reviewed
ingestion and preflight boundaries can normalize and audit supplied source artifacts, but there is
no historical options status corpus, production status adapter, empirical broad-market coverage
evidence, complex-order auction model, live venue-status polling, or outage failover. The archive
transport is
injectable, but operational unattended acquisition is not established: on 2026-08-18, direct HTTP
and headless Chromium requests to the live OCC memo endpoint both returned HTTP 403 with
`cf-mitigated: challenge` and exposed no PDF bytes. This limitation is preserved as a negative
result; no challenge bypass or historical corpus is claimed. An OCC-supported distribution path or
authorized operator retrieval is required before corpus accrual can be represented as operational.
There is not yet automated PDF text extraction, a reviewed historical memo corpus, a production
vendor feed adapter, a historical terms/quote
ingestion spine, implied-volatility fitter, put-call-parity input set, dividends/rates/borrow
exercise model, arbitrage repair, a validated stress repricer or calibrated scenario corpus,
broker/OCC/exchange/regulatory margin equivalence, opening-premium collateral integration, margin
calls and forced liquidation, end-to-end backtest ledger, or
broker exercise/reconciliation path. The existing Deribit forward capture is a research data
accrual process; it does not erase these gaps.

Until those components and their point-in-time evidence exist, no candidate may claim realistic
options execution or assignment modeling. The machine-readable capability statement is published
at [`/glassbox/options_execution_contract.json`](/glassbox/options_execution_contract.json).
