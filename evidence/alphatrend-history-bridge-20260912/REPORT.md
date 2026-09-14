# AlphaTrend historical continuity and price convention audit

The frozen candidate lake ends August 21, 2026. One bounded GET acquired 493 raw
SIP bars across 29 sessions and all 17 ETFs (August 3–September 11). All expected
symbol/session pairs are present exactly once, with valid timestamp and OHLCV
checks and no pagination. This includes all 238 bars for the 14 missing sessions
August 24–September 11. They are retained separately in
`missing_prefix_raw_bars.parquet`; the frozen lake has not been appended or edited.

The 255 overlapping rows cover 15 sessions per ETF. Most close-return differences
are less than 0.001 bp; FXE reaches 0.4695 bp and SHY 0.6107 bp. These are observed
provider differences, not assumed rounding corrections. Near agreement on this
short window does not demonstrate equivalent price adjustments.

The preserved input manifest identifies Yahoo adjusted bars. The copied current
historical loader explicitly applies adjclose/close to open/high/low and stores
adjclose as close, without corporate-action rows. Its current source documents
the convention; it is not evidence of the exact historical execution source.
The managed-futures momentum implementation consumes `ctx.panel("close")`
directly, so mixing raw bars into this adjusted panel changes the signal inputs.

A separate expanded check of IEF/SHY/TLT across May 1–August 21 found substantial
adjustment-factor changes. See the [factor report](../alphatrend-adjustment-factors-20260912/REPORT.md).
Acquisition completeness is now established for the missing window; adjustment
continuity and the historical prefix's point-in-time provenance are not.

Validation: 39 tests across history normalization, daily capture, corrected
producer and observation journal. New cases reject missing/duplicate bars,
unexpected sessions, pagination, wrong timezone/session labels and duplicate
expected sessions. Ruff and git diff --check pass for this change.
Two total GET requests in this phase; no retries, alternate feeds, strategy return
trials, broker orders or producer activation. Hypothesis union remains 238.

Next implementation requirements:

- Obtain split and cash-distribution records covering each ETF from the anchor
  through every new decision, with effective dates and when records were available.
  Absence of action rows must not silently mean no action occurred.
- Specify a versioned continuation rule anchored to the frozen final session.
  Keep raw execution prices separate from adjusted signal prices and accounting
  cash flows. Establish provider adjustment semantics before choosing the formula.
- Reconcile old/new overlap and every adjustment transition independently; test
  causality under delayed announcements and revised data. A current back-adjusted
  download alone cannot establish historical point-in-time equivalence.
- Bind that adapter, complete prefix, account context and verified clock into a
  new observation epoch. If historical semantics change, register a separate
  candidate before measuring strategy returns.
