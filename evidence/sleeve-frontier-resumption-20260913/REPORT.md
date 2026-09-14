# Sleeve frontier resumption — September 13, 2026

Goal remains active: combined net excess Sharpe >2, maximum drawdown <=11% over frozen evaluation/stress horizons, and >=15 economically distinct qualified sleeves. No goal threshold is established by this checkpoint.

## Results

- **Pre-FOMC access unchanged.** A bounded authenticated historical SPY quote request for 2015-12-29 returned HTTP 403 / NOT_AUTHORIZED. Retained `fomc-access-recheck.json` contains request scope and sanitized response metadata; no prices or credentials were retained. This is evidence about that access route, not proof that historical quotes do not exist. Do not rerun without an entitlement/source change.
- **EIA access recovered.** The existing locked collector now obtained 100 actual-demand/day-ahead-forecast sample records across PJM, ERCO, MISO and ISNE from the start of the 2019–2025 window. All eight series start at 2019-01-01T00 and contain required schema fields. The API reports 490,606 matching rows; that total is not downloaded or audited coverage. The 100 sampled identity keys are unique, all eight series are present, and the raw-response SHA-256 independently matches the collector result.
- **Electricity remains DATA_GATED.** The sample lacks explicit forecast issue/vintage timestamps. Full historical missingness/revision auditing, temporal interpretation and operational NOAA vintages remain unresolved. The existing protocol also requires exact-contract executable market history and broker support. Source availability alone does not permit a return experiment. Do not download the entire latest-state panel to pretend to solve the vintage blocker.
- **Two other existing families inspected, not restarted.** The customer–supplier v1 extraction failed its frozen prevalence gate (106/300 versus at least 50%) and needs separately declared, independently labeled v2 validation. Stablecoin direct-redemption feasibility requires documented entity eligibility, historical depth and operational settlement evidence. Neither supplies a ready qualified sleeve; old failures remain intact.

## Accounting and next work

Zero new return trials, zero sleeves admitted, zero production changes. The completed trial union remains 242. The prior weekly volatility-control rule remains rejected: historical raw Sharpe gain was about 0.012 against its frozen +0.10 requirement. Its improved observed drawdown does not override that result.

This checkpoint clears one obsolete source-access blocker but does not improve measured portfolio performance. Continue with a bounded inventory of already retained executable data and event identities to select one attainable distinct-mechanism development experiment. Explicitly distinguish exploratory development from qualification; do not repeatedly probe the parked routes or relax their historical protocols. If no source-qualified distinct mechanism is presently runnable, investigate an explicitly new combined-book allocation hypothesis using retained components, preserving the existing baseline and all costs/limitations, instead of spending another phase on unchanged access failures.

## Reproduction

`eia-collector.py` is an exact copy of the existing source collector. Run with the project Python and `--raw` / `--result` pointing to a new directory; exit 1 means DATA_GATED, including a successful source collection with unresolved gates. The recorded run used the default public DEMO_KEY. Responses are mutable: a fresh request is a new observation, not byte-for-byte reproduction of this snapshot. `checksums.json` binds the collected source, collector, result and sanitized FOMC evidence. No strategy returns were calculated.
