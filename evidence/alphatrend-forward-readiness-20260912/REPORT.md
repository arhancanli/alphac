# AlphaTrend forward readiness and sleeve map

**The retained candidate is not ready for forward execution.** We can build its isolated observation recorder now; the audited runner does not yet produce the identity-bound prospective evidence needed to activate it.

This is a September 12 local source/artifact audit, not a fresh broker or remote-host check. Nothing was deployed, no orders or API requests were sent, and no return trial or portfolio reweighting was performed. The experiment union stays at 234.

## Readiness findings

| Gate | Status | Evidence / gap |
| --- | --- | --- |
| Candidate definition and development evidence | AVAILABLE | ec7ec19175ac10a9 frozen; 2x-cost validation passed, still not admission |
| Candidate installed in local production signal path | FAIL | Production SignalService lacks directional_rms; saved WF config has no candidate normalization |
| Fresh complete daily inputs for observation | UNESTABLISHED | All 17 local 2026 ETF partitions end September 10; new received-time input captures absent from audited candidate evidence |
| Targets tied to a pre-outcome decision | FAIL_FOR_CURRENT_PATH | mf_tick refreshes Yahoo history and reruns WF; live_cycle selects latest saved position weights, not a sealed candidate decision packet |
| As-of signal and allocation runtime parity | UNESTABLISHED | Historical reconstruction passed; equity prospective decision-calendar, causal blend-weight updates and persistent risk/cadence parity are not established |
| Independent execution benchmarks and dated borrow | INCOMPLETE | live_cycle records padded order price as decision_price and uses shortability flags; no verified candidate-wide arrival/fee/borrow record |
| New identity-bound append-only observation epoch | NOT_EVIDENCED | No candidate deployment/epoch receipt in the audited source set; historical reruns cannot backfill this record |
| Current account, clock, licensed feed and remote scheduler verification | NOT_RECHECKED | Local source/credential presence only. Earlier SIP/clock failures are dated evidence, not fresh status |

The local saved walk-forward end is **August 25, 2026**, while all 17 local ETF data partitions reach **September 10**. These different cutoffs show that refreshed data do not prove refreshed targets. Remote Frankfurt runtime state was not queried.

Credential files for general, equity and dedicated spot contexts exist. No keys were read or copied. Later restart notes and the preserved dedicated-account verification supersede older missing-credential notes. This audit does not ask for replacement keys or infer present account readiness from file existence.

## Sleeve evidence and mechanism map

| Sleeve / candidate | Status | Overlap implication | Next evidence |
| --- | --- | --- | --- |
| AlphaTrend directional candidate | RETAINED_DEVELOPMENT_NOT_ADMITTED | Trend and directional market exposure; new-candidate cross-sleeve overlap unmeasured | Separate immutable observation epoch and causal as-of runtime parity |
| AlphaMax | LEGACY_REPLAY_PROVENANCE_LIMITATION | Potential momentum and equity exposure overlap with AlphaTrend | Freeze comparable identity/curve provenance before a new synchronized overlap study |
| AlphaVintage | LEGACY_MARGINAL_CONTRIBUTION_REVIEW_REQUIRED | Distinct macro-event input, shared equity execution; candidate-specific overlap unknown | Reconcile exact curve identity and synchronized dates; measure contribution without filling gaps |
| AlphaForge disputed carry | QUARANTINED_FROM_COMPARISONS | Excluded from usable correlation and portfolio performance claims | Keep legacy record separate; do not splice restart returns |
| AlphaForge spot restart | SEPARATE_RESTART_NOT_ACTIVATED_BY_THIS_WORK | Crypto trend is not automatically independent of multi-asset trend | Resolve documented timing/runtime gates; new dated paper epoch only after readiness |

The August 16 lineage registry lists 40 research families: 5 RETIRED_KILLED, 16 NOVEL_ATLAS, 10 ACTIVE_FEASIBILITY, 2 IDENTITY_REDESIGN_REQUIRED, 7 DUPLICATE_OVERLAP. These are novelty/queue labels, not admission findings. Four legacy book names and a separate restart do not establish five qualified independent sleeves.

## What the old overlap numbers can tell us

| Pair | Archived joint-activity correlation |
| --- | ---: |
| AlphaMax / AlphaTrend | 0.210 |
| AlphaMax / AlphaVintage | -0.062 |
| AlphaTrend / AlphaVintage | -0.044 |

These are preserved values from the old 1,061-calendar-day research window ending June 1, 2026. They use the old AlphaTrend construction and source alignment, not the new directional candidate. They cannot certify its diversification. AlphaForge legacy returns are excluded here; no corrected current portfolio Sharpe or qualified sleeve count can be established from this audit.

## Work sequence

1. Build an isolated, append-only AlphaTrend observation recorder. Bind the candidate code/config, point-in-time inputs, received timestamps, decision deadline, exchange calendar and causal weight state before computing and committing each signal. Capture missed/invalid observations explicitly; never reconstruct a past decision.
2. Verify research/as-of signal parity and persistent allocation/risk/cadence behavior on an equity session calendar. Compare a controlled replay with the frozen baseline; do not switch existing broker targets to the new candidate.
3. Collect bounded read-only feed, clock, asset/borrow and account evidence for the chosen observation context. Use existing credentials. Require an independent decision/arrival benchmark and clear feed scope; dated Alphabet diagnostics do not substitute for a current 17-ETF observation check.
4. Freeze compatible AlphaMax and AlphaVintage identities and synchronized return observations before a portfolio-overlap study. Distinguish absent observations from known flat exposure. Do not include disputed AlphaForge history or splice restarts.
5. Resume data-feasibility work on complementary mechanisms. WASDE has original-release timing/lifecycle gaps; Alphabet has quote/borrow/clock gates; FDA/convertible leads still need historical mapping and execution evidence. Prefer closing a specific gap with existing data over buying more data or launching another return sweep.

The next concrete implementation is the observation recorder and its parity tests. It should begin a new prospective epoch only when the required inputs can be captured before their outcomes. A local recorder alone does not provide independent public timestamp proof, mature paper performance or admission.

Owner targets remain Sharpe near 2 and 14+ independently useful sleeves. Existing canonical 1.5 forward criteria and 252/756 calendar-mark maturity rules remain unchanged; they must not be silently applied as 252-session AlphaTrend research rules.

[Machine-readable audit and full family inventory](audit.json). Source snapshots and hashes are included; no secret files are part of this evidence packet.
