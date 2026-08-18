# ALPHAC — the quant engine behind [canlicapital.com](https://canlicapital.com)

ALPHAC is a cross-asset, market-neutral research and trading system, and this is all of it:
the data lake, the point-in-time reader, the backtester, the walk-forward harness, the
multiple-testing machinery, the portfolio optimizer, the live broker loop, and every design
document and adversarial review that produced them.

**Created and maintained by [Arhan Canli](https://github.com/arhancanli) for Canli Capital.**
Development uses reviewed AI-assisted tooling, but project ownership, research decisions,
methodology, claims, and publication responsibility remain with Arhan Canli. Citation metadata is
provided in [`CITATION.cff`](CITATION.cff).

It is public because the claim we actually make is not *"this makes money."* It is
**"every number we publish can be checked, including the ones that embarrass us."** That claim
is worthless if the code is hidden.

## The honest position, stated first

We run this on paper capital. No real money has been deployed.

| | |
|---|---|
| Live sleeves | **4** — funding carry, equity momentum, managed-futures trend, PIT macro surprise |
| Forward record | began **2026-08-07** on separate $1M Alpaca paper accounts, one per sleeve |
| Average pairwise correlation | **+0.0274** — *positive*. We used to call the sleeves "uncorrelated" and call that the edge. It is real diversification, but smaller than we said. |
| In-sample Sharpe | 1.78 book / 1.38 neutral core — **in-sample, and therefore not evidence** |
| Honest forward Sharpe | **0.3 to 0.9**, with a real chance of ~0 in year one |
| Deflated Sharpe (gate 0.95) | AlphaMax **0.213** · AlphaForge **0.052** · AlphaTrend **0.000** |
| Grade | **C+** |

**Not one sleeve is statistically distinguishable from luck once its own search is accounted
for.** That is not a marketing frame, it is the measurement. It does not mean the strategies are
worthless — it means the *backtest* evidence cannot carry them, and only a long forward record
can settle it. That record began on 2026-08-07.

Maximum drawdown reads −4.5%, but that is the live-overlap window only (2023-07 onward). It
excludes 2022 and Covid and **is not a risk estimate**. The realistic worst case, including the
disclosed strategic-long overlay's crash tail, is **−22% to −28%**.

## What is actually interesting here

The strategies are well-documented academic families — cross-sectional momentum, funding carry,
time-series trend, macro-surprise rotation. We are not claiming a secret. What took the work, and
what this repo is really for, is the machinery that stops us fooling ourselves:

- **A union trial ledger.** Deflated-Sharpe correction counts every hypothesis ever tested across
  every research profile, deduplicated — 162 distinct identities. Which directory a trial landed
  in is a filing convention; multiple-testing correction does not care. Research is currently
  **paused at 162 against a 160 budget** pending a formal decision, because adding hypotheses
  raises the bar for everything already in the book.
- **Pre-registration that can be voided.** Each candidate names its mechanism, data vintages,
  costs, variants and kill condition *before* the holdout is read. `docs/design/PREREG_*.md`.
  A run that deviates from its own document is not quietly accepted.
- **A published kill log.** Dead ideas keep their full return curves, not a scalar verdict — you
  cannot build a portfolio out of scalars. Recent kills: all five PIT macro-surprise series,
  clustered insider purchases, crypto VRP, eight AlphaMax construction variants.
- **`docs/retracted_claims.txt`.** Numbers we published and later found wrong, with the correction
  and the date. Two of the largest: average pairwise correlation was published as ~−0.02 when the
  three-sleeve book measured **+0.0723** (the current four-sleeve book measures +0.0274), and
  AlphaTrend was called our soundest sleeve at DSR 0.83 when its honest DSR is **0.000** — it had
  been graded with a variance input ~80x too small, an easier exam than its siblings.
- **A signed, Bitcoin-anchored transparency chain** — 239 entries across 39 distinct dates. An
  append-only hash chain over the published record, so a past claim cannot be silently rewritten.
  The verifier and anchoring scripts are here; the log itself is operational state, published at
  [canlicapital.com/open](https://canlicapital.com/open) rather than committed.
- **Tests that pin the path that runs, not the intention.** Twice in this project a fix was
  correct, unit-tested, and never executed in production — funding was booked zero times in 44
  days behind a swallowed `TypeError`, and a regime detector fires on 0.02% of days when it should
  fire on 81.8%. Both are documented. The lesson is enforced in the test suite.

## Known-open defects

Kept here rather than in an issue tracker nobody reads:

1. **Overlay scale defect** (`portfolio` / `strategy.py:609`) — the realized-vol leg measures the
   post-overlay equity curve while the ex-ante leg uses pre-overlay weights. Never the same scale.
   Costs an estimated +0.6 to +2.2pp of expected max drawdown. **Open.**
2. **AlphaLedger's pre-registration may be void.** `PREREG_SLEEVE4_INVESTMENT.md` pins the universe
   to a frozen 8,017-id allowlist; the run that produced its headline evidence (21y Sharpe 0.83,
   NW t +3.19) resolved the universe dynamically and used 6,880 ids. The corrected re-run is
   written (`scripts/rerun_alphaledger_pinned.py`) and **has not been executed**. The sleeve is
   plumbed but is **not** in the live book, and will not be until this is settled.
3. **The diversification gate bars its own target.** `config/sleeve_discovery.json` declares a
   2.0–2.5 Sharpe objective and an `average_pairwise_correlation_max` of 0.15. At measured sleeve
   quality that ceiling caps the book at **1.37** — a candidate can pass every evidence check and
   the book still cannot reach the target at any sleeve count.

## Reproducing

```sh
uv sync                 # Python 3.12, pinned via uv
uv run pytest           # the suite
uv run af --help        # CLI
```

The Parquet data lake (`data/`, ~26GB) and run artifacts (`artifacts/`) are not in git — they are
re-derivable from the exchange and vendor sources the ingest scripts name. Published numbers and
their inputs are mirrored as machine-readable artifacts under
[canlicapital.com/open](https://canlicapital.com/open).

## Not investment advice

This is research software published for inspection. It is not investment advice, not an offer, and
not a solicitation. Nothing here is a promise or forecast of returns. Past and simulated
performance do not indicate future results. Trading involves risk of total loss. Run it against
your own capital and that is entirely your decision and your risk. See `LICENSE` — the software is
provided "as is", without warranty of any kind.

---

## Engine architecture

Production-oriented mid-frequency quantitative research and paper-trading system under active
development. The multi-asset core includes a Binance USDT-M perpetual path on 1h bars (signal at
bar close, execution at next open), spanning the data lake through live paper operations.

## Non-negotiables

- **Point-in-time everywhere.** Timestamps are UTC epoch-milliseconds; bars are labeled by open
  time and become available at `ts_open + Δ`. A decision at close `T` may only use records with
  `available_at ≤ T`. The `PITDataReader` is the single read path enforcing this.
- **One of everything integrity-critical.** One `Instrument` model, one calendar, one feature
  framework, one `TransactionCostModel`, one purged-splitter library, one scheduler.
- **No same-bar fills.** Every engine fills at the next bar's open plus modeled costs.
- **Survivorship-bias-free.** Backfill candidates come from historical listing/delisting records,
  not the live instrument list.
- Full design rationale and the adversarial review live in [docs/design/](docs/design/).

## Layout

- `src/alphaforge/` — the engine (`core`, `data`, `features`, `validation`, `signals`, `costs`,
  `backtest`, `portfolio`, `risk`, `execution`, `live`, `analytics`)
- `configs/` — layered YAML settings (`base.yaml` + env overrides via pydantic-settings)
- `data/` — Parquet lake (gitignored, re-derivable from exchanges)
- `var/` — operational SQLite state + logs (gitignored, backed up nightly)
- `tests/` — `unit/`, `property/` (hypothesis), `golden/` (frozen fixtures), `integration/`

## Development

```sh
uv sync                 # install env (Python 3.12 pinned via uv)
uv run af --help        # CLI
uv run pytest           # tests
uv run ruff check src/alphaforge tests  # governed lint-clean scope
uv run python scripts/export_lint_debt_contract.py  # disclose legacy script debt
uv run mypy             # types (strict)
```
