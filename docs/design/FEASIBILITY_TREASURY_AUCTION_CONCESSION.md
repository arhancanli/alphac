# Treasury auction concession — no-return feasibility protocol

## Scope

This stage reads only official US Treasury auction metadata. It does not load prices, calculate
returns, select an entry window, or spend a return identity. The objective is to establish that
the coupon-auction event clock can be reconstructed from fields knowable before each auction.

## Source and immutable lineage

- Source: Treasury Fiscal Data `auctions_query` API.
- Start date: 2000-01-01.
- Eligible security types: nominal `Note` and `Bond` only. Bills, TIPS and FRNs are excluded.
- Raw response is canonicalized, SHA-256 hashed and atomically stored.
- Event identity is `auction_date|CUSIP`; duplicates fail the gate.
- The emitted Parquet contains announcement-safe fields only. Auction outcomes such as high
  yield, allocations and bid-to-cover are deliberately excluded from the event manifest.

## Gates locked before execution

1. At least 1,000 eligible coupon auctions.
2. At least 500 auctions from 2013 onward, preserving a publication-aware falsification era.
3. At least 99% completeness for identity, announcement, auction, issue, term, amount and
   reopening fields.
4. Announcement date is never after auction date for at least 99% of rows.
5. At least one calendar day of notice for at least 99% of rows.
6. Event identities are unique.

Passing these gates authorizes a separate return preregistration. It does not authorize a return
test by itself. The return specification must lock duration buckets, beta hedges, event windows,
transaction costs, post-publication priority and overlap handling before opening prices.

## Kill conditions carried forward

Kill if the effect is absent after publication, reduces to duration beta, fails one-tick-plus-fee
cost stress, or exceeds 0.35 correlation with AlphaTrend. The sign and window will not be inverted
or retuned after a failed locked identity.
