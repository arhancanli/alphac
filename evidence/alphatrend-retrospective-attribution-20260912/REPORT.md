# AlphaTrend saved-run attribution

The latest directional candidate remains rejected. This diagnostic describes both existing registered paths (239/240); it computes no new strategy variant and does not change the experiment union of 240.

Dollar contributions include realized and terminal unrealized price P&L, recorded commissions and corporate-action cash flows. Borrow is retained at portfolio level because these files do not allocate it by instrument. Spread, latency and impact are embedded in fills and are not separately identified; fees alone are not total execution drag.

## Reconciled portfolio accounting

| Arm | Equity gain ($) | Borrow cash flow ($) | Action cash flow ($) | Residual ($) |
|---|---:|---:|---:|---:|
| baseline | 7434.86 | -2626.94 | 4614.08 | 0.0000000008 |
| candidate | 6721.89 | -1911.38 | 8666.29 | -0.0000000008 |

## All instrument contributions before portfolio borrow

| Instrument | Baseline ($) | Candidate ($) | Difference ($) |
|---|---:|---:|---:|
| XUSE:CASH:TLTUSD | 496.56 | -2264.93 | -2761.49 |
| XUSE:CASH:GLDUSD | 4035.92 | 1608.71 | -2427.21 |
| XUSE:CASH:FXYUSD | 1577.22 | -358.84 | -1936.07 |
| XUSE:CASH:FXEUSD | 2357.55 | 506.68 | -1850.88 |
| XUSE:CASH:SHYUSD | 6865.34 | 5181.61 | -1683.73 |
| XUSE:CASH:SLVUSD | -1236.79 | -2479.78 | -1242.99 |
| XUSE:CASH:EFAUSD | -1720.08 | -2858.21 | -1138.13 |
| XUSE:CASH:UNGUSD | 2273.04 | 2059.10 | -213.94 |
| XUSE:CASH:IEFUSD | 1284.83 | 1102.79 | -182.03 |
| XUSE:CASH:DBCUSD | 295.60 | 866.86 | 571.26 |
| XUSE:CASH:QQQUSD | 1627.86 | 2270.92 | 643.06 |
| XUSE:CASH:EEMUSD | -147.07 | 777.55 | 924.62 |
| XUSE:CASH:SPYUSD | -1568.40 | -153.84 | 1414.56 |
| XUSE:CASH:USOUSD | -1235.16 | 522.21 | 1757.37 |
| XUSE:CASH:DBAUSD | 406.72 | 2368.15 | 1961.43 |
| XUSE:CASH:UUPUSD | -1271.03 | 802.15 | 2073.18 |
| XUSE:CASH:IWMUSD | -3980.31 | -1317.86 | 2662.45 |

## All calendar-year slices

2026 is partial through September 11. Differences are descriptive percentage points, not additive lifetime attribution or independent validation.

| Year | Baseline (%) | Candidate (%) | Difference (pp) |
|---|---:|---:|---:|
| 2015 | 2.385 | 1.043 | -1.342 |
| 2016 | -3.632 | -4.191 | -0.558 |
| 2017 | -0.210 | -3.000 | -2.790 |
| 2018 | 1.350 | -0.049 | -1.398 |
| 2019 | -2.077 | 0.187 | 2.264 |
| 2020 | 3.734 | -1.482 | -5.217 |
| 2021 | 3.378 | 2.065 | -1.313 |
| 2022 | 5.335 | 5.656 | 0.321 |
| 2023 | -3.780 | -3.633 | 0.147 |
| 2024 | -0.300 | 4.134 | 4.434 |
| 2025 | -0.243 | 2.393 | 2.636 |
| 2026 | 1.708 | 3.965 | 2.257 |

## Next research step

Audit the retained forecast and exposure histories for the instruments with the largest contribution differences, including short exposure and covariance allocation. Do not drop losing instruments or select favorable years from this diagnostic. Any changed strategy needs a distinct economic hypothesis and preregistration before returns. No evidence here establishes Sharpe 2, independent alpha, executable live returns, or a new qualified sleeve.

Both portfolios reconcile to saved final equity within $0.000001. Input SHA-256 hashes are retained in attribution.json. Historical source availability, borrow availability and omitted cash interest remain limitations inherited from the parent comparison.
