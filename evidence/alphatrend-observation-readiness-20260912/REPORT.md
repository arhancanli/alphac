# AlphaTrend observation readiness and AlphaMax reference recovery

The bounded read-only check establishes daily-data access, but the corrected AlphaTrend candidate is not ready for an operational observation epoch or execution. AlphaMax's previously missing reference legs are now recovered and verified; exact strategy replay remains unresolved.

## Fresh AlphaTrend observations

20 GET requests using the existing equity paper credentials completed on September 12, 2026 around 05:11 UTC: 19 HTTP 200 responses and one 403. There were no retries, orders, locates, credential changes, clock adjustments or account mutations.

| Check | Result | Meaning |
|---|---|---|
| Completed-session SIP daily bars | 17/17 valid for September 11; no pagination remaining | Existing access supports a bounded daily input capture |
| Asset identities / active tradability | 17/17 matched and tradable | Current paper asset observations only |
| Shortability | 14/17 shortable / easy-to-borrow | FXE, FXY, USO are hard-to-borrow and not shortable |
| Latest SIP quotes | HTTP 403 | Latest-quote entitlement is unavailable in this credential context; no fallback was used |
| Host clock | Failed offset/uncertainty gate | One fresh SNTP sample exceeded the configured 50ms offset or 100ms uncertainty bound; the helper did not retain the raw numerical sample |
| Market session | Closed | Broker clock reports next open September 14 at 09:30 New York time |
| Corrected prospective journal / producer | Missing | Legacy journal pins ec7ec19175ac10a9; corrected candidate is 59901461092dd7a6 |

Daily-bar access and latest-quote access are distinct. The quote denial is not evidence that daily observations require another subscription. Hard-to-borrow flags are a current execution constraint, not historical borrow evidence and not a reason to invent historical missing returns. No current model targets were generated, so this check does not assert the candidate currently wants to short those instruments.

These are newly received feasibility records, not a reconstructed prospective performance history. Raw daily bars are preserved locally with response hashes and request/receipt timestamps. Full causal-prefix readiness, adjustment consistency with the frozen historical inputs, provider-history revisions, persistent portfolio state, independent time evidence and a producer bound to the corrected candidate remain unresolved. A local request time does not independently authenticate when a vendor value became available.

## AlphaMax reference recovery

The existing private reference folder contains 113 files, including all 12 legs. The five originally sealed root files still match their manifest hashes. All 729 per-leg equity rows concatenate exactly to the preserved root curve, with no duplicate timestamps. Leg boundaries, root final-equity metadata and cash continuity also match. Orders, fills and positions are retained alongside each leg.

This supersedes the older report's assertion that reference leg outputs are unavailable. It proves current internal consistency, not when those files were captured or that the full original historical input/source environment is recovered. The original publication receipt remains untouched.

The earlier fresh-vendor replay is still different from the reference. Its temporary workspace was destroyed by the old runner. A bounded search of 634 non-leg equity artifact paths (hashing files below 100KB) found no copy matching the recorded replay equity hash. This is not a filesystem-wide absence proof. The published comparison still reports a maximum equity difference of $574.69, exact configuration/timestamps, and different equity, leg results and validation. Those facts do not distinguish vendor revisions, historical membership differences and missing dirty-source changes as the cause.

The acquisition inventory receipt matches its sealed hash. The 79,915 raw input files were not all rehashed in this phase. The 58-session historical entitlement gap remains a documented limitation. No new replay or new return trial was run.

## Concrete next work

1. Build the corrected-candidate observation producer with its own immutable binding, full input prefix and explicit state recovery. Validate clock quality on the actual intended observation host before activating the epoch. Daily-bar access can support development while latest execution benchmarks remain separately constrained.
2. Preserve a complete AlphaMax diagnostic replay directory before workspace cleanup. Bind code, inputs, environment, current trial accounting and the recovered reference; compare the first differing session, positions, orders and fills. Do not overwrite the reference or present a new replay as untouched validation.
3. Resolve the full signed ETF slate's executable instruments and dated borrow evidence before paper execution. A changed long-only/borrow-constrained strategy would require a separately registered comparison.

The experiment union remains 238. No portfolio was reweighted and no performance claim was upgraded. The Sharpe-near-2 / 14+ qualified sleeves objective remains unmet. Targeted tests and verification receipts are stored beside this report.

Files: `protocol.json`, `clock.json`, 20 individual HTTP observations, `result.json`, `verification.json`; AlphaMax evidence is in the sibling `alphamax-reference-recovery-20260912` directory.
