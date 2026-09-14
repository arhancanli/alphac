# Portfolio observation collector — September 13, 2026

The isolated research checkout now has a one-shot Alpaca paper-account observation collector. It reuses the existing bounded GET-only paper reader and all-type activity pagination. It captures account and position responses before and after the activity scan, retaining account identity checks and every page, including partial evidence preceding a failure.

Each receipt contains request-start and response-receipt wall/monotonic times, requested endpoint/parameters, and a detached parsed response body. Decimal JSON numbers use an explicit tagged representation to avoid binary-float rounding. These are parsed bodies, not original wire bytes; receipt time includes decoding. Local wall-clock accuracy and broker source timestamps remain unverified. Authentication headers and exception text are excluded from the packet.

The collector never emits a valuation, starts an epoch, grants operating clearance or verifies performance targets. Repeated body agreement is diagnostic only; responses are sequential and may change as prices move. Exhausted activity pagination does not prove settlement completeness or exclude delayed postings. Paper account identity does not establish disjoint sleeve ownership. Position price receipts, funded overlay accounting and complete accrual/flow evidence remain unavailable.

Capture files are created exclusively with owner-only permissions and synchronized to disk. Existing files are not overwritten. Full account evidence is intended for local private storage; the saved example uses entirely synthetic identifiers and mock HTTP responses. No credentials were loaded and no live broker requests were made in this phase.

Validation: **115 tests passed**, including 16 new collector tests, the 59 acquisition/valuation tests, and 40 existing paper-reader/activity tests. Ruff passed. Tests exercise account changes, changing balances, malformed positions, duplicated and budget-exhausted pagination, failed reads, clock reversals, decimal preservation, content hashes and private exclusive persistence. A seven-receipt mock capture was saved and its content hash independently checked. Logs, source bindings and a manifest accompany this report.

Run validation from the research checkout:

```sh
PYTHONPATH=src /Users/arhancanli/alphaforge/.venv/bin/python -m pytest tests/unit/test_portfolio_observation.py tests/unit/test_portfolio_acquisition.py tests/unit/test_portfolio_valuation.py tests/unit/test_spot_paper.py tests/unit/test_spot_activity_ingestion.py -o addopts='' -q
```

The explicit one-shot entry point is `scripts/collect_portfolio_observation.py`. It requires a paper-only credential file, expected account-binding digest, fixed UTC activity window (up to seven days), and a new output path. No scheduler was installed or invoked. Failed/incomplete captures remain evidence packets and must be assessed through their blocking reasons, not through file existence or process success.

This phase completes collector implementation and offline verification. It does **not** complete live source capability calibration, add a legacy crypto-cycle collector or supply a synchronized combined return series. Production and strategy baselines are unchanged; there are no new return trials or qualified sleeves. Combined Sharpe >2, maximum drawdown ≤11% and 15+ qualified sleeves remain unestablished.

Next bounded phase: reconcile current paper account bindings with the retained operating records, perform a read-only capability capture where those bindings are supported, and specify the missing crypto price/cycle receipt instrumentation. Use measured source capabilities to decide the prospective valuation timing policy. Preserve the old baseline and do not relabel sequential observations as a simultaneous cut.
