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
