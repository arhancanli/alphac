# AlphaMax covariance and holding labels: synthetic integration findings

Four integration tests pass. The raw covariance input contains a false approximately-75% daily return at a4-for-1 split. Raw-open21-session labels contain0.021-log(4) instead of0.021 on a constant-growth synthetic path. Correct reciprocal share-unit adjustment restores both economic series; this does not add dividend entitlement or certify label-release timing.

The actual StrategyContext.bars method requests lookback_bars calendar days. BlendStrategy._close_panel independently constructs a session-count grid. In the synthetic301-session test ending January3 2022, the reader returns only209 populated sessions despite all301 being present in the source; early rows become NaN. Thus the covariance history limitation is not a vendor data gap.

An isolated SessionPriceBasisStrategy helper now reads the exact requested XNYS session range, preserving as_of=decisiontime. It optionally converts stored share ratios in the close panel and preserves real missing observations. Tests show301/301 observed rows when complete,300/301 when a deliberate source bar is missing, correct split returns, and exact raw-price parity when adjustment is disabled. No global strategy/context/labeling code or frozen trial source changed.

Next integrate the opt-in strategy seam and holding-label variant, then freeze controls and separate interventions: session-depth correction, covariance split correction, and split-aware open labels. Preserve the more complete momentum+sigma296/297 control. Do not combine all fixes into an unidentifiable change or restore bad units for favorable returns. Label release/IC availability must also be inspected before claiming causal learning; raw-open timing and dividends have not been certified here.

No historical signal, strategy return or portfolio comparison was computed this phase. Union297 unchanged; no new qualification or deployment. Synthetic proof is implementation evidence, not performance improvement.
