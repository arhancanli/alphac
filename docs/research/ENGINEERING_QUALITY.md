# Engineering quality boundary

This page reports the current static-quality boundary honestly. It is engineering evidence, not
investment-performance evidence, and generating it evaluates no return stream or hypothesis.

## Verified clean scopes

The production package under `src/alphaforge` and the complete `tests` tree pass the repository's
configured Ruff rules. The production package also passes strict mypy across all 161 modules, and
the current non-network test suite contains 3,702 passing tests. Twelve credentialed network tests
remain deliberately deselected from the offline suite.

## Explicit debt

The `scripts` tree contains historical probes, one-off data collectors, diagnostics, and active
operational exporters accumulated across the research program. It is not Ruff-clean. The
machine-readable contract enumerates every current finding by rule and file and binds each debt
file to its SHA-256 digest.

This boundary is intentional but not celebratory: a clean production package does not make an
unclean repository clean. Historical scripts will be remediated in reviewed batches, prioritizing
active operational and publication paths before archived exploratory probes. Bulk autofix is not
used across return-generating scripts because even apparently stylistic rewrites deserve tests and
review when they sit near research evidence.

## Reproduction

Run:

```text
uv run ruff check src/alphaforge
uv run ruff check tests
uv run ruff check scripts
uv run mypy --strict src/alphaforge
```

The current source-bound result is published locally at
`/glassbox/lint_debt_contract.json`. Its status is
`PRODUCTION_AND_TESTS_CLEAN_HISTORICAL_SCRIPTS_DEBT`; it must not be represented as a whole-repo
clean claim.
