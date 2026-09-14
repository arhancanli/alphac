# Retrospective execution integration

Implemented an explicit retrospective action/payment path in the opt-in payable engine and research runner. The default settlement and action availability checks remain strict. Retrospective callers must supply a nonnegative integer capture cutoff and a complete typed action schedule together. Events later than that cutoff, duplicate actions/payments, or unequal dividend/payment cash schedules fail. Actual observation metadata remain distinct from economic dates; result metadata declares RETROSPECTIVE_CURRENT_VINTAGE and point_in_time_proven=false, with action and payment hashes.

The supplied schedule is the retrospective execution authority. It avoids both the historical reader cutoff and ex-date knowledge requirements without rewriting timestamps in the source lake. The inherited legacy engine and corporate-action primitive are unchanged. The retrospective loop requires all in-window actions to be consumed at their exact session boundaries. Existing split sanity checks, entitlement ordering, payable-date cash, financing segmentation and signed short liabilities remain in force.

A real nonempty schedule exposed a preexisting runner bug: Decimal cash values could not be serialized into its input fingerprint. Cash is now represented as an exact decimal string in that binding, using the retained payment tuple rather than re-consuming the caller's iterable.

## Historical inputs

Prepared a separate 2012–September 11, 2026 input bundle: 62,798 rows, 17 ETFs, 834 corporate actions and 830 dividend payments. Synthetic OHLC starts from each ETF's first 2012 raw bar and is rebuilt from reviewed raw prices/actions. Each action is included once. An independent shares/reinvestment calculation agrees with signal closes within 8.216e-15 relative error. All non-signal fields, including raw OHLC and volume, match the prior selected panel exactly.

Prior reviewed-panel and EFA source seals were checked before preparation. The schedule retains reviewed-source observation metadata; payment knowledge is conservatively bounded by the recorded review closure time. The newly declared capture cutoff is actual preparation time. A separate historical engine preflight loads all 834 actions even though all captures follow the simulated end date, validates all payment cash, and verifies staged hashes. No strategy forecasts, IC calculations or historical strategy returns were computed.

## Tests and limitations

47 targeted tests pass in 3.34 seconds; Ruff passes. Eight new cases cover long/short economic parity with timely fixtures, weekend and same-day cash, terminal unpaid entitlements, financing, splits followed by dividends, schedule refusals, and a staged runner-to-engine execution with a late dividend. Timely and retrospective fixture equity, fills, financing and corporate-action outputs match exactly where compared. Default late-payment rejection remains verified.

Initial new-test failures identified the Decimal serialization bug and one incorrect expected exception class. Both were corrected; an intermediate suite invocation with a nonexistent filename ran no tests and was followed by the successful complete invocation. Old evidence is preserved; earlier source hashes describe prior implementations and are not resealed to claim unchanged code.

This completes retrospective accounting integration and input staging, not strategy evaluation or admission. Historical data remain current-vintage; smaller cash precision differences, USO volume differences, modeled costs/borrow and already-inspected history remain limitations. The new IC anchor, exact warmup/evaluation configuration, comparison criteria and trial identities must be frozen and registered before strategy computation. Hypothesis union remains 238. Sharpe 2 and 14+ qualified sleeves remain unmet targets.
