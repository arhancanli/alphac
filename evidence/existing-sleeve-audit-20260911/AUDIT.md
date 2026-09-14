# Existing-sleeve improvement audit

Archived evidence reviewed on 2026-09-11. No new return trial, admission, portfolio reweighting or broker action. Source bytes and SHA-256 hashes are frozen in this packet; freezing a summary does not independently validate its underlying data.

## What to fix first

1. **AlphaForge:** quarantine the disputed carry history in comparisons. The correction packet is not a validated replacement track record. The separate spot paper restart still needs runtime readiness and a clean epoch.
2. **Shared execution measurement:** reuse the recent session's offline prototype. The equity order path still substitutes a padded limit for decision price. Capture independent decision/arrival benchmarks with verified feed, market and receive timestamps, cumulative fill observations and fee completeness. Preserve missing values; do not backfill a limit price as a market benchmark. Prototype integration is unfinished and has not been deployed.
3. **AlphaTrend:** diagnose signal construction and allocation before tuning again. The existing family has 21 hypothesis identities and zero artifact-era gate passes. The table below exposes previously tested variants; their trial history must carry forward.
4. **AlphaMax:** the fresh-input author replay does not exactly reproduce the preserved curve. Freeze prospective inputs and evaluate a new epoch; the replay cannot replace the historical record or count as independent replication.
5. **AlphaVintage:** low standalone Sharpe alone does not justify removal. The old removal comparison includes disputed AlphaForge returns, so its book Sharpe and drawdown changes cannot settle today's allocation.

## Historical comparisons

The full-history and common-window columns use different periods. They are historical simulation summaries, not forward paper or funded performance.

| Sleeve | Full-history Sharpe | Original common-window Sharpe |
| --- | ---: | ---: |
| AlphaMax | 0.907 | 0.759 |
| AlphaTrend | 0.327 | -0.199 |
| AlphaVintage | Not in cost packet | 0.197 |

AlphaTrend's first-order commission plus modeled spread/latency burden is 0.125 Sharpe points. Adding it back yields approximately 0.451; this is not an achievable cost saving or a true gross Sharpe because impact and compounding are not isolated.

Historical pair correlations, measured on jointly active days:

- AlphaMax / AlphaTrend: 0.210.
- AlphaMax / AlphaVintage: -0.062.
- AlphaTrend / AlphaVintage: -0.044.

Stress samples in the source packet are only 14–16 common days. Neither those samples nor long-history family proxies establish reliable tail diversification.

## Previously completed AlphaTrend variants

These are not a new selection contest. Windows and instruments differ; the real-futures variant has fewer observations. All source artifact hashes were checked against the family packet.

| Existing variant | Observations | Sharpe | Annual turnover | Gate pass |
| --- | ---: | ---: | ---: | --- |
| mf_252 | 5132 | 0.182 | 4.93 | False |
| mf_trend | 5132 | 0.263 | 6.44 | False |
| fut_real2 | 3515 | -0.238 | 8.97 | False |
| mf_rb5 | 5132 | 0.278 | 12.31 | False |
| mf_rb10 | 5132 | 0.311 | 9.39 | False |
| mf_126 | 5132 | 0.175 | 5.47 | False |

## Next algorithm diagnostic

Use the existing frozen AlphaTrend baseline to attribute losses by instrument, signal horizon, rebalance event and risk allocation, retaining the entire tested family denominator. First verify daily curve, fill and input bindings. Report missing attribution inputs instead of reconstructing them silently. Diagnostic results may motivate one explicit construction change; reserve its trial and unseen evaluation interval before inspecting new returns. Do not present a rebalance-frequency sweep or a switch to futures as an untested idea.

Alphabet share-class research remains parked pending dated security-level borrow and defensible execution inputs. Quote/status feasibility is not proof of short availability or profitability. No new data purchase was made.

The Sharpe-2 and 14+ sleeve targets remain unproven. This packet supplies repair priorities, not evidence that performance has improved.
