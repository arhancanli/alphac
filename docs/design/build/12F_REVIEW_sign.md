# Phase 12 — SIGN / IDENTITY REVIEW

> Reviewer role: **SIGN / IDENTITY REVIEWER**. Scope: actually RUN (not just trust
> mypy/tests) the three load-bearing properties — (1) OFF == identity byte-for-byte,
> (2) the gate never flips sign through the full runner on mixed-sign non-constant-`|size|`
> input, (3) `cs_zscore` is never called after gating. Verified against the working tree
> on top of HEAD `7039a1a`.

## Verdict: PASS

All three mandated properties hold under live execution on a synthetic lake. The gated
backtest RUNS end-to-end (real HMM fit on ≥730 daily obs + per-leg meta-model). No
runtime bug found in `walkforward.py`. No code change was required.

---

## What was RUN (not just type-checked)

Standalone harness drove the **actual `WalkForwardRunner.run`** and the runner's exact
gate entry point `gate_signal_frame` over a tiny synthetic lake (6 instruments —
`_min_members=5` requires ≥5 cross-sectional members or the `cs_zscore` blend NaNs every
row; 2 directional CS-momentum alphas; ~4 200 hourly bars; 2–3 tiled legs; 760 synthetic
daily-BTC rows so the **real** `RegimeHMM.fit` exercises, not just the identity fallback).
A deterministic `dsr_fn` stub was injected only to bypass the tiny-fixture zero-variance
DSR guard (the same idiom the shipped integration tests use); it does not touch the
sign/identity paths.

### P1 — OFF == identity byte-for-byte (D7)
- `run(ml=False, regime=False)` equity is **byte-identical** with vs without a
  `daily_btc_reader` attached (`equity.equals(...)` True).
- OFF `config` carries **no** `ml`/`regime` keys.
- OFF `validation.to_json_obj()` is identical between the two runners and **omits** all
  four Phase-12 gate keys (`variant`/`gate_inactive_frac`/`baseline`/`clears_baseline_gate`),
  so the OFF `walkforward.json` is byte-identical to HEAD. Confirmed in code at
  `ValidationReport.to_json_obj` (L292): the gate block is emitted only when
  `variant != "blend" or baseline is not None`.
- The pre-Phase-12 HEAD-behaviour pins still pass: `test_walkforward_equivalence.py`
  (compute-once-and-slice equivalence) and `test_mu_contract.py` (next-open fill discipline).

### P2 — the meta gate SCALES, never FLIPS (D1 / leakage #1)
Run through `gate_signal_frame` (the runner's real per-leg call) on a genuinely mixed-sign
blend (12 527 positive / 12 385 negative finite rows) with a **non-constant** `|size|` stub:
- **0 sign flips** across 24 192 finite `mu_ann` rows.
- `|mu_ann_gated| ≤ |mu_ann_blend|` everywhere (magnitude-only shrink).
- 24 192 rows had magnitude actually moved (non-vacuous — the gate is not silently identity).
- the reported `alpha_blend` column is kept **ungated** (`gated[alpha_blend].equals(...)` True);
  the gate's entire effect lives in `mu_ann`.

**Adversarial hardening (stronger than the spec asks):** a deliberately malicious stub whose
`bet_size` returns the **opposite** sign of `side` still produced **0 sign flips** and
`|out| ≤ |in|` everywhere. Sign-safety does **not** rely on the model behaving — the hard
guard is the `.abs()` in `gate_signal_frame` (L299) applied to `meta.bet_size(...)`. The
seam itself is also sign-safe by construction: `bet_size_from_prob` returns
`sign(side)·magnitude`, `magnitude ∈ [0,1]` (`ml/model.py` L618-619).

`apply_regime_gate` independently verified: cold-start hours → `G=1.0` (never NaN), the
single backward `merge_asof(allow_exact_matches=True)` keys on the day-`D` `ts_open` with
the day-open boundary matching, `G=0.3` shrinks exactly, all-1.0 `g_series` (IdentityRegime)
returns the input **exactly** (`out.equals(in)`), 0 sign flips, `|out| ≤ |in|` everywhere.

### P3 — `cs_zscore` is never called after gating
- `grep cs_zscore` over the full gated chain (`gating.py`, `features_serve.py`,
  `walkforward.py`, `sizing.py`): the only hits are the **two docstring sentences** in
  `gating.py` (L18, L136); **zero** hits in code in any of the four modules.
- `gating.py` imports from `blending` **only** the string constant `ALPHA_BLEND_COLUMN`
  (L51) — never `blend` or `cs_zscore`. No gating function body references `cs_zscore`
  (verified by source inspection of `gate_signal_frame`/`apply_meta_gate`/`apply_regime_gate`).
- The single real `cs_zscore` call lives in `blending.py:423` (`Ã = cs_zscore(A)`), which
  is the blend step strictly **upstream** of the gate. `gate_signal_frame` receives the
  already-blended `[alpha_blend, mu_ann]` frame and only multiplies `mu_ann` by `|size|·G`
  — no re-standardisation. The exact bug leakage #1 killed (re-z-scoring after the gate,
  which could subtract a non-zero cross-sectional mean and flip a small-`|size|` positive
  name negative) is structurally absent.

### Extra (end-to-end RUN confirmation, beyond the strict sign/identity remit)
- `run(ml=True, regime=True)` completed with `variant="ml+regime"`, a real HMM fit, gated
  equity all-finite and stitched on the same OOS grid as OFF, a `baseline` companion
  attached, and `ml`/`regime` keys present in `config` (D6).
- The IdentityRegime cold-start fallback (50 daily rows < `MIN_FIT_DAYS=730`) does **not**
  crash and records `gate_inactive_frac=1.0`.

## Static / suite state
- `ruff check` + `mypy --strict` clean on `gating.py`, `features_serve.py`, `walkforward.py`.
- Full Phase-12 suite green: 25 unit (`test_gating`, `test_feature_serve_parity`) + the
  six integration files (`test_gates_default_off_identity`, `test_meta_gate_scales_never_flips`,
  `test_regime_gate_no_same_day_leak`, `test_walkforward_full_pipeline`,
  `test_experiments_honest_trial_count`, `test_cli_gated_flags`).

## Notes / non-blocking observations
- The brief's "5 integration tests not yet written" is **stale**: six gated integration
  test files already exist on disk and pass, including the two that pin P1 and P2
  (`test_gates_default_off_identity.py`, `test_meta_gate_scales_never_flips.py`). Both
  carry explicit anti-vacuity guards (mixed-sign + ≥20 finite rows). My independent harness
  corroborates them through the same `gate_signal_frame` entry point rather than re-using
  the test scaffolding.
- Two `assemble_meta_features` definitions coexist (`signals/gating.py` and
  `signals/features_serve.py`); the runner and `_assemble_leg_features` use the
  `features_serve` one, and `gating.py` re-exports its own. They are behaviourally
  equivalent for the sign/identity properties. Not a sign/identity concern; flagged only
  for the dedup reviewer.
