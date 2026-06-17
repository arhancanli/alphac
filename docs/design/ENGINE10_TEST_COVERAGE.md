# ENGINE10 — Test-Coverage Audit

Read-only audit at HEAD `dfdf515`. Dimension: **Test-Coverage** — property-test and
golden-master coverage, the equities path, mutation-test candidates, and the
deployed-path parity / truncation-invariance fixtures. Verdict: **8.5 / 10**.

The crypto-perp path is pinned to an institutional bar: 2030 test functions, a
hand-arithmetic golden master, an exact batch-vs-live parity + truncation harness
with a deliberately-broken control, and a deployed-path bit-identity test. What
separates it from a true 10/10 is concentrated in three corners: (1) the **equities
read-path is structurally untestable end-to-end** because the deployed path it would
test does not exist yet (no calendar-aware engine grid, no `corporate_actions` read
method) — so its load-bearing PIT-adjustment invariant is verified only on a hand-built
fake; (2) **no coverage measurement and no mutation testing** anywhere, so "2030 tests"
is an unaudited number and the assertion-strength of the suite is unknown; (3) the
**numerically critical estimators (covariance, the validation arsenal) and the
real-money pre-arm gates have zero invariant pins** — example-based tests only, no
property tests, no failing-as-spec guards.

---

## 1. What a 10/10 engine has on this axis

- **Coverage is measured and gated.** `--cov` in CI with a floor; branch coverage on
  the load-bearing modules at ~100%; the number is a fact, not a vibe.
- **Mutation testing on the math core.** mutmut / cosmic-ray over costs, optimizer,
  covariance, ledger, the validation arsenal — proving the assertions *catch* a
  sign-flip or off-by-one, not just that the line executed.
- **Every estimator's mathematical invariant is property-pinned**, not just sampled:
  covariance PSD + symmetry + shrinkage∈[0,1]; optimizer constraint-satisfaction
  (present); DSR/PSR bounded in [0,1] and monotone in trials/skew/kurtosis; PBO ∈ [0,1]
  and = 0.5 on pure noise.
- **The deployed path is the tested path, on every asset class.** Equity factors run
  through the *real* engine + reader + context on the *real* session grid against a
  planted split — not a `_FakeCtx`.
- **Deferred real-money work has executable spec guards** (xfail / `@pytest.mark.skip`
  pinned to a TODO) so a fix flips a red test green; the checklist lives in CI, not a
  memory note.
- **Golden masters are stored artifacts** with an explicit regen story, so a numeric
  drift anywhere downstream is a diff, not a silent re-derivation.

---

## 2. Concrete gaps in OUR engine

### G1 — Equities deployed read-path does not exist, so it is untestable end-to-end  **[BLOCKER for the equities sleeve; HIGH overall]**

The equity sleeve's load-bearing correctness gate is PIT split/dividend adjustment
(`adjusted_close`, `equity_price.py:143`). But the path that would *serve* it is
absent in two places:

- `FeatureEngine` hardcodes `ANCHOR_TIMEFRAME = Timeframe.H1` and builds its grid with
  `expected_bar_opens(start, end, tf)` for both `compute_history`
  (`features/engine.py:87,97`) and `compute_asof` (`features/engine.py:126`). There is
  **no calendar-aware / D1 / XNYS-session grid path**. The XNYS calendar
  (`core/calendar.py:177`) is fully unit-tested in isolation (`test_calendar.py`,
  holiday membership) but the engine never consults a calendar to build the grid — so
  equity factors in tests run on a **1h grid** (`test_factors_equity_price.py`:
  `start=T0 + 22*HOUR`), not the daily session grid they will run on in production.
- `PITDataReader.corporate_actions` and `FeatureContext.corporate_actions` **do not
  exist** (grep returns nothing in `data/store/reader.py` and `features/context.py`).
  `_adjusted_close_panel` (`equity_price.py:270`) therefore does
  `getattr(ctx, "corporate_actions", None)` → `None` → **returns the RAW close panel**.
  Every equity price factor on the live engine is, today, *silently unadjusted*.

Consequence for coverage: the entire PIT-adjustment invariant is verified only by
(a) the pure `adjusted_close` function on a stand-alone DataFrame
(`TestAdjustedClosePIT`, strong) and (b) a hand-built `_FakeCtx` that fabricates a
`corporate_actions()` method (`test_factors_equity_price.py:479`). There is **no test
that drives a split through the real reader → real context → real engine on the real
session grid**, because none of those equity pieces are wired. The one truly
load-bearing equities invariant ("a 2:1 split must not print as a -50% momentum
return *on the deployed path*") is unpinned at the integration level.

### G2 — No coverage measurement and no mutation testing anywhere  **[HIGH]**

`pyproject.toml:83` `addopts = "-q --strict-markers -m 'not network'"` — **no
`--cov`**. CI (`.github/workflows/ci.yml:86`) runs bare `uv run pytest`. There is no
`mutmut`/`cosmic-ray` config (grep clean across `pyproject.toml`, `.github`). So:
"~2500 tests" is an unmeasured claim — there is no line/branch coverage number, no
floor, and no proof that any single assertion would *fail* under a mutated operator.
For an engine making capital decisions, an unmeasured assertion-strength is exactly
the corner a top shop closes.

### G3 — The numerically critical estimators have NO property tests  **[HIGH]**

39 `@given` property tests exist, well-placed on the *time/accounting* invariants:
bar arithmetic (`test_bar_arithmetic.py`, 10), calendar (`test_calendar_properties.py`,
11), ledger equity-decomposition + funding antisymmetry (`test_ledger_properties.py`,
4), resample OHLC laws (8), HMM producer-lag/no-leak (3), and optimizer
constraint-satisfaction (`test_optimizer.py:455,496`, 2). But the estimators where a
silent numerical bug is most dangerous have **zero** `@given`:

- **Covariance** (`portfolio/` EWMA + Ledoit-Wolf): `test_covariance.py` has 0 `@given`
  and no PSD / symmetry / shrinkage∈[0,1] / "shrinks toward target" invariant — only
  example matrices. A non-PSD covariance silently corrupts every MVO solve downstream.
- **The validation arsenal**: `test_dsr.py`, `test_pbo.py`, `test_cpcv.py`,
  `test_validation_metrics.py` — **0 `@given` each**. No property that DSR/PSR ∈ [0,1],
  no monotonicity in trial count / skew / kurtosis, no "PBO ≈ 0.5 on pure noise"
  invariant. These are the gatekeepers that decide whether a strategy is real; their
  monotonic/bounded behavior is asserted only at hand-picked points.
- **Costs** (`test_costs.py`), **sizing**, **overlay**, **killswitch**: 0 `@given`.
  Cost monotonicity (more notional ⇒ more impact), vol-target scaling, drawdown-ladder
  monotonicity are example-based only.

### G4 — Pre-arm real-money gates (C3/C5/C7/C10) have no executable spec guard  **[MEDIUM]**

The five deferred real-money fixes are correctly out of reach in v1 (CCXTBroker is a
`NotArmedError` stub, `execution/ccxt_broker.py:1`, guarded by `test_broker_abc.py`).
But there is **no failing/xfail test that encodes the required post-fix behavior** —
`grep "xfail"` over `tests/` returns nothing. Specifically:

- **C3 (mark-time):** `test_reconcile.py` always reconciles at a single fixed
  `as_of=T0` (`:318,330,353,383,392…`). The C3 hazard — broker equity marked at
  `fills[-1].ts` while the book is marked at `floor_bar(now)` on a *moving* book — is
  never constructed, so the spurious-`ReconciliationError` / masked-divergence path is
  untested and there is no red test waiting for `BrokerView.account_at(as_of)`.
- **C10a/b (ack ordering + durability):** no test pins "book the dedup ack before /
  atomically with the fill" or the `synchronous=FULL`/fsync durability requirement in
  `paper.py`. `test_paper_broker.py` covers idempotent resubmit
  (`test_resubmit_returns_prior_ack_no_double_fill:309`) but not crash-between-book-and-ack.
- **C10c (two-tier ladder):** reconcile tests assert a single hard equity bound
  (`test_equity_divergence_beyond_tolerance_raises:387`); the spec's 0.5% WARN → 2%
  HALT ladder has no test.

Risk: the checklist lives only in a memory note; nothing in the repo turns red if a
future arming PR forgets one. A 10/10 makes the deferral visible as a skipped test
with the gate id in its name.

### G5 — `ml/importance.py` (MDA + feature clustering) is executed but never asserted  **[MEDIUM]**

`mda_importance` and `cluster_features` (`ml/importance.py:69,136`) are wired into
`ml/retrain.py` and `analytics/walkforward.py`, but `grep "importance\|mda\|cluster"`
over `test_ml_retrain.py` and `test_walkforward.py` returns **nothing** — they run
inside those flows with no assertion on their output. There is no direct test file.
MDA permutation importance has a known failure mode (correlated-feature dilution that
clustering is meant to fix); neither the permutation sign convention nor the cluster
grouping is pinned. A mutation here would not be caught.

### G6 — Golden master is hand-arithmetic, not a stored artifact; `tests/golden/` is empty  **[POLISH]**

`tests/integration/test_golden_master.py` (623 lines) is genuinely excellent —
hand-derived fills/fees/funding to the cent, plus a drift-guard that pins
`LakeCostInputs` numerically equal to the registered `adv_quote_30d`/`sigma_daily`
(`:Part 2`), plus a read-only real-lake funding check (`:526`, skipped if absent). But
the `tests/golden/` directory contains **no files** — there is no stored
equity-curve / tearsheet / per-bar-PnL snapshot for the *full grand-backtest harness*.
A whole-pipeline numeric regression (e.g. a portfolio or analytics change that shifts
the final equity by 3 bps) would not trip a golden diff; it is only caught if it
happens to violate one of the scripted hand-arithmetic asserts. The hand-master pins
*mechanism*; a stored master would pin *the whole pipeline's number*.

### G7 — Deployed-path parity proven only for finite-window + crypto  **[POLISH]**

`test_phase4_deployed_path.py` and `test_feature_serve_parity.py` are strong: exact
(`check_exact=True`) batch-vs-live and train-vs-serve identity. But by construction
they use **finite-window crypto specs** so the comparison can be bit-exact. The
EWMA-family 1e-9 tolerance is exercised only in the *unit* truncation harness
(`test_feature_parity.py:337`), never through the full deployed `compute_asof` →
CSPipeline → blend chain. And there is no deployed-path parity test for *any* equity
spec (it cannot exist until G1 is built). The strongest parity guarantee is therefore
narrower than the strategies it must protect.

---

## 3. Severity summary

| ID | Gap | Severity |
|----|-----|----------|
| G1 | Equities read-path absent (no calendar grid, no `corporate_actions` reader) ⇒ PIT-adjustment invariant untestable E2E; live equity factors silently unadjusted | **blocker** (equities) / high |
| G2 | No coverage measurement, no mutation testing in CI | **high** |
| G3 | Covariance + validation arsenal (DSR/PSR/PBO/CPCV) + costs have 0 property tests | **high** |
| G4 | Pre-arm gates C3/C5/C7/C10c have no executable spec/xfail guard | **medium** |
| G5 | `ml/importance.py` MDA + clustering executed but never asserted | **medium** |
| G6 | `tests/golden/` empty — no stored full-pipeline numeric master | **polish** |
| G7 | Deployed-path parity proven only finite-window + crypto; EWMA + equity untested E2E | **polish** |

---

## 4. Concrete fixes

- **G1:** Build the equity read-path so it becomes testable: (a) make `FeatureEngine`
  calendar-aware — select `Timeframe.D1` + `XNYSCalendar` grid by the universe's
  `asset_class` instead of the hardcoded `ANCHOR_TIMEFRAME = H1`
  (`features/engine.py:87,126`); (b) implement `PITDataReader.corporate_actions` and
  `FeatureContext.corporate_actions` so `_adjusted_close_panel` adjusts instead of
  falling back. Then add `tests/integration/test_equity_deployed_path.py`: plant a 2:1
  split in a synthetic equity lake, run `eq_mom_252_21` / `eq_rev_21` through the
  *real* engine on the XNYS session grid, assert the split prints no -50% return and is
  invisible before `available_at` — the integration analogue of the existing
  `TestAdjustedClosePIT` unit gate. Until G1 is built, mark the equity sleeve "not
  arrived" in scope docs rather than implying coverage.

- **G2:** Add `pytest-cov` to dev deps; set `addopts += --cov=alphaforge
  --cov-branch --cov-report=term-missing`; add a `--cov-fail-under` floor (start at the
  measured number, ratchet). Add a separate (non-blocking-at-first) `mutmut` job
  targeting `costs/`, `portfolio/optimizer.py`, `portfolio/` covariance,
  `backtest/ledger.py`, and `validation/`; triage survivors into new assertions.

- **G3:** Add `@given` property tests: covariance returns PSD + symmetric + shrinkage
  ∈ [0,1] for arbitrary return panels and shrinks toward its target as n→p; DSR/PSR ∈
  [0,1] and monotone decreasing in `n_trials` and increasing in observed Sharpe; PBO ∈
  [0,1] with PBO ≈ 0.5 on i.i.d.-noise PnL matrices; cost-model impact monotone in
  notional and ≥ 0. Reuse the optimizer-property idiom (`test_optimizer.py:455`).

- **G4:** Add `tests/integration/test_prearm_gates.py` with one `@pytest.mark.xfail`
  (or `skip(reason="pre-arm gate Cx")`) per gate that constructs the failing scenario
  and asserts the *required* behavior (C3: reconcile on a moving book with a shared
  `account_at(as_of)`; C10a: ack durable before fill booked; C10c: WARN-then-HALT
  ladder). Arming the broker flips them green — the checklist becomes CI-enforced.

- **G5:** Add `tests/unit/test_ml_importance.py`: MDA importance is positive for an
  injected predictive feature and ≈ 0 for pure noise; clustering groups two duplicated
  features into one cluster; the permutation degrades log-loss in the expected
  direction.

- **G6:** Add a stored golden under `tests/golden/`: run the grand-backtest harness on
  a small committed synthetic lake, snapshot the equity curve + key tearsheet metrics
  to a checked-in JSON/parquet, and assert equality (with a documented regen command).
  Whole-pipeline numeric drift then surfaces as a reviewable diff.

- **G7:** Extend `test_phase4_deployed_path.py` with an EWMA-family spec asserting the
  deployed `compute_asof` chain stays within the 1e-9 documented tolerance end-to-end
  (not just in the unit harness); add the equity deployed-path parity test once G1 lands.
