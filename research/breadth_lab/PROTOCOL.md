# Breadth lab: protocol

Written 2026-10-15, before any return was computed.

## The question

The owner's goal moved on 2026-10-15 from 14 sleeves to 1,000: "at such volume sleeves we can be very
flexible as long as just the correlation is very weak between sleeves". The arithmetic agrees: a book
of N sleeves with mean Sharpe s and average pairwise correlation r has Sharpe
s * sqrt(N / (1 + (N - 1) * r)). Many weak sleeves make a strong book when r is near zero, but only
if each sleeve's edge is real. A flexible search finds sleeves that look good on the data it searched
and earn nothing afterwards, so the search and the test use different years.

## The one rigid rule

- Search years: 1998-01-01 to 2017-12-31. Everything is allowed here: any signal, any
  parameter, any grouping, any selection rule, as many tries as needed.
- Test years: 2018-01-01 to 2026-09-30. No return, correlation or score dated in these years
  is computed until the selection is frozen: the frozen file is committed and its sha256 is
  recorded here before the test years are opened. The test is run once and reported whatever
  it shows.
- The search ledger (`ledger.jsonl`) records every variant tried, with its search-year result,
  so the size of the search is public.

## What a sleeve is here

One signal, run inside one group of stocks (a Fama-French 48 industry, or a sector for signals
that need more names), dollar neutral: long the best-ranked half, short the worst-ranked half,
rebalanced on a fixed schedule, net of trading costs and borrow, scaled to the same risk.

## Data

US common stocks and ADRs from the Sharadar lake (`data/lake_sharadar`), daily, with the reader's
corrected splits and dividends (total return). Eligible on each rebalance date: price at least $5 and
63-day median dollar volume at least $5 million. Industry and sector come from Sharadar TICKERS (the
latest label, not point-in-time: a stated limit).

## Costs

One-way cost per name by 63-day median dollar volume: 10 bp from $50 million, 20 bp from
$10 million, 40 bp below. Borrow: 50 bp a year on the short side. Costs are charged per sleeve
before netting across sleeves, which overstates them for a combined book.

## What is not established by this lab

Admission. A sleeve enters the paper book only through the admission contract, and every variant in
the ledger joins the trial accounting first. The forward paper record stays the final judge.

## Amendment 1 (2026-10-15, before any crypto return was computed)

- The stock data ends on 2026-06-18 (the Sharadar lake was last loaded in June), so the stock test
  years run 2018-01-01 to 2026-06-18.
- Crypto sleeves (Binance spot, perpetuals and funding, which start in 2020) use their own split:
  search 2020-01-01 to 2022-12-31, test 2023-01-01 to 2026-09-30, under the same rules.
- Search results so far (17 price signals and 14 fundamental signals inside 39 industries) are in
  `ledger.jsonl`; every one of them was computed on search years only.

## Amendment 2 (2026-10-15): the freeze

The selection is frozen in `frozen_selection.json`, chosen from search years only:
1,026 stock sleeves (27 signals held as overlapping portfolios, in every industry with at least
10 names, netted into one book with a no-trade band of 1.5), crypto cash-and-carry per coin
(30-day funding lookback), and the two blocks at equal risk. The search ledger lists the 100-odd
variants tried before it.

frozen_selection.json sha256 8d1803de7e04d3ee16b5d9aa6f4aa5504ba79bd02a6268a7117972a3b615f786

`test.py` refuses to run unless the file still has this sha256. It is run once, and its result is
published whatever it shows.

## Amendment 3 (2026-10-15): round 2, written before any round-2 return was computed

Round 1 is tested (`RESULTS.md`). The owner asked to keep improving. Round 2 keeps the rigid rule
(every choice on search years only) with one honest difference: the test years have now been seen
once, so round 2's test is a second look, not an untouched one. It is reported next to round 1's,
and the ledger carries both rounds' variants. Only data after today (the forward paper record) is
fully clean.

What round 2 may add, all chosen on search years:

- Stocks (search 1998-01-01 to 2017-12-31, test 2018-01-01 to 2026-06-18): new fundamental signals
  from the full Sharadar SF1 file (as-reported quarterly rows, usable from their SEC filing date,
  as in the lake), new price signals, and changes to how sleeves are weighted and hedged in the book.
- Futures, a new block: one sleeve per market and signal (trend at several horizons, carry from the
  curve), from the Databento CME daily contracts in `data/lake_fut_db` (37 markets from June 2010;
  each contract's expiry year is inferred from the bar's date, because CME symbols carry one year
  digit). Search 2010-06-06 to 2017-12-31, test 2018-01-01 to 2026-06-26. Earlier ALPHAC research
  (the AlphaTrend family) already looked at trend on futures in these years, so this block's test
  is not untouched either. Costs one way: 2 bp for equity index, rates and currency futures, 5 bp
  for energy, metals and grains, 10 bp for thin markets (livestock, oats, palladium, platinum,
  Nikkei, Russell); a roll trades both contracts.
- Crypto cross-section, a new block: signals ranked across Binance perpetuals inside liquidity
  tiers, dollar neutral, funding paid or received. Search 2020-01-01 to 2022-12-31, test
  2023-01-01 to 2026-09-30. Costs as in round 1 (15 bp one way for majors, 30 bp for the rest).
- The crypto cash-and-carry rule stays as frozen in round 1. Any new rule designed after seeing
  2025-26 can only be judged on data after 2026-09-30.

The round-2 selection is frozen in `frozen_selection_round2.json`; its sha256 is recorded here
before the test years are opened again, and the round-2 test runner refuses to run otherwise.
