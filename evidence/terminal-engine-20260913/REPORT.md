# Terminal replay adapter: synthetic integration verified

Added opt-in TerminalBacktester for crypto perpetual research. The shared engine now exposes ledger construction and interval-funding hooks; the default funding implementation is extracted unchanged. A hash-bound pre-edit engine copy is retained here. Old result packets and runners have not been rewritten to claim compatibility with changed source hashes.

The adapter merges terminal events and funding chronologically within each hourly replay interval. Settlement uses the explicitly supplied price and fee, realizes the signed position loss/profit, and closes the contract before later funding or marks. It does not invent intrabar strategy decisions. Later target orders for that contract are blocked; unrelated contracts continue. Administrative settlement rows carry an explicit reason and separate terminal records in result configuration.

## Verification

61 tests pass across terminal engine (8), terminal ledger (11), base engine and payable engine. Ruff checks pass for the changed base engine, adapter and integration tests. The synthetic intrabar case checks a loss, terminal fee, pre-terminal funding, absence of later funding on a closed position, exact cash at the next close, blocked reopening, and continuing ETH execution. Aligned boundaries and end-of-run settlement pass; events outside (start,end] and coincident funding/termination fail explicitly.

The preserved pre-hook engine, current parent and terminal adapter with no events reproduce the synthetic two-asset golden fixture exactly for equity, fills, positions, funding, orders and counters. See parent_parity.json and its reproducible verification script. This is a bounded regression proof, not proof of all possible paths or historical execution quality.

## Explicit research assumptions and remaining work

With terminal events enabled, funding uses the interval's hourly open as a disclosed price proxy (falling back to the previous known close for a missing bar). This changes the funding-price policy from the parent's close proxy, so the historical comparison must separately freeze and control that change. No-event runs retain the parent policy. Simultaneous funding and termination require a sourced tie policy and currently raise. Financing/borrow providers are unsupported because their intervals require separate splits. Events must occur after run start and no later than run end; terminal prices must be positive. Historical notice availability and actual settlement-price authenticity are not established by a source hash or the synthetic tests.

No historical return trial, new qualified sleeve, production activation, or corrected historical result is claimed. Experiment union remains 273. Next: freeze the corrected historical input manifest, modeled settlement scenarios, funding valuation control, costs and comparison gates; register every return identity before computation. Retain uncertainty over the May 2022 settlement rule and price rather than label a modeled reconstruction exact execution evidence.
