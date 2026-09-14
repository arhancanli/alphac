# Saved-book attribution relative to implemented BIL cash

No alternative allocation, new forecast or strategy curve was computed. Decomposed saved portfolio excess returns exactly into22.5% times each alpha return less BIL return, plus BIL return less DFF. Dividing all term means by the SAME observed portfolio excess-return volatility gives additive Sharpe contributions, not standalone or marginal Sharpe.

| Horizon / costs | AlphaMax | Crypto carry | AlphaTrend | BIL minus DFF | Combined excess Sharpe |
|---|---:|---:|---:|---:|---:|
| main/normal | 0.1733 | 0.8169 | -0.1896 | -0.0582 | 0.7424 |
| main/stress | 0.1643 | 0.5317 | -0.2134 | -0.0637 | 0.4189 |
| 2022/normal | 0.6865 | 0.4999 | 0.2281 | -0.0873 | 1.3272 |
| 2022/stress | 0.6644 | 0.4486 | 0.2043 | -0.1009 | 1.2164 |

In2023–June2026, Trend loses0.821percentage points/year of portfolio arithmetic mean excess return versus BIL under normal costs,0.909under stress. It adds1.007/0.903points in2022. Removing it based only on the main period would discard measured crisis-period contribution; no such portfolio was simulated here. Crypto supplies most main-period positive excess contribution, so15distinct qualified sleeves remains a substantial unsolved objective. BIL also underperforms the DFF benchmark in these saved paths; the ETF cash implementation does not earn the benchmark by definition.

Bounded follow-up of existing Trend provenance found signal features ALREADY use an independently checked dividend-reinvested synthetic index; do not invent a missing-dividend signal bug or rebuild that input pipeline. Earlier2012–2026 exposure diagnostics found sign-only inverse-volatility allocation and large SHY absolute capital exposure; they are not measurements of the current narrower horizon. The same confirmed direction rule is already in the reference. Next: one saved-path current-horizon per-instrument P&L/forecast attribution, matched against2022, to distinguish signal-direction losses from cost/capital allocation effects before selecting a new economic forecast. No threshold or universe/weight sweep is authorized by this attribution. Reuse existing forecast/position/fill artifacts and keep this diagnostic bounded to a concrete experiment decision.

All saved daily excess identities reconcile to1e-14 and additive Sharpe totals to1e-12; input hashes retained inresult.json. No causal inference, untouchedOOS, capacity or qualification follows from attribution. Union334 and BIL reference331/332main+333/334separate2022 unchanged.
