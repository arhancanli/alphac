# WASDE format and version recovery — 11 September 2026

All 131 indexed date entries from 2015–2025 now reconstruct successfully.
The new dataset contains 1,179 crop/year records, 354 source-revision rows,
three correction rows and 36 rows without a comparable prior crop year.
There are zero parsing gaps. Calendar gaps documented earlier remain genuine
missing index months, not interpolated observations. These counts describe
source coverage, not independent trades or profitable sleeves.

The 21 earlier reports were recovered through official archive XML links.
One download failed initially and succeeded on retry; both receipts remain.
The adapter handles the observed namespaced and unnamespaced schemas, validates
report month, crop matrix and units, and checks every field's year/month column
identity. Properly grouped thousands separators are normalized. Invalid values,
wrong units, inconsistent columns and unsafe XML are rejected. It reuses the
text extractor's balance-sheet checks instead of implementing different
financial arithmetic for the alternate format.

For November 8, 2019, all three text files have identical decoded lines. Each
text/XML pair and all six resulting grain-table extracts agree on every selected
field across all three crop years. The three PDFs identify report 594 dated
November 8, 2019 on their first pages. A canonical text representative is selected
by URL only after field equivalence is checked. All variants remain archived.
This resolves the selected-field ambiguity, not the original upload order or
exact publication times of those files.

The assembly preserves the original collection and partial feature dataset.
The complete manifest and rebuilt features live in `evidence/wasde-reconstructed/`.
Each manifest entry identifies the original response and SHA-256 hash. The
November equivalence inputs are included explicitly. May introductions still
have no manufactured prior, December 2018 retains correction classification,
and the recovered November 2019 values restore the December comparison chain.

USDA's January 8, 2013 notice establishes the scheduled noon release regime
beginning January 11, 2013. It literally uses EDT even for January; we do not
turn that wording into a fixed UTC offset. A schedule is not evidence of each
file's actual availability, especially for corrections. All feature availability
fields remain null and all rows remain nontradable. The notice and its hash are
saved in `timing-evidence.json` and `noon-release-notice.html`.
[USDA release-time notice](https://www.nass.usda.gov/Newsroom/Notices/2013/01_08_2013.php).

Validation: 16 parser tests pass, all 131 response hashes match, and full-dataset
checks confirm chronological comparison, May boundaries, correction treatment,
November/December lineage and nontradability. Ruff passes for changed Python
files. This verifies extraction behavior and internal consistency; independent
cell-by-cell review of every archived table is not claimed.

Next work is to establish a defensible historical availability convention with
version exceptions, obtain intended-venue bid/ask and cost coverage, and freeze
one forecast-revision hypothesis before examining return outcomes. The candidate
must add information beyond commodity trend, carry and seasonality. Corn, wheat
and soybeans stay one candidate family. No return trial or sleeve admission has
occurred, no new Sharpe estimate is reported, and no broker orders were submitted.

Reproduce the feature build with the project Python and `PYTHONPATH=src`:
`python scripts/build_wasde_features.py --dataset-dir evidence/wasde-reconstructed`.
Assembly uses `scripts/assemble_wasde_recovery.py` and refuses to replace its
output directory. Source recovery receipts are in `evidence/wasde-format-recovery/`.
