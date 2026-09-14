# Existing corporate-action repair route for AlphaMax

Located retained Sharadar dividend-basis authority, a versioned corrected lake and its post-build validation in the main repository. The source report's global decision remains CORPORATE_ACTION_VALIDATION_FAILED_SPLIT_BOUNDARIES; this work does not rewrite it or claim a global pass.

All984available2020–2022price partitions for the333active-window AlphaMax names match the current lake exactly on instrument ID, timestamp, OHLC, volume, quote volume, trade count and quality flags. Ingestion timestamps were deliberately excluded from this economic-field comparison; files are not byte-identical across current and corrected lakes. Both file hashes are retained.

The corrected source report records a passing dividend-price consistency gate. Its split-failure list has20events intersecting these names, all before2020; none lies in2020–2022. This is a scope intersection of retained validation evidence, not a fresh global corporate-action validation or historical availability proof. The older events must still be checked against the actual signal warmup dependency interval before any replay clearance.

The AAPL example demonstrates why the repair matters: current2020pre-split dividend cash fields0.1925/0.205/0.205 become0.77/0.82/0.82 in the corrected dataset, while the post-split0.205 remains unchanged. The raw price rows retain the split price boundary. This example describes the retained datasets; source authority and its assumptions are carried separately rather than inferred from price ratios alone.

No lake mutation, new corporate-action formula, strategy return or trial identity. The grid audit is complete; replay readiness remains false pending exact warmup dependencies, metadata, applicable split handling and an explicitly frozen corrected-input protocol. The audit script retains one E501 long descriptive-string warning; it executed successfully. Do not relabel the current-input extension as an exact legacy replay or discard the preserved original-input mismatch.
