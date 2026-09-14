# AlphaTrend runner and Alphabet collection

September 12 validation checkpoint: the retained directional candidate passed the single preregistered full-engine 2x-cost scenario. Stressed Sharpe 0.542 versus baseline 0.150; CAGR 2.07% versus 0.45%; maximum drawdown 10.50% versus 12.35%; turnover 8.60 versus 9.68. Both new cost identities remain counted (union 234). Corrected exchange-session exposure analysis gives incremental raw-return intercept 0.59% annually with descriptive interval -0.75% to 1.94%; positive independent alpha is not established. The candidate also underperformed in 2013-2019. Retain frozen for independent/prospective validation and portfolio overlap assessment, not promotion. [Completed validation](artifacts/analysis/alphatrend_directional_validation_20260912/REPORT.md).

September 12 directional-blend checkpoint: hypothesis ec7ec19175ac10a9 (ordinal 232) passes all four frozen development criteria. Sharpe 0.327 -> 0.677; CAGR 1.11% -> 2.63%; maximum drawdown 10.24% -> 9.63%; annual turnover 9.69 -> 8.61. Baseline signal and timestamped equity reproduce exactly. Gross exposure stays about 94.77%, but net exposure rises from 15.86% to 39.01%. Retain for further testing only; no admission or deployment. The full union remains counted at 232. Next: freeze validation of exposure attribution, cost robustness and independent/prospective evidence before measuring further variants. [Completed directional comparison](artifacts/analysis/alphatrend_directional_20260912_attempt2/REPORT.md).

September 12 forecast-audit checkpoint: exact archived forecast reconstruction and 593 sealed files verified. On 247 sampled dates, mean cross-sectional Rank IC is 0.0222 for the standardized blend and 0.0362 for expected returns; both descriptive 95% intervals include zero. Cross-sectional centering changes the pre-centering trend sign in 17.15% of complete audited observations. The next justified experiment is a separately registered direction-preserving blend with existing settings fixed. No new portfolio trial or promotion occurred; strategy selection union remains 231. [Full forecast audit](artifacts/analysis/alphatrend_forecast_audit_20260912/REPORT.md).

September 12 checkpoint: the cash-retention variant is also rejected under the unchanged scenario. Sharpe 0.218 versus baseline 0.327; CAGR 0.10% versus 1.11%; maximum drawdown 1.86% versus 10.24%. Mean marked gross exposure was only 0.89%. [Completed comparison](artifacts/analysis/alphatrend_cash_retention_20260912/REPORT.md). Both trials remain counted; neither was deployed.

September 11 checkpoint: the registered development comparison is now complete. The cost-filter candidate is **rejected under the frozen scenario**: Sharpe 0.327 → 0.213 and maximum drawdown 10.24% → 35.14%, despite lower turnover. [Completed report](artifacts/analysis/alphatrend_cost_development_20260911_attempt2/REPORT.md). Earlier pending-status notes below are retained as history. Untouched validation and admission are still not established.

The optional cost filter now runs through `WalkForwardRunner` and the existing
`mf_gauntlet.py` command via `--trend-cost-policy`. `--trial-reservation` passes
through to canonical registration. Its full dated, side-specific cost policy and
hash enter trial identity, saved run configuration and the input snapshot. The
snapshot retains both original and filtered expected returns. Default runs keep
their existing behavior. No production profile or deployed job was changed.

A pre-return correction replaces the draft's 10-session holding assumption with
the signal configuration's 21-session horizon, annualized on 252 sessions.
The rebalance cadence can remain 10 sessions. This follows the existing Grinold
expected-return convention; it does not assert that positions exit after exactly
21 sessions. The cost gate also preserves the baseline units check and tail clipping.

The fixed modeled cost components total 12 basis points per round trip: twice
1 bp commission + 3 bp half-spread + 2 bp latency. That is **not the complete
cost**: impact needs trade size, lagged volume and volatility; short borrow and
financing also need explicit treatment. The legacy 50 bp annual borrow assumption
is not dated security-level lending evidence. The configured IC of 0.02 remains
a model assumption; this work does not establish its empirical calibration.

The [readiness record](evidence/trend-cost-runner-20260911/readiness.json) binds
those findings to source files. A complete candidate cost policy and a verified
untouched evaluation interval remain missing. No new market-return trial was run,
no Sharpe improvement is claimed, and the full historical experiment union must
carry forward when the new trial is reserved. A comparison on already-inspected
data must be labelled a development comparison rather than untouched validation.

## Alphabet

The bounded collector saved five observation packets, with sample hashes verified:

| Explicit credential/feed context | Quote response | Result |
| --- | --- | --- |
| General paper / SIP | 403 | Stopped after first denied request |
| General paper / IEX | 200 in all three rounds | No pair passed the age/skew diagnostic |
| Equity paper / SIP | 403 | Stopped after first denied request |

Both symbols continued to report easy-to-borrow status. IEX quote diagnostics
included ages around 1.8 seconds, pair skew of 4.9 seconds, and negative apparent
ages of roughly 0.3–0.4 seconds. Negative ages are unresolved timing evidence;
this collector does not calibrate the host clock. None of these samples is
execution clearance. Quote-age rules are diagnostics, not proof that a quiet
standing quote is invalid.

[Alpaca documents](https://docs.alpaca.markets/us/reference/stocklatestquotes-1)
SIP as covering US exchanges and IEX as a single-exchange feed. The collector
explicitly requests a feed and never falls back silently. Separate IEX observations
were collected only after preserving the SIP denial. Asset requests are sequential;
this is not an atomic quote/borrow snapshot or a synchronized trade decision.

No orders, locates, paid data purchases, account changes or background schedulers
were made. This was bounded collection, not continuous monitoring. Additional
Databento credits do not establish Alpaca SIP access. The next Alphabet data step
is to resolve consolidated quote entitlement or select another licensed feed,
and establish clock calibration before collecting decision-quality observations.

## Verification

75 focused runner, cost-policy, optimizer, snapshot and golden-master tests pass.
One optional real-lake funding test is skipped because its lake is absent in this
checkout. Changed Python files pass Ruff. Synthetic results validate the wiring
and accounting behavior; they do not establish improved market performance.
