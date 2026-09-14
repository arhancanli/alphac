# AlphaTrend sealed baseline attribution

Verified 877 sealed input/output files. All 42 legs reconcile to within $0.000000000. The stitched equity gain is $25,507.32.

Historical simulation, not forward performance. Commission is explicit; spread and impact are embedded in execution prices. Borrow is reported at book level, not allocated by an invented rule. Dollar contributions are additive across cash-linked legs.

| Instrument | PnL after commission, before borrow | Commission | Share of gross exposure |
| --- | ---: | ---: | ---: |
| XUSE:CASH:IWMUSD | $-3,777.08 | $49.80 | 2.9% |
| XUSE:CASH:UUPUSD | $-3,078.59 | $133.26 | 6.9% |
| XUSE:CASH:SLVUSD | $-1,640.93 | $45.58 | 1.9% |
| XUSE:CASH:USOUSD | $-1,359.93 | $29.15 | 1.7% |
| XUSE:CASH:EFAUSD | $-103.61 | $59.25 | 3.4% |
| XUSE:CASH:EEMUSD | $-36.76 | $52.08 | 2.7% |
| XUSE:CASH:IEFUSD | $1,229.93 | $180.03 | 9.8% |
| XUSE:CASH:TLTUSD | $1,824.16 | $75.60 | 4.7% |
| XUSE:CASH:DBCUSD | $2,030.89 | $53.91 | 3.2% |
| XUSE:CASH:SPYUSD | $2,151.24 | $59.83 | 3.8% |
| XUSE:CASH:FXYUSD | $2,444.00 | $95.20 | 5.6% |
| XUSE:CASH:FXEUSD | $2,889.49 | $117.22 | 6.9% |
| XUSE:CASH:DBAUSD | $3,095.69 | $63.81 | 3.7% |
| XUSE:CASH:UNGUSD | $4,149.36 | $14.42 | 1.0% |
| XUSE:CASH:QQQUSD | $4,197.71 | $53.07 | 3.2% |
| XUSE:CASH:GLDUSD | $5,945.46 | $70.71 | 3.8% |
| XUSE:CASH:SHYUSD | $10,212.54 | $414.03 | 34.9% |

Book-level borrow cashflow: $-4,666.24.

Exposure shares use sums of absolute recorded session weights. These are capital exposures, not risk contributions. The blended book does not record horizon-level PnL; attributing its whole PnL separately to 63/126/252 days would double-count.

Loss rankings are diagnostic and are not an instruction to remove losing assets. The inspected interval is now research evidence, not an untouched test of a new variant.
