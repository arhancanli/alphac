# Crypto scheduled versus risk-maintenance fills

All40 retained legs matched replayed risk-state and rebalance counters exactly. Every fill joined a unique issued order and decision; no fill came from a normal-hold decision. Skipped-order rows use empty IDs and are excluded from the issued-order join. The initial failed duplicate-ID check and script are retained in the original evidence directory; no strategy returns were recomputed.

Normal: scheduled1,662fills/8,712.10USDTfees/17.4242millionnotional; half-gross maintenance2,680fills/63.36fees/126,720notional; immediate half-risk transitions18fills/40.04fees. Stress: scheduled1,650fills/14,613.17fees/14.6132millionnotional; maintenance11,193fills/820.37fees/820,373notional; transitions20fills/168.75fees.

Maintenance explains8,513 additional fills, offset by12 fewer scheduled and2 more transition fills (net8,503). But it represents only5.26% of stress fees/notional; scheduled decisions account for93.66%. Maintenance reductions below the ordinary band are common; do not infer that their suppression materially fixes the much larger scheduled cost burden. Explicitfees omit spread/impact/latency embedded in prices, and different evolving paths prevent treating these totals as a fixed-NAV fee counterfactual.

Source inspection shows RankEqualVolFallback explicitly ignores prior weights and costs: optimizer.py documents that it never trades off turnover. The portfolio turnover_max0.10 setting is an MVO constraint, not an enforced bound for this rank allocator. This is a research architecture choice, not evidence that simply toggling MVO improves returns. Existing MVO/turnover experiments must be reviewed before registering one new scheduled-turnover candidate.

Decision: do not spend a return trial on maintenance-only suppression based on fill counts. Preserve immediate risk transitions and full-halt exits. Focus next on scheduled turnover, using the10-session AlphaMax provisional reference and unchangedTrend for combined normal/stress evaluation. No qualification, new sleeve or strategy-return identity is claimed by this attribution.
