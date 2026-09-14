# Merger arbitrage v2: point-in-time announcement identity

**Prepared:** 2026-08-26

**Stage:** prospective no-price, no-return identity redesign

**Family trial account:** `merger_arbitrage`

**Technical authorship approval:** not yet recorded

**Return execution authorized:** no

## Why this is a new identity

The original metadata protocol required one preceding Item 1.01 8-K inside 60 days for at least
80% of all target-side deal anchors. It failed at 67.02%. The failure was not homogeneous:
`SC 14D9` tender-offer anchors reached 86.65%, while `DEFM14A` merger-proxy anchors reached 61.33%.
The aggregate gate blended populations with different filing paths and therefore described
neither one cleanly.

That result remains failed. This protocol does not widen its window, reinterpret its gate, or
reuse the tender stratum as if it were prospective evidence. It defines a materially new identity,
keeps both strata, and reserves 2006–2015 as a disjoint confirmation period. The 2016–2025 result
may explain the redesign but may not validate it.

## Mechanism and claim boundary

The candidate is the contractual spread on an announced all-cash acquisition of a US-listed
public target. Entry cannot precede a source-bound SEC acceptance timestamp that identifies the
same target, counterparty, cash consideration, and binding merger agreement or commenced tender
offer. Rumours, press timestamps reconstructed from later documents, stock consideration, collars,
CVRs, appraisal trades, hostile proposals, and transactions without a deterministic announcement
record are outside this identity.

This protocol contains no prices, returns, break losses, Sharpe ratios, drawdowns, correlations,
capacity estimates, or sleeve-admission evidence. It spends zero return hypotheses.

## Frozen strata

Discovery begins from unamended target-side filings and never treats the discovery filing as the
historical entry time:

1. `DEFM14A` merger-proxy anchors;
2. `SC 14D9` target recommendation anchors.

Every acquisition, extraction, coverage, and accuracy statistic is reported separately by stratum.
Both strata must pass. An aggregate result cannot rescue a failed stratum, and no row may be moved
between strata after its documents are read.

## Announcement resolver

For each anchor, search at most 365 calendar days backward using only filings accepted no later
than the anchor. The broad search interval locates source documents; it is not a trading window and
does not authorize backdating.

Eligible source classes are:

- target 8-K Item 1.01, 7.01, or 8.01 filings and their merger-agreement or press-release exhibits;
- target `PREM14A` or `DEFA14A` filings carrying the agreement parties and cash terms; and
- bidder `SC TO-T` filings linked to the target through the filing header's subject-company CIK.

A document qualifies only when the point-in-time text resolves the target CIK, one named
counterparty, one cash consideration, and binding-agreement or commenced-offer language. The
resolver selects the earliest SEC acceptance timestamp among qualifying documents. A later filing
may confirm an earlier filing's meaning but may not move the timestamp backward. Conflicting
counterparties, consideration values, transaction types, or subject-company links produce
`UNRESOLVED_CONFLICT`, not a discretionary choice.

The required resolver states are:

- `RESOLVED_CASH_MERGER`;
- `RESOLVED_CASH_TENDER`;
- `UNRESOLVED_NO_QUALIFYING_SOURCE`;
- `UNRESOLVED_CONFLICT`;
- `OUT_OF_SCOPE_NON_CASH_OR_COMPLEX_CONSIDERATION`.

## Disjoint confirmation corpus

The confirmation interval is 2006-01-01 through 2015-12-31, disjoint from the 2016–2025
exploratory result. No confirmation filing, document, machine prediction, or human label has been
opened for this design.

After Arhan's technical approval, acquire official SEC metadata in deterministic order. Within
each `(year, stratum)` cell, rank anchors by
`sha256("alphac-merger-announcement-confirmation-v2|" + year + "|" + stratum + "|" + accession)`
and retain the first 20 eligible anchors. The target is 200 anchors per stratum and 400 total.
Fewer than 20 eligible anchors in any cell produces `DATA_GATED_NO_CROSS_CELL_SUBSTITUTION`.

Selection uses no document text, machine prediction, human label, price, return, or realized deal
outcome. All accessions from the 2016–2025 exploratory corpus are excluded even though the periods
are already disjoint.

## Independent review gates

An independent reviewer, blind to machine outputs and all prices and returns, labels every selected
anchor from the frozen source packet. AI or automated labeling assistance is prohibited. Raw
confusion counts and unresolved cases are published.

Each stratum independently requires:

1. point announcement coverage of at least 0.80 and a one-sided 95% exact lower bound of at least
   0.75;
2. same-transaction linkage accuracy with a one-sided 95% exact lower bound of at least 0.95;
3. exact SEC acceptance-timestamp agreement with a one-sided 95% exact lower bound of at least
   0.90;
4. later Item 2.01 or 1.02 outcome-marker coverage of at least 0.70 and a one-sided 95% exact lower
   bound of at least 0.65; and
5. complete CIK, accession, form, acceptance timestamp, primary-document, archive-URL, and
   SHA-256 lineage for every selected row.

Coverage denominators include unresolved rows. Accuracy denominators include every machine-resolved
row; a small denominator cannot pass by omission. Underpowered denominators remain data-gated.

These thresholds do not prove alpha. They establish only that the event clock and transaction
identity can be reconstructed without hindsight at the declared error rate.

## Fail-closed sequence

1. This technical draft must pass its structural audit.
2. Arhan independently reviews and either approves the exact design or records required changes.
3. Only an approved hash may activate metadata and document acquisition for the disjoint corpus.
4. The frozen corpus must pass both strata and the independent-review gates.
5. Only then may a separate return preregistration bind instruments, sizing, financing, borrow,
   dividends, delisting treatment, costs, halts, breaks, amendments, capacity, stress tests, and
   the complete admission contract.

No automation may supply Arhan's approval, acquire the corpus before approval, open market data,
or interpret a technical pass as a sleeve admission.
