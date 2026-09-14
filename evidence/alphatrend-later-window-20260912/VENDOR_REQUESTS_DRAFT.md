# Vendor clarification drafts — not sent

These requests concern retained historical responses. Please provide original and corrected values, adjustment basis, correction/publication timestamps, and a dated authoritative source. Please distinguish ex-date, record date and payable date; we will preserve original responses alongside any revision.

## Sharadar: two unresolved FUNDS price records

Our raw-price reconstruction multiplies O/H/L by closeunadj/close and uses closeunadj as close. Please verify all source fields and the reconstructed raw prices for:

| Symbol | Session | Raw open | Raw high | Raw low | Raw close |
|---|---|---:|---:|---:|---:|
| DBA | 2007-01-08 | 35.94 | 35.94 | 24.84 | 24.98 |
| UUP | 2007-06-20 | 28.97 | 28.97 | 24.08 | 25.07 |

Archived alternate-feed same-session OHLC ratios disagree. Our recent Alpaca SIP requests returned no bars for these dates, so they do not establish corrections. Are these source-field errors, mixed adjustment bases, or valid observations? Please provide corrected records if applicable.

Additional quality questions, separate from the two unresolved price flags:

- USO 2020-04-09: our reconstructed open was 5.41; raw SIP open 5.40 agrees with the archived alternate-feed ratio. We revised only our separate research snapshot's open to 5.40. Source-imputed volume remains 302,312,816 versus SIP 304,930,827. Please explain the price and volume differences and volume basis.
- UUP 2007-03-15: OHLC all 24.96, volume zero. Please identify whether this is a no-trade observation, carried price, or missing volume.

Local supporting evidence: `../alphatrend-price-repair-20260912/price_review.json`, raw SIP responses and receipts there, and `../alphatrend-quality-routing-20260912/quality_tagged_panel.parquet`. Do not attach credentials or request URLs containing keys.

## State Street: SPY historical payment date

Please confirm the payable date for SPY's 2006-06-16 ex-dividend event (our retained source cash is rounded to 0.555/share). In the retained historical-distributions workbook, the payable date is 2006-06-16, preceding the record date 2006-06-20. We have therefore left the payment date unresolved. Please supply a dated distribution notice and confirm amount/record/payable dates.

Workbook source: https://www.ssga.com/library-content/products/fund-data/etfs/us/spdr-etf-historical-distributions.xlsx

Retained workbook and receipt: `../alphatrend-dividend-recovery-20260912/`.

## Invesco and Polygon: FXE payment-date discrepancies

Please identify the official payable date for each event and explain the one-day discrepancy between the two retained histories:

| FXE ex-date | Polygon payable date | Invesco payable date |
|---|---|---|
| 2007-04-02 | 2007-04-09 | 2007-04-10 |
| 2008-07-01 | 2008-07-08 | 2008-07-09 |
| 2011-10-03 | 2011-10-11 | 2011-10-10 |

Are these different definitions (official payable date versus processing date), or historical corrections? Please provide distribution notices or equivalent dated records, not an inferred business-day adjustment.

Invesco product: https://www.invesco.com/us/en/financial-products/etfs/invesco-currencyshares-euro-trust.html

Retained Invesco response, receipts and conflict table: `../alphatrend-payment-source-review-20260912/`. Polygon originals: `../alphatrend-full-dividend-reference-20260912/`. Current unresolved rows: `../alphatrend-efa-event-review-20260912/remaining_gaps.parquet`.
