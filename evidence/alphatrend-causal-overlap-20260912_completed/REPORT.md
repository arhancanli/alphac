# Corrected AlphaTrend archived overlap

| Comparator | Matched intervals | Pearson correlation | Descriptive 95% interval |
|---|---:|---:|---:|
| AlphaMax | 728 | 0.330 | 0.214 to 0.427 |
| AlphaVintage | 5,163 | -0.004 | -0.087 to 0.065 |

Source curves and source code are frozen with hashes in `protocol.json`. `result.json` contains coverage, dates, Spearman correlations and the common-window correlation matrix. Aligned raw simple returns are retained in parquet. Uncertainty uses 2,000 paired circular 63-observation blocks with fixed seed 20260912; intervals are descriptive, not admission tests.

Returns are matched by both economic starting and ending close; next-session engine labels are corrected before joining. No missing intervals were bridged or converted to flat returns. No activity filter removed known zeros. The all-three window has 728 intervals; its Trend/Vintage correlation is -0.049, distinct from the longer pairwise estimate.

AlphaMax's historical curve hash matches the publication reference, but its fresh-input replay did not match. AlphaVintage remains KILLED under its recorded checks; its log-spread approximation and historical data limitations remain. No independent-sleeve, portfolio-Sharpe, capacity or prospective-performance claim is established. No new return trial, portfolio weights, broker call or production mutation occurred.

A preserved first attempt stopped before correlations on pre-2004 vintage dates outside the core calendar. The completed protocol crops vintage to the first candidate close, before constructing comparable returns. All first-attempt evidence remains in the sibling directory without the `_completed` suffix.
