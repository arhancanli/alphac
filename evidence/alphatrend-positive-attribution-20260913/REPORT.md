# Positive targets: reconciled instrument attribution

All four saved paths reconcile at every one of2939 equity timestamps. Maximum absolute daily residual is below$0.000001. Modeled borrow is independently reconstructed from post-fill short quantities, raw session opens, calendar-day accrual and the frozen50bp/100bp annual rates. Total borrow matches retained ledger counters; no residual is allocated arbitrarily to an instrument.

P&L is cumulative realized price profit minus fees plus current unrealized profit, economic dividend income and signed borrowing. Dividend entitlement is economic income at the next snapshot after ex-date; it is not a claim of settled cash. Split basis adjustments are already reflected in saved realized/unrealized values. Spread, impact and latency are embedded in fill prices and are not separately identified here. No new return strategy was simulated.

## Findings

Full-history candidate-minus-control dollar improvement is$22,351.65 on each run's original$100,000 account. Largest positive instrument differences are IWM+$4,003,EFA+$3,825,SPY+$2,427 and UUP+$2,273. The candidate gives up UNG$1,839,FXY$1,104 and TLT$236 over the full history. These are realized-path comparisons with different equity and risk histories, not isolated causal effects or a license to remove losing names.

Q12020 lost contributions are concentrated in commodity ETFs: USO-$1,209,DBC-$916,DBA-$596,SLV-$395 and UNG-$260; EEM also loses$557. Treasury instrument contributions actually improve versus the control in that slice. This contradicts attributing the COVID tradeoff chiefly to bond shorts.

In2022 the candidate loses$1,269 of IEF contribution,$1,191 SHY,$1,115 TLT,$1,195 FXY and$754 FXE. The Treasury/currency exposure differences identified in the preceding audit are supported by instrument-level accounting. Dollar deltas are not percentage-point contributions because starting equity differs between arms in2022.

## Research decision

Do not choose a shortlist of the best historical shorts. A defensible next bounded hypothesis is an economic-category rule: retain the confirmed strategy's shorts across ALL non-equity ETFs while keeping equity ETFs long-or-cash. This retains losing and winning non-equity instruments alike, rather than selecting UNG/FXY/etc from this table. It must be compared with the positive-target control under a new frozen primary/stress specification, including explicit crisis-retention criteria, before any return measurement. Equity positive drift is a hypothesis here, not an established causal explanation of these results.

This is not a qualified new sleeve or OOS evidence. The current combined development result remains excessSharpe1.1065,observedDD3.700%; full-horizon target and15-sleeve requirement remain unmet. No production changes or launch. Trial union265 unchanged.

## Audit development

Two diagnostic assumptions were rejected by numerical checks before reporting: base-engine pre-fill borrow timing (the actual runner uses PayableEquityBacktester), and same-timestamp ex-date snapshot attribution. Correct payable-engine timing reconciles the full paths. These corrections did not rerun or alter any strategy or recorded performance result. Source hashes, detailed instrument/group tables, cumulative instrument P&L and daily borrow tables are retained.
