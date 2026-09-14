# Saved crypto execution-cost diagnosis

Normal:4,360 fills,8,815.50USDT explicit fees,17.631millionUSDT traded notional and20,557.10USDT funding. Stress:12,863 fills,15,602.29USDT explicit fees,15.602millionUSDT notional and16,906.61USDT funding. These are sums over saved paths with different evolving equity, not a constant-capital fee counterfactual. Spread, impact and latency are also embedded in fill prices; explicit fees are not total execution cost.

Both runs have179 scheduled rebalances and zero full halts, but half-gross bars increase from1,560 to6,366 under stress. Every fill has target_weight reason. The strategy re-emits half-scaled targets on non-rebalance half-gross bars; the engine permits risk-reducing orders below the ordinary no-trade band. This is a concrete possible source of maintenance trading. The counters do not establish that all extra fills arise from this mechanism or that suppressing them improves performance.

Next: attribute saved fill events to risk state and scheduled versus maintenance decisions before selecting one bounded cost-aware maintenance experiment. Preserve immediate de-risking and halt exits; do not relax risk controls or change fees to manufacture a gain. No new strategy returns or identities were computed here.
