# ALPHAC — the quant engine behind [canlicapital.com](https://canlicapital.com)

[![ci](https://github.com/arhancanli/alphac/actions/workflows/ci.yml/badge.svg)](https://github.com/arhancanli/alphac/actions/workflows/ci.yml) [![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml) [![live record](https://img.shields.io/badge/live%20record-paper%2C%20since%202026--08--07-orange.svg)](https://canlicapital.com/performance)

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

**Evidence snapshot:** 2026-08-26. Later marks must update this table through the same
artifact-bound publication pipeline; this is not a real-time broker display.

| | |
|---|---|
| Paper sleeves | **4 / 14 planned** — funding carry, equity momentum, managed-futures trend, PIT macro surprise |
| Forward record | **17 daily returns** from 2026-08-07 through 2026-08-26; cumulative return **−2.27520%**; provenance fails closed because crypto attribution does not cover the latest mark |
| Forward Sharpe | **Not reportable** — 252 observations are required for an estimate and 756 for the project's establishment test |
| Drawdown | Realized **2.47372%** to date, descriptive only; the current-composition model estimates **9.318% expected / 16.451% p95**, neither established by live evidence |
| Diversification | Research-curve average pairwise correlation **+0.02483** across 4 sleeves; live-forward diversification is not established |
| DSR policy | Mandatory to measure and publish; **0.95 is a full-union portfolio-maturity threshold, not a per-sleeve or incremental-admission gate** |

No forward Sharpe or expected maximum drawdown is established. The 17-return record is too short, and its provenance gate remains closed because the latest composite mark is newer than the last attributed crypto cycle.
Historical simulations, modeled risk and broker-derived paper marks remain separately labelled;
none is a promise about future returns.

## What is actually interesting here

The strategies are well-documented academic families — cross-sectional momentum, funding carry,
time-series trend, macro-surprise rotation. We are not claiming a secret. What took the work, and
what this repo is really for, is the machinery that stops us fooling ourselves:

- **A union trial ledger.** Deflated-Sharpe correction counts every hypothesis ever tested across
  every durable research ledger, deduplicated — **229 total identities**: 228 retired legacy
  identities plus one sealed prospective identity that ended incomplete and was not admitted.
  Which directory a trial landed in is a filing convention; multiple-testing correction does not
  care. Prospective research has a staged **400-identity ceiling**, with hard reviews at 320, 360
  and 400. The remaining capacity buys permission to test, never permission to admit.
- **Pre-registration that can be voided.** Each candidate names its mechanism, data vintages,
  costs, variants and kill condition *before* the holdout is read. `docs/design/PREREG_*.md`.
  A run that deviates from its own document is not quietly accepted.
- **A published kill log.** Dead ideas keep their full return curves, not a scalar verdict — you
  cannot build a portfolio out of scalars. Recent kills: all five PIT macro-surprise series,
  clustered insider purchases, crypto VRP, eight AlphaMax construction variants.
- **`docs/retracted_claims.txt`.** Numbers we published and later found wrong, with the correction
  and the date. Two of the largest: average pairwise correlation was published as ~−0.02 when the
  three-sleeve book measured **+0.0723** (the current four-sleeve research study measures
  **+0.02483**), and
  AlphaTrend was called our soundest sleeve at DSR 0.83 when its honest DSR is **0.000** — it had
  been graded with a variance input ~80x too small, an easier exam than its siblings.
- **A signed, Bitcoin-anchored transparency chain.** An
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
3. **Trial-packet backfill is mostly incomplete.** The public corpus contains 101 research papers
   and the one-to-one manifest publishes a packet for all 228 hypothesis identities, but only 2
   packets currently contain every required protocol, result, lineage and correction section; 226
   remain incomplete. Family-paper coverage is not exact-trial reproducibility, so the project
   explicitly does not claim a complete paper and evidence packet for every trial.

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
