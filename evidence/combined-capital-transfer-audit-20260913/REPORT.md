# Combined fixed-weight allocation demands quantified

The previous goal phase completed the failed trade-flow forecast; it remains closed. This phase quantifies a known limitation in the combined performance reference rather than calling it an executable account.

| Horizon and costs | Cumulative one-way implied NAV redistribution per $100000 initial NAV | NYSE-closed days with noncrypto allocation changes |
|---|---:|---:|
| 2023–June1 2026 normal |$184610.18|393|
| 2023–June1 2026 stressed |$176534.82|393|
| Separate2022 normal |$50126.60|110|
| Separate2022 stressed |$49936.86|109|

For each day the audit computes end-of-day subbookNAV before transfers and subtracts it from the target subbookNAV implied by constant22.5/22.5/22.5/32.5percent weights. The four transfers sumzero; half their absolute sum is one-way allocation redistribution. All retained return rows and terminal NAVs reconstruct. Seven synthetic accounting tests pass. Source/reference hashes verified before and after.

These are NAV allocation demands, not measured stock/ETF trading turnover, brokerage transfers or fee estimates. Closed-market target changes demonstrate missing position-scaling mechanics; they do not prove cash itself cannot move on those dates. This audit does not calculate an alternative strategy return path. Existing metrics stay unchanged and provisional.

The source runners all start their independent subbooks at100000, including the BILsubbook; therefore scaling their return curves into a100000combined account does not establish actual integer quantities or minimum-order behavior at22500/32500. Simply multiplying the curves would preserve this limitation.

FUNDED_REPLAY_DESIGN.json freezes the next implementation benchmark before its returns: one actual100000 initial deposit,22500 each retainedalpha and32500BIL, no subsequent inter-sleeve transfers, endogenous weight drift, real per-subaccount quantities/costs/cashflows. This is an explicit allocation-policy change, not a newly discovered alpha. Do not choose it retrospectively because it outperforms. Original daily-fixed-weight reference stays preserved. Normal/stress/separate2022 results and all limitations must be reported.

The design also requires calendar-dated funding/borrow and cashflows. Forward-filling equity sessionNAV can hide weekend borrow timing; summed engine curve labels must not be mistaken for economic-time combined accounting. Opening predecessor positions and capital inception need reconciliation. These concrete requirements govern implementation; no funded run has started yet.

Next: inspect retained runners' inception/position and calendar-cashflow evidence, then version actual-capital runners and register before returns. Time-box preparatory work to these blockers. No new hypothetical strategy trial in this phase;340performance plus2forecastdiagnostic selection history remains. Combined normal/stress excess0.742413/0.418865 unchanged. No new sleeve, qualification, deployment or performance-improvement claim. Previous/current phases progress; all launched jobs terminal; goalactive.
