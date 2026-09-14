# Treasury trade specification and arithmetic

The proposed phase-held implementation is written in TRADE_SPEC.md. It fixes selection at entry, retention of CUSIPs and quantities through each phase, explicit reversal, settlement-aware instruction aggregation and exact cash/duration hedge arithmetic. It is a new implementation proposal, not a verified reproduction of the literature strategy or a return-ready portfolio.

The staged plan contains 305 phases across 156 auctions, with 915 candidate leg slots and 514 distinct preliminary CUSIPs. These references are for data coverage assessment, not verified trade instructions. The previous source hashes were verified before staging. No market prices or returns were opened; no purchase or order was made. Hypothesis union remains 240 and the user's Sharpe 2 / 14+ qualified-sleeve goals remain unmet.

26 tests pass: 16 new arithmetic/identity/settlement cases plus ten reference-mapping tests. Exact rational arithmetic verifies cash and parallel-duration neutrality with unequal dirty prices. Tests check sign reversal, invalid inputs, same-identity netting with retained event attribution, separation by settlement/venue/account/financing, supplied-calendar holidays and the difference between original issuance and reopening settlement. Current new code and tests pass Ruff. These tests do not validate a broker, a historical calendar, lot sizing or real fills.

A filename inventory of /Users/arhancanli/alphaforge/data found 122 Treasury-related paths, saved in local_inventory.json. This limited search does not establish whether differently named or external cash-market holdings exist. Existing auction metadata and schedule archives are reusable; they do not provide all trade inputs.

CME's BrokerTec catalog lists benchmark note/bond tenors, with full-book history from 2000 and top/depth tables beginning December 2014. Its FAQ gives a different 2014 start month, requiring clarification. The listed product does not establish six-month-bill or off-the-run coverage, both required by this proposal. [CME dataset documentation](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457421032).

A vendor coverage inquiry is prepared in DATA_REQUEST_DRAFT.md but not sent. The next step is coverage and entitlement verification, particularly bills, historical benchmark changes, off-the-run exits and financing. Do not buy more Databento credits for this unresolved requirement. No request for user action is necessary to review this packet; no external message has been authorized or sent.
