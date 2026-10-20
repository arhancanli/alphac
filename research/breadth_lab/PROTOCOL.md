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

## Amendment 4 (2026-10-20): round 3, pods and flexible admission, written before any round-3 return was computed

Owner, 2026-10-20: "lets try to get to 10k sleeves all with very very weak corellations and dont
make the juding rubric on whether we shuld get the sleeve or not so strict be flexible", and the pod
structure he asked for on 2026-10-12 ("run it like citadel ... hundreds of these pods and each
consists of levers which make each other stronger"). The governing rule (config/owner_goals.json,
2026-10-20): correlation between sleeves matters most; be flexible about each sleeve, never about
correlation. Round 3 uses the search years only (stocks 1998-2017). No round-3 return on the test
years is computed; the stock test window was used once (amendment 2) and any second look is the
owner's decision and is counted as a trial. Nothing is admitted to the paper book.

**Candidate sleeves.** Every overlapping-portfolio stock signal registered in rounds 1 and 2,
signed at the signal level by its search-year book Sharpe before costs (as round 1), built in three
cell schemes, with the same costs, borrow, market hedge and volatility scaling as rounds 1-2:
- `ind48`: each Fama-French 48 industry (the round 1-2 sleeves);
- `ind48xL`, `ind48xS`: each industry split at its median 63-day dollar volume on every rebalance date
  (larger and smaller names), each half normalized to gross 1 inside the industry;
- `ind150`: each of Sharadar's 150 industries.
A cell needs at least 6 eligible names on a rebalance date (flexible; rounds 1-2 used 10).

**Pods.** Signals are grouped into pods by joining signal books whose weekly correlation is 0.5 or
more in absolute value (average linkage, `effective_bets.idea_clusters`). A pod is one idea; its
sleeves are its levers.

**Admission (flexible, correlation first).** A candidate is admitted when all three hold:
1. its search-year Sharpe after its own costs is above 0 (it pays for itself; no t-statistic bar);
2. its weekly correlation with every sleeve already admitted in its pod is below 0.5 in absolute
   value (no near-duplicates);
3. its average weekly correlation with all sleeves already admitted is below 0.05 (weakly
   correlated with the book).
Order: inside each pod by Sharpe after costs, pods taken in turn. Correlations use weekly sums and at
least 104 shared weeks; pairs with fewer shared weeks count as 0.

**The central layer.** Equal weight on sleeves inside a pod (each sleeve is already scaled to 10%
volatility); pods weighted in proportion to 1 / (1 + their average correlation with the other
pods); the sum scaled to the 10% target with a trailing volatility, lagged a day. A pod brake is
reported beside the plain book: a pod's weight halves when its own shadow record is 5% below its
peak and goes to zero at 7.5%, judged on yesterday's record.

**Reported.** Candidates; admitted sleeves; effective independent bets at the sleeve level
(participation ratio N^2 / sum of squared correlations), the pod level and the idea level; book
statistics on the search years with and without the brake; and a split check: admission run on
1998-2007 alone, the book's 2008-2017 record reported as it comes out.

## Amendment 5 (2026-10-20): round 3, variant B, written AFTER round 3's split result was seen

Round 3 as specified (amendment 4) came out: 10,785 candidates, 2,715 admitted, average pairwise
correlation 0.0075, 255.5 effective bets at the sleeve level and 11.3 across 20 pods; search-year
book 3.66 (selection on the same years, not evidence). Split check: chosen on 1998-2007, the book's
2008-2017 Sharpe was -0.90 (-0.18 with the pod brake). Diagnosis: the 2,167 sleeves carried into
2008-2017 averaged a Sharpe after costs of 0.355 on the years that chose them and -0.013 after;
49% were positive. A per-sleeve bar of "positive after costs" selects luck, and breadth multiplies
whatever average edge is left. Round 3's result stands as recorded.

Variant B, a second trial on the same split, chosen after seeing that result: flexible about each
sleeve, strict about the family.
- A family is one signal in one cell scheme. Its book is the equal-weighted mean of its sleeves,
  scaled to the target volatility with a trailing volatility, lagged a day (`lab.book`).
- A family is admitted when its book's Sharpe after costs on the selection years is at least 0.3,
  and the signal's sign recomputed on the selection years alone (48-industry book before costs)
  agrees with the sign the sleeves were built with; a signal whose sign disagrees is left out.
- Every sleeve of an admitted family with at least three years of data is kept, whatever its own
  Sharpe, except that the correlation rules of amendment 4 still apply: below 0.5 in absolute value
  with every sleeve already admitted in its pod, and an average below 0.05 with all admitted.
  Order: families by their book's Sharpe inside each pod, pods in turn; sleeves in a fixed order.
- Reported exactly as round 3: the 2008-2017 book chosen on 1998-2007, with and without the brake,
  and the search-year book labelled as chosen on its own years.
Both trials are logged in the ledger.

## Amendment 6 (2026-10-20): round 3 traded as one netted account, written before it was computed

Variant B's split selection (amendment 5, chosen on 1998-2007) is traded as one account, the way
`book.py` trades rounds 1-2: every sleeve's stock positions are summed first, so opposite trades in
the same stock cancel before any cost is paid; the market hedges are one position; costs are paid
on the account's net trades, plus borrow on its shorts. Each sleeve enters with its own leverage
and hedge ratio (recomputed exactly as built), at the weight W_pod / n_pod: pods weighted by
1 / (1 + their average correlation with the other pods) on 1998-2007, equal weight inside a pod.
The account is scaled at month ends to the 10% target with its trailing volatility (cap 20x, as
`book.py`). Reported for 2008-2017, before and after costs, with no band and with the round-1
frozen no-trade band of 1.5. Nothing else is chosen in this step.

## Amendment 7 (2026-10-20): the netting law, written before it was computed

A measurement of costs, not of returns, on the search years (1998-2017); nothing is selected. For
every one of the 10,785 round-3 candidate sleeves, its stock positions (cell weights times its own
leverage, held between rebalances as `book.py` does) are sampled on a weekly grid. For K in 10, 30,
100, 300, 1,000, 3,000 and all sleeves, random sets of K sleeves (seeded; 20 sets at K <= 100, 5 at
300 and 1,000, 2 at 3,000, the full set once) are combined at equal weight, and two costs are
computed with the round-1 cost per name: the sum of what each sleeve pays for its own trades, and
what one account pays for the summed positions' trades. Reported: the netted share of the summed
cost by K, and the slope of its logarithm against log K (independent trades give -0.5 once
sleeves overlap in the same names; none at all give 0).

## Amendment 8 (2026-10-20): variant C, admission on marginal netted cost, written before it was computed

The netting law says a sleeve inside a full-breadth account pays about 30% of its standalone cost.
Variant C judges families on that marginal cost instead of the standalone cost:
- The full-breadth netted share s is measured again on the selection years alone (1998-2007, all
  candidate sleeves with three years of data there, one draw), so nothing from 2008-2017 enters.
- Each sleeve's return at marginal cost is its before-cost return minus s times its standalone cost
  (before-cost minus after-cost return).
- A family is admitted when its book's Sharpe at marginal cost on 1998-2007 is at least 0.3 and its
  sign agrees (as variant B). All its sleeves are kept, subject to the correlation rules of
  amendment 4, in the same order as variant B.
- The selection is traded as one netted account exactly as amendment 6 (no band, and band 1.5), and
  its 2008-2017 record is reported as it comes out, beside variant B's.
