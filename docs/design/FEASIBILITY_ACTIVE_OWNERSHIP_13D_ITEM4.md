# Active ownership escalation — Schedule 13D Item 4 document protocol

**Declared:** 2026-08-15 after schema-aware metadata v2 passed and before selecting the document
sample, downloading any complete submission, parsing Item 4, or opening prices/returns.
**Stage:** official document/classifier feasibility only; zero return identities are spent.

## Frozen corpus

Start from the 800-row immutable-header audit under
`artifacts/feasibility/active_ownership_13d_schema_v2/header_audit.parquet`. Keep only rows with
complete header lineage and exactly one contemporaneous domestic-common ticker interval. Within
each year, sort on SHA-256 of `year|accession` and retain exactly ten rows. The resulting 160
accessions are fixed; failures cannot be replaced.

Download the complete official SEC submission using its quarterly-index archive filename. Preserve
the compressed raw bytes, source URL, SHA-256, acceptance timestamp, subject CIK, reporting-owner
CIK, ticker interval, and accession. From each SGML submission select exactly one `<DOCUMENT>` whose
`TYPE` is the accession's exact initial form (`SC 13D` or `SCHEDULE 13D`). Multiple or absent exact
primary documents are failures, never guessed by filename order.

## Locked parser and high-precision classifier

Convert visible primary-document text with `sec-filing-sections-v2`. Extract the shortest valid
Item 4, Purpose of Transaction span ending at Item 5, Interest in Securities. Minimum length is 50
words; table-of-contents spans must fail rather than jump to a later section.

Classify a section `specific_active_intent` only when a sentence contains a concrete action phrase:
nominate or appoint directors, seek board representation, deliver an activist letter/proposal,
demand or urge a strategic review/sale/capital return/governance change, enter an agreement for a
board seat, or state an intention to engage management on one of those actions. Generic language
that the owner `may`, `could`, `reserves the right`, or will merely `review the investment` is not
specific intent. Preserve every matched sentence; no black-box score is allowed.

Extract every explicit beneficial-ownership percentage in Items 4/5 and the visible cover pages,
but do not choose a reporting-group aggregate unless the frozen audit confirms the rule.

## Machine gates

- 160/160 complete submissions download;
- at least 98% contain exactly one exact-form primary document;
- Item 4 extraction is at least 90%;
- every machine-positive classification retains at least one matching source sentence; and
- neither class is degenerate: at least 10% and at most 90% of extracted sections are positive.

Failure is `DATA_GATED` and the classifier is not revised after aggregate results.

## Frozen manual accuracy audit

Before aggregate classifier output is viewed, retain the first three frozen accessions per year as
a 48-document audit set. A manual reviewer must label `specific_active_intent` from the source and
record a representative sentence, plus the filing's reported aggregate ownership percentage when
unambiguous or `unresolved`. No row may be omitted.

Document feasibility requires:

- all 48 labels complete;
- positive-class precision at least 95%;
- positive-class recall at least 80%; and
- exact ownership-percentage/unresolved agreement at least 90%.

Until labels are complete, a machine pass is `HUMAN_AUDIT_REQUIRED`, not a pass. Even a full pass
authorizes only a separate return preregistration covering amendments, group lineage, entry timing,
controls, costs, capacity, terminal histories, deflation/PBO, and portfolio correlation.

## Primary source

- SEC EDGAR access and archive structure:
  https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data

## Locked v1 result

V1 is `DATA_GATED`. It downloaded or resolved 159/160 complete submissions, with one accession
containing two exact-form primary documents that the protocol forbids choosing between. Item 4
extraction reached 125/160, or 78.13%, below 90% required. The classifier identified 23 specific
active-intent sections among 125 extracted sections (18.40%) and every positive retained its source
sentence, but the upstream corpus gate controls. Zero prices or returns were loaded.

Machine-readable v1 result:
`artifacts/feasibility/active_ownership_13d_item4/result.json`.
