# Payment timing contract review

Decision: **exact intraday timestamps are not universally necessary for daily cost accounting**. The previous mapper correctly refused to invent payment timestamps, but its zero-bookable-payments result should not imply that date-level fee evidence is useless for daily portfolio measurement. Updated the research evaluation draft with a separate daily cost timing policy; it remains out of force.

Alpaca distinguishes transaction execution time from non-trade activity dates. Its non-trade date may describe occurrence or settlement, and FEE denotes a USD fee. Those fields do not establish an exact UTC posting instant. [Account activity objects](https://docs.alpaca.markets/us/docs/account-activities).

The activity endpoint filters by creation time, which can differ from settlement or trading dates. Therefore creation time is useful for acquisition coverage and knowledge provenance, not as an automatic substitute for economic timing. [Trading API activity endpoint](https://docs.alpaca.markets/us/reference/getaccountactivities-2).

The following decisions are accounting-design inferences, not additional provider guarantees:

| Use | Timing needed |
|---|---|
| Daily net NAV with costs already included in reconciled cash/liabilities | Correct opening/closing balances and cost recognition; an exact fee timestamp is not independently necessary |
| Daily cost attribution | Provider date with explicit calendar/timezone semantics and reconciliation to the relevant balance interval; date alone is insufficient |
| External deposits/withdrawals | Timing adequate for the chosen return adjustment; current closing-boundary-only restriction remains |
| Funding entitlement or position-changing events | Position and contract evidence at the applicable boundary; date-only data may be insufficient |
| Execution causality and market prices | Source/receipt/decision timing requirements remain |

Example: opening NAV 100 and closing NAV 98, with a fee of 2 already included and no external flow, yields -2%. Subtracting the fee again incorrectly gives -4%; treating it as a withdrawal incorrectly gives 0%. Exact intraday fee timing does not alter the correct endpoint calculation in this example. Conversely, a 20 deposit within an interval cannot simply be treated as a closing deposit without support for that convention.

Late postings require separate knowledge time and versioned correction/accrual evidence. Preserve the as-known observation; do not silently rewrite its past date. Absence of a source-observation timestamp alone need not invalidate independently reconciled daily cost evidence. Actual local receipt provenance, balance coverage, liabilities and account identity still matter.

The nine retained fee records are eligible for further daily reconciliation, **not newly approved payments or valuations**. We have not proved which boundary balances include them, their exact posting instants, the provider-date timezone, complete liabilities or absence of external flows. The daily UTC valuation convention and clock gate are unchanged. The existing exact-time payment API remains unchanged; it needs a separate daily annotation/reconciliation path rather than fabricated timestamps.

Verification: original and revised draft JSON are saved; scope/targets, valuation design, return formula and qualification requirements are unchanged. Decimal arithmetic examples were checked independently. No new software test suite was added for this documentation/policy phase. The previously tested mapper's behavior is unchanged. No production action, cash application, epoch, backfill, strategy trial or admission occurred.

Firecrawl CLI was unavailable, so primary provider documentation was checked with the available web reader. Sources above support only the provider-field semantics; the policy decisions are explicitly our design conclusions.

Phase complete. Next bounded phase: build daily fee annotations and a reconciliation bridge against retained account balances/accruals, while preserving unknown posting intervals. This should establish whether the available daily evidence can support measurement without requiring nonexistent precision. Combined performance targets and the legacy crypto residual remain unresolved.
