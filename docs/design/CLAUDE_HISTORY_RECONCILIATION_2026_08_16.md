# Claude / VS Code history reconciliation — 2026-08-16

## Scope and authority

The local Claude Code project history under `~/.claude/projects/-Users-arhancanli` was reviewed
against the current AlphaForge code, artifacts, databases, launch agents, and production-facing
state.  No separate Canli Capital conversation corpus was found in VS Code workspace/global
storage; the Claude Code history is therefore the available local source.  Chat text is not an
engineering source of truth.  A claim is current only when the running path or a sealed artifact
supports it.

The history contains an old broker credential.  It is not reproduced or used here.  Treat any
credential ever pasted into chat as compromised and rotate it if it remains active.

## Reconciled findings

| Topic | Current classification | Evidence / required action |
|---|---|---|
| Canli positioning | Current | The intended position is a transparent systematic research and engineering operation, not a generic AI product.  Current public redesign follows this direction. |
| Sharpe 2.0–2.5 | Research objective only | It is not a forecast or public promise.  Quality and average correlation bind the feasible frontier; sleeve count alone cannot manufacture the target. |
| Six validated sleeves / book 1.48 | Stale and superseded | The current public state is four sleeves plus a separately disclosed 10% directional overlay.  Historical six-sleeve chat claims must not be restored without present artifacts and gates. |
| AlphaTrend DSR 0.83 | Withdrawn | Later audit found DSR effectively zero; current public copy says evidence is promising but statistically inconclusive. |
| Average sleeve correlation −0.040 | Corrected | Recomputed value was positive, about +0.072 in the historical audit.  Negative value must not reappear. |
| Honest trial count 101 | Stale | Later counts were 127/133 depending on the sealed accounting point.  The live ledger/config is authoritative, not prose. |
| Crypto funding booking | Running-path defect repaired | The `available_at` selector and timestamp cast are pinned by focused tests; first production booking was observed.  Historical public results have not been silently restated. |
| Funding interval metadata | Partially repaired; historical limitation remains | `InstrumentStore` is SCD2 and current venue intervals are ingested.  Stored funding events drive realized backtest settlements directly.  However `FeatureContext.instrument()` selects the version at the window end (or earliest-known fallback) for the whole window, so historical interval metadata is not truly event-time versioned for carry annualization/synthetic label counts.  Do not claim full historical PIT interval lineage until this is corrected and tested. |
| AlphaVintage October 2025 gap | Confirmed and code-corrected; revised returns unopened | October headline/core CPI are absent.  The prior function could reuse an older computable change under a later vintage.  `CORRECTION_ALPHAVINTAGE_MISSING_RELEASE.md` locks a fail-closed adjacent-month rule.  November and December 2025 are unusable for both PCPI and PCPIX.  Revised performance remains unopened pending one fixed-spec re-evaluation. |
| Macro-vintage arrival lineage | Accruing, not funding-ready | The lake refreshed on 2026-08-15 and has six arrival observations.  The history itself says live funding must wait for real forward arrival evidence; do not treat the backtest timestamp convention as proven operational availability. |
| Maker shadow | Passed measurement gate; promotion deferred | Current report: 4.6 days, 1,008 v2 quotes, 990 matured, 90.3% 60-minute fill rate, 55.9% at one minute, +5.33 bps measured maker/taker edge.  It places no orders.  Owner-deferred promotion date is 2026-08-19; do not promote early or loosen the gate. |
| Deribit capture | Repaired on reachable research host | The Mac resolver maps Deribit to unreachable addresses, so local collection remains fail-closed.  Bounded retries and artifact-freshness monitoring now make that explicit.  The research-only collector was installed on the existing VPS, where the public endpoint returned HTTP 200; its first verified run wrote 50 option rows plus BTC/ETH DVOL, the daily 13:00 UTC timer is active, and an atomic line-union mirror added 52 rows locally without touching trading state. |
| Health monitor | Prior board red; exact rerun now green | The 2026-08-15 status recorded only `C7b-suite`, exit 124 after its 900-second timeout.  On 2026-08-16 the exact health-suite command completed unattended at 100% with exit 0, distinguishing the prior incident from an assertion failure.  The persisted board remains historical until the next scheduled monitor run records the recovery. |
| 24/7 sentinel | Deployed, core VPS coverage green | `scripts/sentinel.py` runs every five minutes in a hardened systemd unit.  Its first verified snapshot passed 11/11 checks: five timers, crypto cycle freshness/status, maker-shadow freshness, Deribit freshness, disk headroom, and kill-switch visibility.  It can write only its own atomic status file and cannot place orders or mutate research/trading state.  Remaining expansion: signed-log verification, public-host parity, broker reconciliation, and an independently verified paging channel. |
| Signed live duration | Corrected | Current public-state code says 39 days for the superseded v2 period.  The old 239-day statement must not return. |
| Universe self-healing | Scheduled milestone | Preserve the stated 2026-09-01 evidence milestone; do not infer success early. |
| Earnings-narrative candidate | Return locked | SEC Item 1A corpus completion and exact immediate-predecessor pair sealing remain prerequisites.  No return identity may open before those lineage checks pass. |

## Governing controls carried forward

1. Never spend a trial slot without the declared authority and preregistration.
2. Never deploy real capital, loosen risk gates/caps, edit signed transparency history, or refit
   weights/tilts in sample.
3. Hash complete source/artifact trees for deploy gates; enumerated-directory hashes are not a
   complete publication seal.
4. Enforce preregistration in code and test the branch that actually runs.
5. Keep non-critical network services out of order, risk, and state-persistence critical paths.
6. Treat the 2.0–2.5 Sharpe target as falsifiable portfolio research.  Publish nulls, corrections,
   costs, capacity, search deflation, and correlation evidence with the positive results.

## Immediate sequence

1. Finish and seal the SEC Item 1A corpus, then build exact immediate-predecessor annual pairs.
2. Run the single locked earnings-narrative OOS identity and apply cost/capacity/deflation gates.
3. Complete the fixed-spec AlphaVintage correction re-evaluation and publish the before/after
   correction even if the sleeve loses admission.
4. Keep the repaired Deribit mirror fresh and complete an unattended full-suite run.
5. Build the read-only sentinel and deploy it with explicit freshness/error budgets.
6. Continue no-return feasibility work for differentiated sleeves before requesting any new key.
