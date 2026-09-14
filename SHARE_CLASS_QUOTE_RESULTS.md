# Share-class quote feasibility — 11 September 2026

Databento returned three fixed historical samples containing 94,920 MBP-1
records. Total quoted retrieval cost was $0.028883, below $1; actual invoice
charges were not independently checked. All three file hashes verify.
No pair spread, return, Sharpe or trading signal was calculated.

## Fixed coverage test

The original sample requested GOOG, GOOGL, BRK.A and BRK.B on EQUS.MINI and
XNAS.ITCH from 14:00 to 14:02 UTC on August 12, 2025. Before inspecting the
coverage results, the audit fixed 60 one-second clocks from 14:01:00 through
14:01:59 UTC, a maximum event/receive age of one second, and at most 100 ms
difference between the two legs' receive timestamps.

At each clock, select the latest received observation before filtering quality.
Do not recover an older favorable quote when the latest update is invalid.
Reject trade/reset rows, incomplete events, flagged books, invalid/crossed prices,
empty sizes, future event times and stale observations. These are diagnostic
limits, not calibrated execution latencies or a validated liquidity model.

| Feed | Pair | Both legs pass, including receive skew | Test clocks |
|---|---|---:|---:|
| EQUS.MINI | GOOG / GOOGL | 47 | 60 |
| XNAS.ITCH | GOOG / GOOGL | 53 | 60 |
| EQUS.MINI | BRK.A / BRK.B | 0 | 60 |
| XNAS.ITCH | BRK.A / BRK.B | 0 | 60 |
| XNYS.PILLAR, follow-up | BRK A / BRK B | 9 | 60 |

Alphabet's remaining clocks failed quote skew, except one Nasdaq clock rejected
because its latest GOOGL row was a trade. These observations do not establish
which feed is economically superior or that the passing quotes could fill orders.

## Berkshire symbol and warm-up investigation

BRK.A resolves in EQUS.MINI's daily symbology but has no observations in the
initial two-minute sample. It does not resolve in XNAS.ITCH on that date.
Neither fact alone establishes that the security is universally unavailable.
NYSE's primary feed resolves the CMS-style symbols `BRK A` and `BRK B`, rather
than their dotted forms. The saved resolution responses establish that mapping.

The NYSE follow-up started at 13:30 UTC, allowing 31 minutes of history before
the unchanged evaluation minute. Both securities are present. Of 60 clocks,
9 passed, 5 failed skew, 10 had both legs stale, 26 had only B stale, and 10 had
an A-valid/B-trade combination. A quiet but standing quote can fail an update-age
limit; these counts alone do not prove absent liquidity. We did not relax the
limit to improve the outcome.

The follow-up receipt's generic scope text says two minutes, inherited from the
initial script. Its explicit request timestamps correctly record 32 minutes;
those parameters govern the actual request. The script wording is now corrected.
The earlier SDK pricing argument failure occurred before any purchase and is
preserved separately in `evidence/share-class-quotes/`.

## Feed and legal scope

EQUS.MINI combines quotes from its component venues and anonymizes originating
venues. It is not being certified here as full SIP NBBO or a routable venue.
Nasdaq and NYSE direct feeds represent their respective venues; do not sum their
liquidity with the derived feed because constituents can overlap. Quantities are
shares, including odd lots. [Databento MINI specification](https://databento.com/docs/venues-and-datasets/equs-mini),
[equity conventions](https://databento.com/docs/examples/equities/equities-introduction).

Dated SEC evidence now precedes the sample: Alphabet's June 2025 10-Q was filed
July 24 and identifies GOOG/GOOGL's classes; Berkshire's June 2025 10-Q was filed
August 4, and note 18 confirms the 1:1500 economic ratio and one-way conversion.
This is corroboration, not a complete intervening-amendment audit.
[Alphabet filing](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000062/0001652044-25-000062-index.htm),
[Berkshire filing](https://www.sec.gov/Archives/edgar/data/1067983/0000950170-25-101578-index.htm),
[Berkshire note 18](https://www.sec.gov/Archives/edgar/data/1067983/000095017025101578/R27.htm).

## Validation and next work

Ten tests pass for lookahead prevention, latest-bad-row handling, receive ordering,
staleness, flags, trade rejection and invalid books. All changed Python scripts
pass Ruff. Evidence includes acquisition receipts, symbology checks, per-clock
coverage results and the pre-sample filing ledger.

The quote-access question is partially resolved: we can acquire observations for
both pairs using the appropriate feeds. Next, fix the actual execution venue,
market-status coverage, borrow/fees and treatment of standing quotes, then choose
one hypothesis and register it before examining returns. No new sleeve is admitted.
