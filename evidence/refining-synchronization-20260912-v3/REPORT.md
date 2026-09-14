# Refinery delivery-month and quote synchronization audit

Completed September 12, 2026. All three sample windows fail the frozen quote-coverage gate. This is a data/execution-feasibility result, not evidence that the economic hypothesis has no value. No strategy returns, trading orders, new data purchases, or sleeve admission occurred. Hypothesis union remains 240; the user's Sharpe 2 and 14+ qualified-sleeve objectives remain unmet.

## Frozen method

Use prior-known instrument definitions to select the nearest common full delivery year/month with more than ten calendar days to the earliest leg expiry. Selection precedes quote loading. Require USD, correct contract units and quantities, consistent symbol metadata, unique identities and no definition changes within the window. First-notice dates remain unverified.

At each of 600 one-second decisions from 18:00:00 through 18:09:59 UTC, take each leg's latest received raw record, including invalid states. Require complete updates, acceptable feed flags, event and receive ages at most one second, receive-time skew at most 250 ms, valid tick prices and enough displayed bid and ask size for one 3 CL : 2 RB : 1 HO recipe. Reject snapshots and bad timestamp/book flags. Do not substitute a previous good state. Require at least 90% qualifying decisions on each date.

The recipe uses 3,000 barrels of crude and 84,000/42,000 gallons of gasoline/heating oil. Prices retain signed fixed-point integers. Quote indications do not establish simultaneous fills.

## Results

| Window date | Common maturity | Contracts CL / RB / HO | Qualifying / 600 | Coverage | Conditional median quoted round-trip width |
|---|---|---|---:|---:|---:|
| 2015-01-15 | March 2015 | CLH5 / RBH5 / HOH5 | 0 | 0% | unavailable |
| 2020-04-20 | June 2020 | CLM0 / RBM0 / HOM0 | 5 | 0.83% | $151.80 |
| 2025-07-15 | September 2025 | CLU5 / RBU5 / HOU5 | 27 | 4.50% | $106.20 |

Every selected 2015 raw record carries the bad-receive-timestamp flag. The newer windows fail mostly on age, cross-leg timing or displayed size. Reason counts record the first failure only, so they do not count every simultaneous defect. Full raw flag counts are in `independent_verification.json`.

Widths apply only to the 32 qualifying observations and are not expected execution costs. They exclude fees on twelve contract-sides per recipe round trip, latency, legging risk, market impact, margin and financing. Feed receive time is not local strategy observation time. Three ten-minute windows cannot establish full-history feasibility or infeasibility. The ten-day expiry buffer is a declared sample policy, not a validated roll rule.

## Verification and corrections

33 focused unit tests pass, including sparse-record serialization, exact nanoseconds, delivery-month selection, invalid feed states, stale/future quotes, negative prices, size and recipe arithmetic. Ruff passes the current audit, verifier, synchronization module and associated new tests. Raw fixed-price decoding agrees with SDK dollar decoding for 166,218 selected finite bid/ask fields.

An independent verifier checks all 1,800 grid rows, 10,800 nullable timestamp values against raw latest records, and all 32 accepted indications against separately expressed recipe arithmetic, flags, timing and size. All three versions have identical result and contract-mapping JSON; all frozen source bindings verify.

The original export coerced nullable timestamps to floating point. Version 2 retained exact timestamps but inferred columns from the first invalid row, omitting accepted-indication fields. Both versions remain preserved as superseded diagnostic artifacts. Version 3 declares every field explicitly, checks in-memory exact values and verifies the Parquet round trip. Use only the version 3 grid for downstream audit work.

## Source interpretation

Databento documents raw prices in units of 1e-9 and distinguishes receive-time, update-completion and quality flags. These definitions support the decoding and rejection policy; they do not imply fills. [Standards and conventions](https://databento.com/docs/standards-and-conventions), [MBP-1 schema](https://databento.com/docs/schemas-and-data-formats/mbp-1).

Full maturity metadata comes from instrument definitions. Display factors must not be applied a second time to normalized dollar prices. [Instrument definitions](https://databento.com/docs/schemas-and-data-formats/instrument-definitions), [definition scaling update](https://databento.com/blog/definition-schema-updates-may).

## Next research step

Retain this failed screen without changing its filters. Investigate whether the existing definitions and spread records contain a documented exchange-listed structure that matches the intended recipe, or whether a separately specified sequential execution model is required. Verify instrument legs, ratios, calendar alignment, supported order mechanics and costs before registering any return test. A changed feasibility policy must be identified as a new route and cannot retroactively make this audit pass. No additional credits are needed to inspect the already downloaded records.
