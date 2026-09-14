# AlphaC algorithm research: combined-book contributions

Recovered the four frozen sleeve equity series and reconstructed their historical fixed-weight book with the separately identified overlay. The 1,061-day window is July 7, 2023–June 1, 2026. Reconstructed raw-return Sharpe is **1.78462818**, CAGR **9.6007%**, and initial-capital-aware observed drawdown **4.5087%**. These are limited historical-control metrics, not qualified net-excess or forward results.

| Component | Annualized arithmetic return contribution | Share of book variance | Additive contribution during worst book drawdown |
|---|---:|---:|---:|
| AlphaVintage | +0.314% | 8.33% | -1.789% |
| AlphaForge | +4.026% | 33.78% | -1.157% |
| AlphaMax | +2.034% | 27.23% | -0.337% |
| AlphaTrend | -0.167% | 4.40% | -0.240% |
| Strategic overlay | +3.097% | 26.26% | -1.069% |

Contributions sum arithmetically, not as compounded sleeve returns. AlphaForge is the main positive sleeve contributor. AlphaTrend contributes slightly negatively over this shared window; it is positive in 2024/2025 and negative in the partial 2023/2026 periods. AlphaVintage has modest average contribution but the largest sleeve loss in the worst book drawdown. The overlay supplies substantial return and variance; it must not be described as neutral alpha. Full yearly contributions are retained in `result.json`.

The earlier saved removal diagnostics reported Sharpe 1.875 without AlphaTrend and 1.791 without AlphaVintage, with removed capital left in cash. Those already-known diagnostics motivate investigation, not retrospective admission or automatic sleeve deletion. Four low-correlated sleeves do not establish fifteen independent qualified mechanisms.

All four sleeve source hashes match the frozen study. The overlay corpus has changed since that study; the strict reproduction check failed before analysis proceeded. The current reconstruction differs in Sharpe by approximately -0.000000144. This is explicitly near-reproduction with refreshed overlay inputs, not exact source reproduction. Current overlay files are frozen here, and the original 1.78462833 result remains preserved. Component contributions reconstruct the current control to machine precision. No allocation variant was evaluated in this phase.

## Next algorithm experiment

`EXPERIMENT_SPEC.json` freezes one causal, weekly combined-book volatility-control candidate: 63 prior daily returns, 5% annualized target, scaling capped at one, no sleeve selection and no parameter sweep. The goal is to test risk-adjusted improvement while retaining at least 90% of control CAGR, with explicit incremental-cost sensitivity. These parameters are a research hypothesis, not optimized results or proof that a risk overlay can generate alpha. The specification is sealed before candidate returns; canonical trial registration is still required before execution.

After this single comparison, resume the distinct-sleeve frontier. Risk scaling adds zero sleeves. A rejected experiment must remain rejected; do not tune repeatedly on this known window.

Limitations: inherited calendar-gap treatment, additive overlay without independent funding evidence, no dated cash benchmark, no COVID/2022 in this common window, and known sleeve provenance/rejection issues. Observed 4.51% drawdown does not establish the owner's maximum-drawdown objective under stress or in the future. The saved study's modeled tail drawdown was much higher. All data were known before this research phase; no untouched validation claim is available.

The owner has now authorized a persistent goal and autonomous continuation between phases. Next action is canonical registration and the frozen candidate/control experiment, with causality and cost checks before interpreting results. Production is unchanged; no improvement or new qualified sleeve has yet been established by this attribution phase.
