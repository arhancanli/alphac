# Combined horizon coverage: missing sleeve histories identified

The common July7,2023–June1,2026 window is constrained by AlphaMax, whose retained equity begins July6,2023. Crypto carry begins February8,2022. The frozen source hashes match the prior combined study; these dates are observed file boundaries, not inferred instrument-inception dates.

| Retained source | Q12020 missing required marks |2022 missing required marks|
|---|---:|---:|
| CPI/Vintage legacy probe |0|0|
| Crypto carry |91daily|38daily|
| AlphaMax |62XNYS|251XNYS|
| Original managed futures |0|0|
| Positive-target Trend |0|0|

Both crypto carry and AlphaMax also lack the explicitly required prior mark for the first crisis return. All five inspected curves cover scheduled marks and their predecessor for the existing1061-day combined window. Crypto is checked at daily last-available-mark resolution, not for complete intraday bars. No prices or profits were inferred for absent history.

An opt-in research_horizon validator now accepts explicit expected calendar marks plus the exact required predecessor. It rejects unordered/duplicate timestamps, missing internal marks and a distant old mark masquerading as the predecessor. Seven tests pass. The audit invokes this validator on all sources and horizons. It is not retrofitted into frozen historical runners or represented as production enforcement.

Observation coverage is necessary, not sufficient: the CPI/Vintage input is a legacy killed probe with separate provenance/admission issues, and AlphaMax's fresh-input reproduction remains unresolved. The result cannot certify those sleeves merely because dates exist. Original source methods and revised current inputs must not be silently spliced.

## Next executable step

Assess the retained raw data and frozen walk-forward configurations for extending AlphaMax and crypto carry before any new return run. Missing saved outputs alone do not prove raw data is absent. A preregistered historical extension must keep causal universe membership, signal warmup, execution/cost assumptions and input lineage explicit; it cannot count zero padding as crisis performance or call inspected historical data untouched OOS. Keep qualification and new-sleeve work separate. No new return identity; union273; goalactive.
