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
