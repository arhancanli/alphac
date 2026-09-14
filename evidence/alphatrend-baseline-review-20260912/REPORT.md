# AlphaTrend baseline and exposure review

Saved observations only; no new strategy return paths or trial reservations.

## Portfolio exposure

| Arm | Mean gross | Mean net | Mean long | Mean absolute short |
|---|---:|---:|---:|---:|
| baseline | 0.9702 | 0.1035 | 0.5368 | 0.4334 |
| candidate | 0.9714 | 0.3003 | 0.6359 | 0.3356 |

## Every instrument

Weights and short fractions use all 2,940 equity sessions, including flat sessions. Forecast means use finite saved daily forecasts in the evaluation interval, not only executed decision dates. They are descriptive and cannot identify causal trade attribution.

| Arm | Instrument | Mean weight | Mean absolute weight | Short sessions (%) | Mean annual forecast |
|---|---|---:|---:|---:|---:|
| baseline | XUSE:CASH:DBAUSD | -0.0096 | 0.0426 | 62.59 | -0.0019 |
| baseline | XUSE:CASH:DBCUSD | -0.0088 | 0.0322 | 60.88 | -0.0017 |
| baseline | XUSE:CASH:EEMUSD | -0.0009 | 0.0277 | 52.04 | -0.0002 |
| baseline | XUSE:CASH:EFAUSD | 0.0078 | 0.0337 | 39.12 | 0.0020 |
| baseline | XUSE:CASH:FXEUSD | -0.0218 | 0.0712 | 66.29 | -0.0017 |
| baseline | XUSE:CASH:FXYUSD | -0.0330 | 0.0596 | 76.84 | -0.0041 |
| baseline | XUSE:CASH:GLDUSD | 0.0123 | 0.0378 | 37.04 | 0.0028 |
| baseline | XUSE:CASH:IEFUSD | -0.0058 | 0.0868 | 53.71 | -0.0001 |
| baseline | XUSE:CASH:IWMUSD | 0.0042 | 0.0267 | 43.88 | 0.0016 |
| baseline | XUSE:CASH:QQQUSD | 0.0179 | 0.0275 | 19.39 | 0.0078 |
| baseline | XUSE:CASH:SHYUSD | 0.1294 | 0.3292 | 29.59 | 0.0008 |
| baseline | XUSE:CASH:SLVUSD | -0.0035 | 0.0210 | 59.15 | -0.0013 |
| baseline | XUSE:CASH:SPYUSD | 0.0246 | 0.0340 | 14.97 | 0.0064 |
| baseline | XUSE:CASH:TLTUSD | -0.0123 | 0.0379 | 66.29 | -0.0026 |
| baseline | XUSE:CASH:UNGUSD | -0.0073 | 0.0109 | 82.62 | -0.0318 |
| baseline | XUSE:CASH:USOUSD | -0.0047 | 0.0152 | 63.27 | -0.0104 |
| baseline | XUSE:CASH:UUPUSD | 0.0150 | 0.0764 | 40.14 | 0.0010 |
| candidate | XUSE:CASH:DBAUSD | -0.0019 | 0.0426 | 53.74 | 0.0004 |
| candidate | XUSE:CASH:DBCUSD | 0.0024 | 0.0322 | 45.58 | 0.0009 |
| candidate | XUSE:CASH:EEMUSD | 0.0094 | 0.0277 | 36.05 | 0.0026 |
| candidate | XUSE:CASH:EFAUSD | 0.0137 | 0.0337 | 30.95 | 0.0042 |
| candidate | XUSE:CASH:FXEUSD | -0.0026 | 0.0712 | 54.39 | -0.0005 |
| candidate | XUSE:CASH:FXYUSD | -0.0169 | 0.0595 | 64.25 | -0.0021 |
| candidate | XUSE:CASH:GLDUSD | 0.0153 | 0.0378 | 32.31 | 0.0052 |
| candidate | XUSE:CASH:IEFUSD | 0.0227 | 0.0869 | 37.04 | 0.0008 |
| candidate | XUSE:CASH:IWMUSD | 0.0100 | 0.0268 | 32.99 | 0.0049 |
| candidate | XUSE:CASH:QQQUSD | 0.0193 | 0.0278 | 17.35 | 0.0102 |
| candidate | XUSE:CASH:SHYUSD | 0.1726 | 0.3292 | 23.13 | 0.0009 |
| candidate | XUSE:CASH:SLVUSD | 0.0026 | 0.0210 | 44.22 | 0.0042 |
| candidate | XUSE:CASH:SPYUSD | 0.0249 | 0.0348 | 15.65 | 0.0081 |
| candidate | XUSE:CASH:TLTUSD | 0.0030 | 0.0378 | 46.56 | -0.0001 |
| candidate | XUSE:CASH:UNGUSD | -0.0063 | 0.0109 | 78.54 | -0.0197 |
| candidate | XUSE:CASH:USOUSD | -0.0008 | 0.0152 | 52.38 | -0.0038 |
| candidate | XUSE:CASH:UUPUSD | 0.0330 | 0.0764 | 29.25 | 0.0020 |

## Baseline decision and prospective design

Keep the original centered baseline as the historical control; it is not an adequate sole acceptance benchmark for the combined-portfolio objective. The directional candidate remains rejected under its original rules. Stronger future comparators should include a dated cash-return reference, a simple predeclared risk-balanced trend control, and the exact existing combined book with and without the proposed change. These are proposed new comparisons, not measured results.

Separate the signal question from the allocator question. Inspecting the retained paired-price allocator shows covariance/shrinkage sizing, volatility scaling, position clipping and the drawdown ladder between expected returns and final targets. Therefore a normalization change is not a clean demonstration of a better economic edge. Do not attribute the observed losses to covariance without an isolated registered comparison.

Before a new experiment, freeze the economic hypothesis, unchanged signal/control definitions, benchmark cash series and available-at-decision rules, portfolio composition/weights, common sample and calendars, net excess-return Sharpe, drawdown horizons, cost/borrow/financing stress, effective trial accounting and untouched/prospective evaluation. Keep zero-benchmark statistics explicitly separate. Freeze success rules around combined-book value; lower turnover alone is not a universal requirement if net returns, capacity and portfolio risk improve.

A revised baseline is permitted when economically justified, but requires a new version and reservation before return computation. All older failed comparisons and identities remain in the record. No losing instrument is removed based on this table. Full-book Sharpe above 2 and maximum drawdown at most 11% remain unestablished.
