# Combined AlphaC baseline audit — phase complete

This phase inspected local production artifacts and source, preserved snapshots, and ran two synthetic accounting checks. It did not generate a new market-return variant, fit portfolio weights, change production, or contact a broker. `audit.json` contains the exact observations and SHA-256 bindings; `sources/` retains the inspected files.

## Verdict

The existing book is useful as a historical control and paper observation record, but is **not ready to qualify a new portfolio against Sharpe >2 and maximum drawdown <=11%**. Keep its original results. Repair the measurement and provenance gaps before judging improvements; do not replace the baseline with a favorable synthetic combination.

## Current configuration

Local published state generated September 12 at 19:26:33 UTC has AlphaForge, AlphaMax, AlphaTrend/managed_futures and AlphaVintage at 25% each, plus a separate 10% strategic beta overlay split equally between BTC and SPY. Composition agrees with the saved fingerprint; state bytes agree with the saved maturity report's binding. The portfolio has neither a book-level volatility target nor a book-level drawdown ladder. Constituent controls are not a substitute for a combined-book risk policy.

The current owner goals remain 15+ qualified sleeves, combined net-of-cost Sharpe above 2, and maximum drawdown at most 11%. The older published contract still uses 1.5 Sharpe and expected drawdown. A prospective contract migration remains required; none occurred here.

## Source audit

| Source | Current evidence | Permitted use / gap |
|---|---|---|
| Historical AlphaMax | 729 reference marks; matches retained study hash | Historical control. Fresh replay receipt is not exact. Later reference recovery reconstructs all 12 legs exactly; initial replay quantities are traced to a TEAM/CVS ranking difference, but original inputs/ranking remain unproven. |
| Historical AlphaForge | 37,776 hourly marks; matches retained study hash | Historical control with inherited reconstruction and execution limitations; not the proposed spot restart. |
| Historical AlphaTrend | 5,133 marks; matches retained study hash | Original construction. It is not the newly tested raw-label/payable-dividend candidate. Substitution would create a new comparison. |
| Historical AlphaVintage | 6,296 probe marks; matches retained study hash | The associated CPI probe result says KILLED. It is not qualified evidence for a newly admitted sleeve merely because it appears in the historical book. |
| Latest AlphaTrend comparison | Registered paths 239/240, both preserved | Development comparison; candidate rejected. Not independently validated or a combined-book test. |
| Paper flagship | 35 marks, Aug 7–Sep 12; recorded cumulative return -2.72169% | Short paper-only record, not a mature Sharpe estimate or funded portfolio. A date-gap issue is documented below. |

The retained historical study uses a 1,061-calendar-row common window, July 7, 2023–June 1, 2026. It omits COVID and 2022. Its reported p95 modeled maximum drawdown is 16.45%, versus expected maximum drawdown 9.32%. Passing the expected figure does not satisfy the owner's stricter 11% objective. These are retained study figures, not new simulations.

## Confirmed measurement defects and limits

1. **Initial drawdown omitted by historical combiner.** A synthetic equity path 100 -> 90 -> 90 produces combined equity [0.9, 0.9] and reported maximum drawdown 0.0. The correct drawdown magnitude from starting capital is 10%. `book.py` computes its running peak without the initial 1.0. This proves an edge-case defect, not the size of any correction to the retained market study. Production remains unchanged.
2. **Multi-day paper interval labeled daily.** The saved flagship jumps from August 8 to August 11. It has 34 adjacent-mark returns, but only 33 one-day intervals. The maturity artifact labels these consecutive daily returns; the inspected evaluator checks increasing dates but does not enforce one-day spacing. Preserve all marks and the multi-day return; do not invent August 9/10 values. No mature Sharpe was published by that artifact, so no established performance claim is overturned here.
3. **Calendar-gap padding in the historical combiner.** A synthetic missing-day curve assigns zero to the missing date and the accumulated return to the next available date. The implementation cannot distinguish a legitimate market closure from missing data without external calendar/coverage evidence. Sleeve-specific economic start/end timestamps must be bound before combining equity-session labels with crypto UTC marks.
4. **Overlay and financing evidence incomplete for the new objective.** The combiner adds the overlay return series without a separate order/cash/financing ledger. The market-factor source uses a BTC perpetual price proxy and SPY prices; this is not proof of financed, net executable overlay returns. Full-book reallocation costs are not independently measured by summing already-costed sleeve curves.
5. **Risk-free benchmark unspecified for qualification.** Existing book Sharpe uses mean raw return divided by volatility. A dated cash/excess-return benchmark and its treatment of collateral, borrow and financing must be frozen prospectively before evaluating the new net Sharpe objective.

## Verification and next phase

All four historical curve hashes match the retained study; timestamps are unique and increasing and equity values positive/finite. All captured source files remained byte-identical over capture. Both synthetic checks reproduce. These checks establish local artifact identity and the stated arithmetic behavior, not current deployment, broker authentication, full-chain verification or independent research validity.

**Next proposed phase:** implement isolated regression-tested corrections for initial drawdown and irregular forward intervals, retain old artifacts, and produce a versioned measurement comparison on the same saved observations. Then specify a portfolio evaluation contract with exact book/overlay identities, economic-time alignment, financing, stress horizons and prospective acceptance rules. Do not launch a new return experiment until those inputs are concrete.

Progress this phase: baseline inventory and measurement defects established; no new sleeve admitted and no algorithm-performance improvement demonstrated.
