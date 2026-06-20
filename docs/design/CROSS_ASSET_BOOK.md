# Cross-Asset Book — design & honest verdict

The unified multi-sleeve book: the layer that combines AlphaForge's independent per-sleeve
strategies into one capital allocation, the way multi-strategy funds run it. Implemented in
`src/alphaforge/portfolio/book.py` (`combine_book`); reproducible report
`scripts/cross_asset_book.py`; 18 unit tests `tests/unit/test_portfolio_book.py`.

## Why a combiner, not one optimizer

The sleeves live on incompatible calendars and frequencies (equity momentum on D1/XNYS;
crypto funding-carry on H1/24-7). Re-optimizing positions across mixed-frequency instruments
in one optimizer is incoherent and is *not* how books are run. Instead each sleeve is an
INDEPENDENT strategy producing its own net-of-cost equity curve; the book allocates
CAPITAL/RISK across those return streams and applies a single book-level risk budget. The
diversification benefit — combined Sharpe approaching `sqrt(sum of sleeve Sharpe^2)` when
sleeves are decorrelated (the Fundamental Law of Active Management across asset classes) —
emerges at this layer.

## Mechanics (`combine_book`)

- **Resample** each sleeve curve to one return per UTC day; align on the UNION of calendar
  days inside the common live window `[max(sleeve start), min(sleeve end)]`. A flat sleeve
  (equity on a weekend) earns 0 while a 24-7 sleeve still earns — the real book's P&L.
  Annualize with 365 (the book trades every calendar day via the 24-7 sleeve).
- **Capital schemes**: `equal_risk` (1/sigma, PIT trailing-vol — the deployable default),
  `inverse_var`, `equal_weight`, `fixed`, and a labelled `static` full-sample DIAGNOSTIC
  (full-sample equal-risk — uses hindsight; quantifies how much the naive combine owes to
  look-ahead; never deploy off it).
- **Book vol-target** (optional): scale to a target annual vol from trailing realized vol,
  capped at `max_leverage` AND per-sleeve by `venue_gross_cap` (so a dollar-neutral sleeve's
  gross can't breach e.g. Reg-T 2x). `sleeve_gross` is each sleeve's internal gross per unit
  of capital (dollar-neutral L/S = 2.0).
- **PIT non-negotiable**: every weight and leverage applied to a forward day is a pure
  function of returns strictly before that day (unit-tested by truncation invariance, exact
  on the real curves).

## Measured result (2023-07 .. 2026-06, net of cost, corr -0.016)

| Book | Sharpe | CAGR | Vol | MaxDD |
|---|---|---|---|---|
| DEPLOY: fixed 50/50 | 1.51 | 12.5% | 8.0% | -4.1% |
| dynamic equal_risk (worse) | 1.46 | 11.7% | 7.8% | -4.7% |
| Reg-T-feasible vol-target 15% | 1.41 | 21.3% | 14.4% | -8.1% |
| Reg-T-feasible vol-target 20% | 1.48 | 24.6% | 15.7% | -8.1% |

## Honest verdict (adversarial 7-agent audit, run `w1947t1pb`)

**STRUCTURE survives — underwrite it.** The combiner is PIT-clean (no look-ahead in weights
or leverage). The -0.016 correlation is stable across every sub-period and *strengthens
negative in stress* (-0.44 on down days, -0.64 stress-union); the sleeves anti-cluster — they
never both hit their worst-2.5% on the same day; the realized -4.7% maxDD was a single-sleeve
event. This is decorrelation that holds when it matters.

**MAGNITUDE must be deflated hard.**
- **Deflation**: combined-book DSR is 0.44 at N=69 honest trials, 0.19 at N=518 config dirs,
  vs the 0.95 gate; the expected-max Sharpe of pure noise overtakes this book at only N=50.
  Breadth does not rescue *selection*. The standalone sleeves already fail their own gate
  (equity DSR 0.341, crypto 0.039). The sample (~2.9yr, 2 bets) is too short.
- **Period concentration**: excluding the 5-month 2026 spike drops every scheme to ~1.04;
  2025 was nearly flat (Sharpe 0.40). 1.46 sits at the ~71st percentile of its own rolling
  windows.
- **Window favorability**: the common window excludes crypto carry's -1.63 Sharpe 2022
  (funding-inversion bear, -19% sleeve DD). The book has never co-experienced that alongside
  the equity sleeve.

**Honest forward expectation**: Sharpe ~0.7-1.0 unscaled (central ~0.7, plan around 1.0),
~7-10% net at natural vol, ~13-16% net at a Reg-T-feasible ~14% vol-target. NOT 1.46/28%.

**Resilience**: if the crypto carry edge decays to zero the book still holds ~1.0 (equity
momentum is the ballast). The dominant forward tail is a carry SIGN-FLIP year (a 2022 repeat
-> book ~-13% DD). Size the vol-target against a -15/-20% single-sleeve crypto blowup, not
the benign -4.7% realized DD.

## Deploy recommendation

- Deploy as a **fixed 50/50** capital split (the dynamic 21-day reweighting adds nothing and
  incurs cross-venue drag).
- Run the vol-target at a Reg-T-feasible cap (~1.84-2.0x equity gross); quote ~21% CAGR /
  ~14% vol, not 28% / 20%. Do not size to 20% vol without confirmed Portfolio Margin.
- Conditions before real capital: clear the Phase-8 pre-arm gates (C3/C5/C7/C10) and run
  6-12 months of genuinely out-of-2026 paper/live evidence confirming the carry edge persists.
- Cap the pilot at the low end of the capacity curve; treat funding-carry as decaying alpha,
  re-estimate quarterly.

## The one lever left: data

The deflation finding is the binding constraint: the sample is too short to clear honest
multiple-testing. The free-breadth path is exhausted — pre-registered value (book-to-price,
SR -0.32) and quality (gross profitability, SR -0.82) both FAILED on the narrow top-200 /
5-year universe (fundamental premia need small/mid caps + a value cycle). The honest path is
the DATA INVESTMENT: a deeper + wider survivorship-free universe (Sharadar ~20yr / ~3000
names with fundamentals) to (a) lengthen the sample so the verdict can clear deflation and
(b) unlock genuinely decorrelated value/quality/small-cap sleeves that add real breadth.
