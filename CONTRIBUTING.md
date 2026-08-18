# Contributing to ALPHAC

ALPHAC welcomes corrections, reproducibility improvements, execution-model tests, data-lineage
work, documentation, and carefully bounded engineering changes.

## Evidence boundary

- Do not present simulated performance as live or investable performance.
- Do not open a holdout, inspect return data, or spend a hypothesis identity outside the locked
  trial-accounting process.
- Keep negative results, failed tests, limitations, and implementation assumptions visible.
- Do not commit licensed market data, credentials, account identifiers, or proprietary inputs.

Strategy proposals should begin as an issue describing the economic mechanism, asset class,
point-in-time data requirements, falsification test, expected implementation costs, and overlap
with existing candidate families. A promising backtest alone is not admission evidence.

## Local checks

```sh
uv sync --frozen --dev
uv run ruff check src/alphaforge tests
uv run mypy
uv run pytest
uv run python scripts/export_lint_debt_contract.py
git diff --exit-code -- artifacts/engineering/lint_debt_contract.json
```

Pull requests should be narrow, explain their evidence boundary, include tests, and identify any
claim or reproducible artifact they change.
