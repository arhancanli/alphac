# AlphaC owner goals — September 12, 2026

Working mode update — September 13: the owner explicitly re-enabled a persistent goal and authorized autonomous continuation across bounded phases without repeated routine permission requests. Report evidence, progress, failures and the next step at each phase boundary, then continue. Prioritize algorithm improvement and economically distinct sleeve research; time-box infrastructure to concrete blockers. Do not repeat unproductive loops or claim unverified results. This supersedes earlier stop-at-every-phase instructions. Existing Meridian API/MCP foundations remain relevant; deployment is not verified.

This records the owner's latest direction and supersedes the earlier 14-sleeve research aspiration. Goals apply to the combined portfolio, not to every sleeve. None is established by this document.

## Outcomes

1. Combined portfolio Sharpe **above 2**, net of costs. Freeze the excess-return benchmark, calendar, evaluation horizon and uncertainty method before a qualifying evaluation; existing zero-benchmark simulated Sharpe is not automatically interchangeable.
2. Combined portfolio maximum drawdown **no greater than 11%**. This is stronger than an expected-maximum-drawdown target. Show realized, historical scenario, simulated expected and tail drawdowns separately. Specify finite evaluation horizons and stress acceptance rules prospectively; no backtest can establish an absolute bound on all future losses.
3. **At least 15 qualified economically distinct sleeves.** Lower standalone Sharpe is acceptable when a sleeve improves the combined book under the applicable evidence gates. Different tickers, parameters or names do not establish independent mechanisms.
4. Exceptionally strong research and operational testing: point-in-time data, correct cash/dividend accounting, leakage checks, full trial accounting, untouched/prospective validation, stressed dependence, realistic execution and financing, capacity, reproducible outputs, restart/reconciliation and honest forward records.
5. After algorithm and operational evidence justify launch, publish the **CanliCapital glassbox analysis platform**, with understandable methods, versions, costs, uncertainty, failures and reproducible evidence, **API-key access**, and **MCP servers**. Design access control, key lifecycle, usage limits, documentation and data rights as launch requirements. Being the first such platform is an ambition, not an established novelty claim.
6. Preserve the broader master-plan commitments: visible Arhan Canli authorship, permanent trial/sleeve research records, independent reproduction and external review, an accessible and performant website, and factual professional/academic evidence. Presentation and recognition do not substitute for investment evidence.

## Permission to reconsider assumptions

The owner explicitly authorizes broad reasoning and adjustments to baselines, mechanisms, universes, allocation and risk design when justified by the goal. Keep the original comparator and outcomes; record why each new baseline is economically meaningful, its costs/data/version, and register return-producing changes before measuring them. Do not redefine success after seeing results or lower a baseline merely to obtain a pass. An accounting repair may correct a baseline, but it must retain the original and disclose the correction.

Evaluate prospective changes primarily by incremental combined-portfolio value. Existing development rules remain attached to their original trials; this direction does not retroactively admit rejected candidates. Full thresholds and public projections require a versioned contract migration with consistency tests. Existing `sleeve_admission_contract.json` and `forward_evidence_contract.json` still encode older objectives; their historical figures are not current owner aspirations and are not silently overwritten.

## Current evidence and work order

- Latest registered AlphaTrend comparison: baseline Sharpe 0.1972, candidate 0.1582; candidate rejected under its frozen protocol. Both are development simulations, not combined-book performance.
- Latest recovered experiment union: 242; verify canonical accounting before reserving another identity. No new qualified sleeve is established by the latest work.
- Saved-run attribution reconciles both portfolios within $0.000001. Next: examine forecast and exposure differences and whether the baseline/allocator is a useful comparator. Design a prospective portfolio-aware evaluation, not another cosmetic variant.
- Continue independent mechanism feasibility alongside existing-sleeve improvement. Treasury cash-data coverage and 15 historical trading boundaries remain unresolved in the latest saved review.
- Resolve AlphaForge paper restart and timing/account readiness against the latest operational evidence before activation; prior notes are historical, not a fresh runtime clearance.
- Before any claim against the new targets: formalize portfolio-level Sharpe/drawdown definitions, migrate contracts prospectively, bind the current book and test financial/operational stress. Keep product launch downstream of this evidence.

## Continuation sources

- `ALPHATREND_IMPROVEMENT.md`: chronological research checkpoints.
- `evidence/alphatrend-retrospective-attribution-20260912/REPORT.md`: latest saved-run attribution.
- `ALPHAC_BREADTH_PHASE.md` and `PRODUCT_VISION.md`: earlier breadth and product directions, superseded above where targets differ.
- `/Users/arhancanli/alphaforge/docs/design/ALPHAC_MASTER_PLAN.md`: broader program commitments; older numeric targets remain historical.

Pursue these long-term objectives through bounded autonomous phases; report at each boundary and continue within the authorized scope. Each report should identify what changed toward the outcomes, what remains unproven, and the next concrete step. Do not mark success based on activity, test count, sleeve names, or elapsed time.


Latest autonomous experiment (September13): capped inverse-vol allocation rejected, canonical243/244 complete, current union244. See artifacts/analysis/alphac_inverse_vol_20260913/REPORT.md. No qualification or sleeve additions. Preserve the baseline and both failed volatility-based experiments; avoid lookback/cap sweeps.

Latest September13 checkpoint: direction-confirmation canonical245–248 complete; union248. Four gates pass but primary+0.10 Sharpe gain fails (+0.0932). No admission. Next separately declared combined contribution comparison, preserving both original baseline and standalone failure.

Latest September13 combined checkpoint: union252; confirmation passes four combined development gates at raw Sharpe1.8689 versus matched1.7916. Bootstrap uncertainty includes zero. No qualification/production/new sleeves; standalone failed gate preserved. Next funded net-excess comparison feasibility.

Latest benchmark checkpoint September13: union256. Capital-budget proxy confirmation excess Sharpe0.9094 versus0.8333 control; raw1.8780 is not net excess. DFF modeled lag and unresolved internal funding mean no financed qualification. Next return-source/forecast-quality work; preserve all baselines and no benchmark tuning.

## Owner restatement, September 14 2026

Recorded verbatim from the owner in the operator session (supersedes the numeric outcomes above
where they differ; nothing below is established by this document):

> no let me break down the goals for you so basically we are trying to make alphac like the worlds
> first open glassbox style algorithm which devs can use via api keys and mcp servers to build
> there own mobdels fine tune it make it better and also we are making everything we do out in the
> open published all tests everything and for alphac the goal is 2 sharpe ratio 14 plus sleeves 10
> percent max dd and also all of the other things being perfect and us doing extremely rigiourus
> tests on it and also not forgeting reach life cosst which may occur on it on our paper live and
> also eventually turning this into a real hedgefund

Read as governing goals (`config/owner_goals.json`, in force 2026-09-14):

1. Combined portfolio Sharpe **above 2**, net of costs.
2. Combined portfolio maximum drawdown **no greater than 10%** (realized bound; stronger than the
   expected-maximum-drawdown objective the sealed admission contract carries at 11%).
3. **At least 14 qualified economically distinct sleeves.**
4. Real-life costs on the paper-live record: commissions, spread and slippage, financing and
   funding, borrow, and every cost a funded book would pay, modelled where they occur and never
   assumed away.
5. Extremely rigorous testing of everything, with every test published.
6. Everything done in the open: the algorithm as the world's first open glassbox, every trial,
   every test and every failure published.
7. The glassbox platform: developers use ALPHAC through API keys and MCP servers to build their own
   models, fine-tune it and improve it.
8. Eventually a real hedge fund, downstream of the paper evidence; paper results never convert into
   real capital by presentation.

The drawdown brake declared in `config/drawdown_control_contract.json` (half gross at 5.5%, flat
at 11%) was measured against the superseded 11% objective and cannot enforce a 10% bound. A ladder
consistent with the bound must be measured and declared before the brake is activated.

Update, 2026-09-14 (evening): drawdown control v1.1 re-derives the ladder from the 10% bound
(half gross at 5%, flat at 10%) and re-measures it by the same protocol; v1.0 (5.5% / 11%) is kept
as history in the contract. The brake is still not activated.
## Owner direction, September 14 2026 (evening)

Verbatim: "i want you to focus on adding sleeves improving each sleeves sharpe ratio returs cagr
max dd and everything go agead make sure everything is perfect and i give you full permision for
the activiations so you can go ahead"

Read as: the research priority is breadth (new qualified, economically distinct sleeves) and the
quality of every existing sleeve (Sharpe, return, CAGR, maximum drawdown), under the existing
gates and trial accounting; the owner authorizes the operator to perform the activations that were
reserved to the owner (drawdown-brake activation, the Frankfurt companion rollout, and the
promotions those require), each still declared and logged as before. Nothing in this direction
retroactively admits a rejected candidate or lowers a gate.
