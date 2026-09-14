# Current-horizon Trend P&L and costs

Saved normal/stress ledgers,855main-period and2512022source sessions; no new forecasts or strategy returns. Main horizon uses the retained preceding equity mark and excludes all out-of-window source sessions.2022comes from the continuous historical run with its actual starting capital; dollarPnL across horizons is not a directly normalized performance comparison.

| Horizon/cost | Net dollar P&L | Commission | Raw-open slippage | Borrow debit | Same-fill P&L before these costs |
|---|---:|---:|---:|---:|---:|
| main_baseline | 2664.25 | 112.47 | 654.79 | 642.16 | 4073.67 |
| main_baseline_stress | 1221.84 | 223.60 | 1300.66 | 1274.61 | 4020.71 |
| 2022_baseline | 6014.98 | 20.91 | 114.10 | 390.82 | 6540.81 |
| 2022_baseline_stress | 5312.42 | 40.35 | 220.07 | 760.32 | 6333.16 |

Main normal: USO−2233.58,IEF−2111.46,UUP−1873.55,FXE−1706.97 are the largest dollar losses. Each was positive in2022. SHY is positive in both periods (+2516.65main/+1231.97in2022); average absolute weight30.3%main/33.9%2022 does not justify deleting it. Same-fill grossmainPnL only4073.67 before1409.42explicitcosts: cost removal alone does not create strong measured alpha. These are accounting attributions, not cost-free simulated strategies or validated counterfactual returns.

The per-instrument realized/mark/dividend/borrow decomposition sums to every saved full-run NAV delta within1.66e-10. All raw-open joins complete and fill slippage is adverse. Stored forecast values were joined strictly before physical fill-open timestamps; descriptive median magnitudes retained inCSV, not calibrated expectations or threshold-selection evidence. Pending dividend economic accrual is counted once, not again at payment. Input hashes retained. Independent-source fill/borrow certification is not claimed.

Allocator review confirms sign-only inverse-vol weighting perETF; within-group/cross-group covariance is not used by this sizing step (downstream portfolio vol overlay still exists). The menu has five equity, three rates, three currency and six commodity ETFs, with economic overlaps. A prior category-target experiment suppressed equity shorts and failed; no such sign mask is proposed again.

Next single construction hypothesis: equalize estimated stand-alone risk of fixed asset-class groups before the existing global gross/name limits, using unchanged saved forecasts and causal covariance. This tests asset-menu concentration without deleting losing names or changing direction. It is not a distinct alpha sleeve or a claim that allocation alone can reach2Sharpe. First build/test isolated allocation adapter and verify prior-family scope, then freeze full cost-aware normal/stress plus2022 combined gates and register before historical execution. No category, risk-budget, lookback or cap sweep. A failed group design stops this construction family.
