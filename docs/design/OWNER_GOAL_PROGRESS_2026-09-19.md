# Owner goals: evidence review, 19 September 2026

The owner reconfirmed the glass-box platform vision and the algorithm objectives: combined forward Sharpe above 2 net of costs, at least 14 economically distinct qualified sleeves, and realized maximum drawdown no greater than 10%. `config/owner_goals.json` remains the authoritative objective. This review does not change an objective, an admission threshold, a trial identity or live sizing.

## Observed state

The `artifacts/engineering/forward_evidence_maturity.json` snapshot generated at 2026-09-19T09:27:23.259823+00:00 reports:

| Dimension | Evidence |
| --- | --- |
| Current configuration | Four sleeves; evidence epoch starts 15 September after book drawdown-control activation |
| Current forward record | Four daily returns; no publishable Sharpe estimate |
| Minimum observations | 252 for an estimate; 756 plus the probability/provenance gates for establishment |
| Remaining observations | 248 to estimate; 752 to the minimum establishment count |
| Current epoch return | Approximately +0.2428%, descriptive only |
| Whole-record realized maximum drawdown | Approximately 3.8964%, not a bound on future losses |
| Conservative current-composition modeled tail drawdown | Approximately 16.4514%; study does not establish live risk |
| Provenance gate | Passed in the cited snapshot |

Do not pool pre-activation and post-activation returns. Do not infer a qualified sleeve count from the number of running sleeves. Do not replace missing costs with convenient flat assumptions to describe a record as fully net of real-world costs.

## Corrections prepared

1. The maturity regression test required a negative cumulative return. That was an accidental assertion about an old observation, not an invariant. It now checks the short observation count and remaining evidence gap. The deterministic evaluator test covers negative, flat-mean and positive short records; none may publish a Sharpe estimate.
2. The goal projection copied a historical "not live" drawdown mechanism label even though the current control contract declares activation. The projection now reads and checks the current contract, including schema, owner bound, half/flat levels and activation/status agreement. The old label remains explicitly historical. The mechanism text distinguishes a contract declaration from independent runtime verification and acknowledges intraday overshoot.
3. Invalid boolean or non-finite Sharpe targets fail validation rather than entering a public objective.

Validation: 61 targeted tests passed across owner goals, sleeve admission, drawdown study, forward-evidence maturity and the sleeve atlas. The existing published drawdown-study artifact was copied into the isolated review worktree for its binding check; no study was rerun and no new performance result is claimed. Ruff passes on all changed Python files.

## Work needed to improve the portfolio, in order

1. Preserve the continuous current-epoch paper record and reconciliations. An early positive run does not establish the Sharpe goal.
2. Capture a defensible price reference at submission to measure arrival slippage. The equity cost-realism contract currently discloses that no such reference is recorded; financing also lacks a bound rate provider. Resolve the data gap before charging or claiming those costs.
3. Complete constituent-instrument and actual ladder replay, crisis coverage, execution-gap and liquidity-feedback scenarios. The current common window omits major stress episodes.
4. Develop economically distinct candidate sleeves through the existing reserved-trial and admission process. Register hypotheses before touching evaluation returns, preserve family-wise accounting and require net incremental contribution and diversification evidence.
5. Treat negative marginal historical contributions as research questions. The cited diagnostics show negative fixed-to-cash deltas for `managed_futures` and `alphavintage_live`; these exploratory comparisons alone do not authorize hindsight-based admission or removal.
6. Seek independent reproduction and continue publishing failed tests. Neither a return-count threshold nor a favorable bootstrap alone establishes the full objective.

The source changes are in an isolated review branch. They improve evidence correctness, not the observed Sharpe ratio. No production trading parameters, broker actions, sleeve admissions or deployments were changed.

The website expansion and developer-platform quality contract are recorded in the website repository at `docs/GLASSBOX-PLATFORM-VISION-2026-09-19.md`. Its source-backed company reference is an input-inspection aid; it is not a point-in-time return dataset and must not be fed directly into the validation API as returns.
