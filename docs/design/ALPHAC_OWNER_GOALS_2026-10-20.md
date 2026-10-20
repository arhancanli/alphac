# AlphaC owner goals — October 20, 2026: correlation first

This records the owner's governing rule for ALPHAC as he stated it on 2026-10-15, 2026-10-17 and
2026-10-20, and his approval on 2026-10-20 to make it the headline of `config/owner_goals.json`.
It adds to the goals of 2026-09-12/14 (`ALPHAC_OWNER_GOALS_2026-09-12.md`); nothing there is
removed. None of it is established by this document.

## The owner's words

- 2026-10-15: "test some ideas and remember at such volume sleeves we can be very flexible as long
  as just the corelation is very weak between sleeves it will be an abselute gold mine and also when
  testing and trying to find things be very very flexible and dont be rigit use your superior
  intelligence and reasoning to get us to 1000 sleeves"
- 2026-10-15: "we find the perfect formula on how to get un imaginable sharpe ratios through tens of
  thousands of sleeves with low corellation"
- 2026-10-15: "we have to think far bigger for alphac like get it to the completely next level as i
  said tens of thousands of sleevs and make it the best engine in the whoel world of quant and
  finance"
- 2026-10-17: "we need the sharpe ratio to be far beyond that for the algorithm alphac since remember
  we discuessed the importance of sleevss and there corellation and that how we could derive
  nomrally impossible statistics through it"
- 2026-10-20: "remember the thing with the breath lab and all of the hundreds of thousands of sleeves
  and also when i told you the thing that matters most is the corellation and also make sure you
  grasp everything"
- 2026-10-20, asked whether to change this file to the rule: "yes change it bro"

## The rule

1. **Correlation between sleeves is what matters most.**
2. **Be flexible about each sleeve, never about correlation.** A sleeve may be individually weak if
   it is weakly correlated with the book and clears its own costs. Costs do not diversify.
3. **Scale: hundreds of thousands of sleeves** (recorded as at least 100,000). Earlier: 14
   economically distinct (2026-09-14), 1,000 and tens of thousands (2026-10-15).
4. **Payoff: a combined Sharpe far beyond 2**, on the ladder 2, then 3, then 5 and beyond.

## The arithmetic that makes correlation the binding quantity

Book Sharpe ≈ average sleeve Sharpe after costs × √(effective independent bets), and

    effective bets = N / (1 + (N − 1) · ρ̄)  ≤  1 / ρ̄

so adding sleeves pays only as the average correlation falls toward 1/N. The breadth lab measured
sleeve correlation 0.017 (at most about 59 independent bets however many sleeves) and signal-family
correlation 0.155; on 2026-10-20 its 1,026 stock sleeves held 5.6 effective independent bets at the
family level (`research/breadth_lab/effective_bets.py`). 100,000 sleeves at ρ̄ = 0.0001 would hold
about 9,100.

The headline measure is therefore **effective independent bets** (participation ratio of the family
books' correlation matrix), always reported beside the sleeve count. Ladder from the long-term plan:
at least 25 by mid-2027, at least 100 by end-2027, several hundred in the fund era.

## What does not move

The 2026-09-14 goals stay the checkpoints the engine evaluates today: combined forward Sharpe above
2 (the first rung), at least 14 qualified economically distinct sleeves (the first 14 independent
ideas) and realized maximum drawdown at most 10%. The forward-evidence contract, its target history
and the forward record are unchanged. Until a family admission path is written and approved,
`config/sleeve_admission_contract.json` stays the admission rule in force; the rule above is the
direction that path must serve.

## Claim boundary

Targets, not results. A rung of the Sharpe ladder is claimed only on a forward record after real
costs long enough to tell it from luck. Real money follows the legal path only.
