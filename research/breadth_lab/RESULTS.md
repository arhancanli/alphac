# Breadth lab: results

Test run on 2026-10-15. The selection was frozen on search years (`frozen_selection.json`, sha256
`8d1803de…`, pushed before the test). Numbers are from `test_result.json`.

## What was built

1,285 sleeves: 1,026 stock sleeves (27 signals, each run inside every industry with at least 10
names, long the best-ranked and short the worst) and 259 crypto sleeves (cash-and-carry per coin:
long spot, short the same coin's perpetual, on while funding pays). All of them were found on search
years and then tested once on years the search never saw.

## On the untouched years

| Block | Test years | Sharpe after costs | Before costs | Worst drawdown |
|---|---|---|---|---|
| Stocks, 1,026 sleeves | 2018-01 to 2026-06 | 0.73 (t 2.1) | 0.85 | −15% |
| Crypto, 259 coins | 2023-01 to 2026-09 | 4.19 (t 8.0) | 8.03 | −6% |
| Both at equal risk | 2023-01 to 2026-06 | 3.42 (t 6.4) | | −17% |

The two blocks' correlation was 0.02. The stock block earned about half its search-year figure (1.43),
the usual decay for published anomalies.

## The recent years are the warning

| Year | Stocks | Crypto | Both |
|---|---|---|---|
| 2023 | 1.54 | 7.12 | 4.59 |
| 2024 | 2.13 | 11.99 | 8.05 |
| 2025 | 0.31 | 0.42 | 0.41 |
| 2026 to date | −0.05 | −3.01 | −2.05 |

Since January 2025 the combined book's Sharpe is −0.44. The crypto carry collected 0.045% a day in
funding in 2024, 0.0095% in 2025 and about zero in 2026: the income it lives on has been competed
away, and switching coins on and off around zero funding now costs more than it earns.

## What the search taught

- Sleeves of one signal across industries are weakly correlated (0.03 to 0.19 on average), so a
  thousand of them behave like many independent bets. Being selective hurt: keeping every signal
  beat keeping only the strongest, on the split inside the search years too.
- Costs do not diversify. Every sleeve's costs add up while its noise cancels, so a book of weak
  sleeves is only as good as their edge after costs. Holding overlapping portfolios and trading
  through a no-trade band cut the stock book's costs from 5.7% to 1.2% a year.

## One error, and how it was handled

The first test run omitted the frozen no-trade band (a runner bug). Its result is published as
`test_result_run1_without_frozen_band.json` (stocks 0.52, combined 3.16). The corrected run applies
the band the frozen file already named; nothing in the frozen file changed.

## What this does not establish

No sleeve here is admitted to the paper book. The 100-odd variants in `ledger.jsonl` join the trial
accounting before any admission. The forward paper record is the only clean test left, and the
recent years say the edge may be thinner now than the test window's average.

## How many distinct ideas the stock book holds (2026-10-20, search years only)

`effective_bets.py` counts independent bets at three levels (weekly returns, 1998-2017, the 27 frozen
signals; output `var/breadth_lab/effective_bets_search.json`):

| Level | Count |
|---|---|
| Sleeves | 1,026 |
| Independent bets across sleeves | 158 |
| Signal families | 27 |
| Independent bets across family books | 5.6 |
| Ideas (families joined while their books correlate 0.5 or more) | 9 |

The sleeve-level 158 counts industry noise that carries no edge; the family level is the honest count.
The nine ideas: momentum and value together (8 signals), low risk and liquidity (5), profitability (4),
growth and long-term reversal (3), cash yields and issuance (3), and four on their own: accruals,
overnight returns, weekly reversal, seasonality. More signals inside these groups add almost nothing.
New ideas have to come from new data or new markets.

## Round 3: pods and flexible admission (2026-10-20, search years only)

The owner asked for 10,000 sleeves with very weak correlations and a flexible bar, organized as
pods. 52 stock signals were built in four cell schemes (48 industries, each industry's larger and
smaller names, 150 industries): 10,785 candidate sleeves. Signals that move together form a pod.
The correlation side worked: 2,715 sleeves were admitted with an average pairwise correlation of
0.0075, 255.5 independent bets across sleeves and 11.3 across 20 pods.

The bar did not survive the split check (chosen on 1998-2007, run on 2008-2017):

| Admission | 2008-2017 book | With pod brakes |
|---|---|---|
| Each sleeve positive after its costs (amendment 4) | -0.90, drawdown -62% | -0.36, drawdown -19% |
| Whole families judged, all their sleeves kept (amendment 5, chosen after seeing the first) | -0.13, drawdown -43% | 0.22, drawdown -14% |

The sleeves the first rule chose averaged a Sharpe of 0.355 after costs on the years that chose
them and -0.013 afterwards, 49% of them positive: a per-sleeve bar, however low, selects luck, and
breadth multiplies whatever average edge is left, here slightly below zero. Judging families
instead raised the out-of-sample average to 0.025 and the book to about break-even; the pod brakes
cut the drawdowns by more than half. The search-year books (3.66 and 1.08) were chosen on their own
years and are not evidence.

One error, fixed and published: the first central layer re-levered braked books back to the
target volatility, which undid the brakes and, when every pod was braked, divided by almost zero.
The book is now sized from the plain book and capped at 5x; both runs are in the ledger before and
after the fix.

What it means: US stock anomalies charged their own costs one sleeve at a time carry almost no edge
in 2008-2017, so more sleeves of them cannot raise the Sharpe. Two levers remain. Costs: thousands
of sleeves trade the same stocks, so a netted book with a no-trade band pays far less than the sum
of the sleeves (rounds 1-2 cut the stock book's costs from 5.7% to 1.2% a year that way); the
round-3 families have to be judged as a netted book next. New ideas: pods from other markets and
data, each with its own edge.

## Round 3, traded as one account: the crossing dividend (2026-10-20)

The family selection above (58 families, 1,163 sleeves, chosen on 1998-2007) was traded the way
one account would trade it (amendment 6): every sleeve's stock positions summed first, so opposite
trades in the same stock cancel before any cost is paid. Same sleeves, same years, 2008-2017:

| How costs are paid | Costs a year | Sharpe after costs | Sharpe before costs | Drawdown |
|---|---|---|---|---|
| Each sleeve pays for its own trades | about 11% | -0.13 | 1.02 | -43% |
| One netted account | 3.4% | 0.59 (t 1.9) | 1.02 | -26% |
| Netted, with the round-1 no-trade band of 1.5 | 1.3% | 0.82 (t 2.6) | 1.06 | -19% |

Before costs the edge is the same in every row: sleeves averaging a Sharpe of 0.12 before costs
(0.025 after their own costs) make a book of about 1.0, the breadth arithmetic working out of
sample. What changes is what the trading costs. Thousands of sleeves trade the same stocks in
opposite directions; the account pays only for the net, so costs grow far more slowly than the
number of sleeves while the edge grows with it. A sleeve that cannot pay for itself alone can still
add to a large netted book, which is why a per-sleeve cost bar is the wrong bar at breadth. Next:
measure how the netted cost per sleeve falls as the number of sleeves grows (10 to 10,000), and
judge a sleeve by its edge against its marginal cost inside the netted account.

Caveats: one split, and variant B was chosen after seeing round 3's first result (amendment 5);
the band of 1.5 is round 1's frozen value, not tuned here; the 1998-2007 figures (1.8-1.9) are on
the selection years. Netting across sleeves is standard practice at multi-strategy funds; the
measurement at this breadth is the new part, and novelty is not claimed before a prior-art check.
