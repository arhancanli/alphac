# Agricultural forecast reconstruction — 11 September 2026

The first source-feature dataset now exists. It contains no return estimates
or executable trading signals. Agriculture remains one provisional economic
family, with wheat, corn and soybeans as related inputs.

From the frozen 2015–2025 archive index, the collector retrieved all 109 dates
with exactly one text link. Each response is stored separately and hashed.
Twenty-one earlier dates have no text link, although other formats are indexed.
November 8, 2019 has three text links and is withheld pending version resolution.
These 22 source gaps are not evidence that the underlying reports are absent.
January 2019 and October 2025 remain the separate calendar gaps identified in
the previous archive review.

The strict parser successfully reconstructed all 109 downloaded reports:
981 crop/year balance-sheet records. It checks report identity, selected table,
column count, numerical values, units and two supply/use identities. A two-million-
bushel tolerance accommodates rounding of the published integer components;
passing these identities alone does not establish that every field is correct.

For each crop year, extraction retains the rightmost published column. The
newest crop year's stocks-to-use ratio is compared with that same crop year in
the preceding successfully reconstructed release. The result is 291 revision
rows, three correction-version rows and 33 rows without a comparable prior.
Those crop rows are not independent events or sleeves. Missing source records
break the comparison chain; actual skipped calendar releases are not interpolated.

May's prior-month column for the newly introduced crop year contains NA. It is
allowed only in unselected columns and is never converted to zero. This keeps
new-crop introductions from manufacturing large revisions. The December 14,
2018 report is retained as a correction version rather than a second monthly
signal. November 2019 ambiguity prevents a December comparison across the gap.

Every row has unknown publication availability and is explicitly nontradable.
The saved archive labels establish ordering for this source audit, not exact
historical release or correction times. Forecast revision is also different
from a surprise relative to contemporaneous market expectations. No executable
quotes, order-book depth, return trials or performance claims were added.

## Reproduction and verification

- Collector: `scripts/collect_wasde_vintages.py`; refuses to overwrite its
  destination. Index and individual response hashes identify the observation.
- Extractor: `src/alphaforge/validation/wasde_vintages.py`.
- Builder: `PYTHONPATH=src <project-python> scripts/build_wasde_features.py`.
- Inputs and outputs: `evidence/wasde-vintages/manifest.json`,
  `source-features.json`, `feature-summary.json` and `verification.json`.
- Nine parser tests passed, including independently checked August values,
  May missing comparisons, wrong units, missing/invalid selected values,
  inconsistent balances and conflicting report/table identities. Fixture
  provenance is recorded in `tests/fixtures/wasde/manifest.json`.
- All 109 source hashes, temporal order, May boundaries, correction classification,
  failed-source comparison break and nontradability were checked. Ruff passes.

## Next algorithm work

Resolve the 21 alternative-format reports and the three November 2019 versions
without selecting whichever produces the best signal. Verify original report
and correction publication times. Then freeze a single economic hypothesis,
contract/holding-period rule and cost specification before opening return data.
Test whether revision effects survive trend/carry/seasonality controls and add
portfolio value. Retain all failed trials and report event counts separately
from daily marks. Current results establish inputs, not an edge.

The owner also requested a transparent algorithm-analysis API service and MCP
servers. `PRODUCT_VISION.md` preserves that direction; implementation is deferred
while the algorithm research remains the priority.

## Subsequent recovery

`WASDE_RECOVERY.md` supersedes the 22 format/version gaps reported above.
All 131 indexed entries now reconstruct. Original partial outputs are retained.
Historical availability and execution remain unverified.
