# AlphaForge

Institutional-grade mid-frequency quantitative trading system. Multi-asset core; v1 trades
Binance USDT-M perpetuals on 1h bars (signal at bar close, execution at next open), full stack
from data lake through live paper trading.

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
uv run ruff check .     # lint
uv run mypy             # types (strict)
```
