# Combined portfolio valuation contract — isolated phase complete

Implemented and tested a structural USD valuation/return contract in `src/alphaforge/validation/portfolio_valuation.py`. The companion `config/research/portfolio_evaluation_v1_draft.json` records the combined targets and explicitly unresolved qualification/activation inputs. It is **DRAFT_NOT_IN_FORCE**. Existing production contracts, trading, marks, epoch and publication are unchanged.

## What the implementation establishes

The proposed accounting basis is a sum of disjoint funded accounts/ledger partitions at a midnight UTC cut. Each declared sleeve, cash partition and overlay must be present. The policy binds ledger identities, epoch, effective cut, instrument calendars, reporting delay, reconciliation tolerance and an allocation-manifest digest. Duplicate capital, missing components or mixed policies fail.

This deliberately distinguishes a funded NAV from the legacy normalized analytical composite. The old four-quarter curve plus an additive 10% overlay cannot simply be relabeled as the new NAV. Overlay capital, financing, transfers and costs must have a real accounting representation before this contract can measure that book. No reallocation was made here.

Each component reconciles cash plus signed position values plus receivables minus liabilities against reported NAV. Fees and financing already charged to cash are not deducted again. Unknown cashflow coverage fails. Negative end NAV is retained and flagged rather than suppressing catastrophic losses. Financial arithmetic uses a fixed 200-digit decimal context with bounded decimal inputs, independent of ambient process precision.

Prices follow the frozen instrument calendar. XNYS instruments use the latest completed official close, including holidays and early closes; the cash/holdings/accrual snapshot must still refer to the current cut. Crypto requires an explicit cut-time valuation price and cannot select the equity closure rule. No last-price age allowance or receipt-delay value has been chosen for real acquisition; the synthetic fixture's 1,000 ms reporting delay is not a production standard.

Daily interval calculations require exactly adjacent UTC cuts under one policy. The first version supports external deposits/withdrawals only at the closing boundary, already included in closing cash. Intraday flows are rejected pending event-level accounting. Net return is `(closing NAV - net closing deposit) / opening NAV - 1`. Excess return subtracts the cash reference over that exact interval. Cash interest already earned in the account and benchmark subtraction are different concepts; a reference return is not credited as portfolio cash.

Valuation and interval receipts hash the supplied evidence, flows and benchmark. These are structural receipts: account ownership, truthful source payloads, complete flow inventories and clock accuracy are **not authenticated** by caller-supplied hashes or flags. All outputs retain `authentication_verified=false`, `runtime_clearance=false`, and `portfolio_targets_established=false`.

## Verification

**88 focused tests pass**, including 40 new valuation-contract cases and the prior 48 book/forward-measurement tests. One archived-workstation-artifact test remains skipped because its publication output is absent from this checkout. Ruff passes for the implementation and tests.

Cases cover missing/duplicate components, account and epoch mismatch, stale or future evidence, false coverage flags, NAV reconciliation, funded overlay inclusion, duplicate capital, weekend/holiday/early-close pricing, crypto calendar substitution, fees/shorts/liabilities, external deposits and withdrawals, duplicate/intraday flows, missing benchmark coverage, missing-day intervals, loss beyond starting capital, stable decimal arithmetic, and evidence-hash substitution.

The initial collection attempt rejected a malformed synthetic tolerance string `.01`; the fixture was corrected to the declared plain-decimal format `0.01`. The subsequent 37-case run passed, then three additional cases and combined regression coverage brought the final total to 88. No market-return experiment was run.

## What remains before a real measurement stream

- Source/account binding and raw-timestamp/session mapping must be implemented at the acquisition boundary; this typed checker does not decode or authenticate broker responses.
- Cut-time crypto prices, current-cut cash/holdings, complete accruals and transfers, and measured reporting/clock limits must be demonstrated. Unsupported asset calendars/currencies require explicit additional policies.
- A dated cash benchmark, allocation/funding manifest, and pinned implementation/environment/calendar must be bound before a real interval is emitted.
- The performance qualification policy still needs frozen uncertainty/multiplicity methods, evaluation horizons and stress scenarios. The inherited observation counts alone do not establish Sharpe above 2. The owner's 11% maximum drawdown is not reduced to expected drawdown.
- The 15+ objective counts qualified economic mechanisms, not account partitions or instruments. Admission and launch remain separate from valuation arithmetic.

## Progress and next phase

The measurement rules now have executable checks and regression evidence. **No improvement in strategy returns, no qualified sleeve and no new live epoch is established.**

Next proposed phase: inspect the existing read-only acquisition paths against this contract and build a bounded adapter/coverage report. Determine what is actually available at a cut and what is missing before choosing operational limits or opening another return trial. Keep algorithm research focused on a fair combined-book comparison once that foundation is usable. Stop here for the phase review.
