# AlphaForge — Pre-Registration (the A-grade campaign)

**This document is the pre-registration. It is committed to git BEFORE any sleeve backtest
touches the Sharadar lake. The commit hash is the timestamp.** Every deflation statistic
(DSR, PBO, SPA) deflates by the number of configs that COULD have been measured, so the
honest path to passing the gauntlet is to fix a tiny trial budget in advance and measure
each config exactly once. Designed by a 16-agent design→critique→integrate→govern workflow
(run `wrlxqh383`).

## Why this exists

The prior cross-asset book graded **C−**: its 1.51 in-sample Sharpe did not survive the
search that produced it (DSR 0.22–0.48, PBO 0.60, SPA p≈0.20 across N=71–518 configs on a
3-year window). The fix is NOT more tuning (that raises N and worsens the gates). It is:
**(1) pre-register a tight, theory-driven, high-capacity, decorrelated suite; (2) measure
once on ~25 years of wide survivorship-free Sharadar data; (3) keep/kill by criteria fixed
in advance.** Low N + high T + breadth is the only honest route to A.

## Trial budget — HARD LIFETIME CEILING N = 9

Every config ever measured against the Sharadar lake counts toward the deflation denominator.
Slots: (1) Momentum, (2) Value, (3) Quality, (4) BAB, (5) Investment, (6) the combined book
(one fixed combiner rule), (7) crypto-carry satellite (re-measured once), (8–9) two
pre-declared contingency reserves spendable ONLY against a structural trigger logged before
its result is seen. **Measure-once protocol:** no re-runs, no re-windowing, no cadence search,
no sign-flips, no subset search over sleeve combinations, no MVO, no `scheme="static"` in the
deployable path. KILL = exclude; never re-tune a killed sleeve.

## The pre-registered sleeves (each config fixed a priori; N_trials = 1 each)

**Sleeve A — Momentum (12-1), KEEP.** `eq_mom_252_21` (lookback 252, skip 21); top-200 by
30-session median $-vol (hysteresis entry 160 / exit 260); K=30/side dollar-neutral L/S,
rank allocator, equal-weight in leg; QUARTERLY (R=63, horizon_bars=63); constant 12% vol
overlay via trailing-126d realized sleeve vol (Barroso–Santa-Clara), gross cap 2.0×; net of
the conservative equity cost model; purged anchored-expanding WF (train 252 / test 63 /
purge 63). **INCLUDE iff** DSR≥0.95 AND net Sharpe≥0.40 AND rank-IC NW t≥3.0 AND PBO<0.5 AND
SPA p<0.05 AND net SR≥0.30 at $500M AND positive in ≥3 of 4 sub-periods. **KILL** if
DSR<0.95 or net Sharpe<0.40.

**Sleeve B — Value (composite), KEEP.** Equal-weighted z of [B/P, E/P (TTM), S/P (TTM)],
each winsorized 1/99, ≥2-of-3 required; K=30/side dollar-neutral, quarterly; WIDE
survivorship-free universe (small/mid where value lives). **INCLUDE iff** net Sharpe≥0.30 AND
mean-return NW t≥2.0 over 25yr AND rank-IC≥0.015 (t≥2.0) AND net SR>0 in BOTH pre/post-2013
halves (value-winter survival) AND turnover≤200%/yr AND corr-to-momentum≤0 AND it raises the
combined book Sharpe. **KILL** if SR<0.20 or t<1.5 or negative in both halves or mom-corr>+0.2.

**Sleeve C — Quality / Profitability, KEEP.** Equal-weight composite GP/A + ROE + low-accruals
(QMJ/AFP canonical); WIDE top-2000 by 63-session $-vol (hysteresis 1800/2300); K=100/side
(same ~5% selection ratio as K=30 on top-200, fixed by IR=IC·√N), dollar-neutral, inverse-vol
in leg; quarterly. **INCLUDE iff** net Sharpe≥0.30 AND DSR≥0.95 AND PBO<0.5 AND rank-IC NW
t≥2.0 with same sign at h=21 & h=63 AND short-leg viable (≥ −0.10 Sharpe contribution) AND
capacity $500M+ AND positive marginal book Sharpe. **KILL** otherwise.

**Sleeve D — Low-risk / BAB, KEEP.** 252-session beta vs equal-weight PIT-universe market;
long low-beta / short high-beta, K=30/side, **beta-hedged** so ex-ante portfolio beta = 0
(the one Frazzini-Pedersen-mandated deviation from plain dollar-neutral); quarterly.
**INCLUDE iff** beta-hedged return NW t≥2.0 AND DSR≥0.95 AND net Sharpe≥0.35 AND realized
|beta|≤0.1 AND ≥70% capacity retained at $250M AND positive in ≥60% of rolling 3yr windows
AND SPA p<0.10. **KILL** if t<1.5 or DSR<0.7 or SR<0.2 or |beta|>0.2 or positive in <40% of
3yr windows. Grey zone → KILL, not re-tune.

**Sleeve E — Short-term reversal (1-month), EXPECTED-KILL / dropped.** Pre-registered for
completeness; the prior null at this horizon + 20× turnover capacity liability ($150–340M
soft cap) make it an expected exclusion. If it somehow passes, it is a ≤$150M large-cap-tail
satellite, never core. **Critique verdict: drop.**

**Sleeve F — Investment / asset-growth (CMA), KEEP.** Low-asset-growth minus high
(Fama-French 2015 CMA; Cooper-Gulen-Schill), YoY total-asset growth from SF1; K-rank
dollar-neutral on a top-1000 universe, quarterly. **INCLUDE iff** net Sharpe≥0.25 AND
mean-return t≥2.0 AND decorrelated from value/quality enough to add book Sharpe. **KILL**
otherwise. (A fundamental-cluster member — counts partial breadth vs value/quality.)

## The combined book (slot 6 — one fixed rule)

**Stage 1:** `combine_book(scheme="equal_risk")` over the SURVIVING equity sleeves only →
risk-parity weights `w_eq` (PIT, trailing 126d vol, quarterly). Risk parity from theory
(Maillard-Roncalli-Teiletche: the "I cannot forecast which sleeve wins" allocation) — NOT
equal-weight, NOT inverse-var, NOT MVO/static (those are in-sample fits). **Stage 2:** deploy
`scheme="fixed"`, `fixed_weights = {equity_i: 0.90·w_eq[i], crypto_carry: 0.10}`,
`vol_target_ann=0.10, max_leverage=1.5, sleeve_gross={equity:2.0, crypto:1.0},
venue_gross_cap={equity:2.0 (Reg-T, load-bearing), crypto:4.0}, trading_days=365`. Crypto is
a capacity-proportional satellite (the $10M cap binds above ~$100M AUM → its weight decays to
zero, scale-honest). **BOOK PASS iff** DSR≥0.95 AND PBO<0.5 AND SPA p<0.05 AND market-neutral
(|β_SPY|, |β_BTC| t<2) AND realistic worst-DD (sized for ~−24% bear counterfactual now inside
the 25yr window). If it misses, record the HONEST NULL — do NOT re-combine subsets to
manufacture a pass.

## Expected outcome (honest)

**Realistic expected grade: B+ to A−, with a credible (not guaranteed) path to A.** Honest
pre-registered combined-book Sharpe ≈ **0.75–0.85 net** (NOT 1.51): uncorrelated ceiling
√(ΣS²) ≈ 1.08 from conservative priors (mom 0.55, value 0.35, quality 0.40, investment 0.30,
BAB 0.35, crypto 0.60 @ 10%), haircut by realized avg pairwise correlation ρ̄ ≈ +0.13 →
≈ 0.80. A genuine, robust, deflation-surviving ~0.8 Sharpe is an excellent, deployable
result. **Realistic floor: a 2–3 sleeve (momentum + BAB) book at B**, if value/quality don't
replicate on the wide universe.

## Execution steps

0. **Commit + tag this doc (done by this commit) — before any backtest.**
1. Set `configs/equity.yaml` `horizon_bars=63`, quarterly cadence; cost block unchanged. Do
   NOT run the h=21 variant (forbidden — that is the cadence-search that caused the C−).
2. Rebuild the PIT survivorship-free universes from Sharadar TICKERS + SEP (top-200 momentum,
   top-2000 quality, wide value, top-1000 investment). Verify SF1 `datekey` = `available_at`.
3. Measure each sleeve ONCE (slots 1–5) via the single purged WF over ~25yr, net of cost.
4. Apply advance/kill criteria — no tuning. KILL = exclude.
5. Re-measure the crypto carry satellite once (slot 7).
6. Combine ONCE (slot 6) per the fixed rule above.
7. Grade the book against its gates; if it misses, record the honest null + track-record path.
8. Report the 2023–2025 sub-window Sharpe SEPARATELY as a clean OOS check (reported, not used
   to choose anything).
9. Earn the grade forward: ≥6–12 months paper-trading the frozen book before any real capital;
   Phase-8 pre-arm gates (C3/C5/C7/C10) must clear first.

## Honest risks (the priors may not hold)

- Every standalone Sharpe / IC / the ρ̄≈+0.13 matrix are **theory-anchored priors, not
  measurements**; the 25yr WF can falsify any of them. B+/A− is an expectation, not a result.
- VAL/QUAL/INV are +0.2–0.3 correlated (one mispricing axis) → ~2 effective bets, not 3.
- Value-winter / BAB-inversion may KILL value and/or BAB → a 2-sleeve book at B.
- **DSR≥0.95 is demanding even at N=9**: if standalone Sharpes land at ~0.30 not ~0.40–0.55,
  sleeves can fail despite positive economics. Pre-registration guarantees honesty, not a pass.
- **Survivorship/PIT integrity is the single highest-impact risk**: any look-ahead in the
  SF1 `datekey` join would silently inflate value/quality/investment. Must be verified.
- Crypto satellite capacity (~$10M) is a structural fact; above ~$100M AUM the book IS the
  equity core.
- The grade can be an honest null (C/D) if the wide-universe value/quality thesis fails to
  replicate. Pre-registration does not promise A — it promises the grade is search-clean and
  reported as-is, with NO config rescue permitted.
