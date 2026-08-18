# Active ownership escalation — Schedule 13D Item 4 parser v2

**Declared:** 2026-08-15 after Item 4 parser v1 closed `DATA_GATED` and before running v2 aggregate
results. **Stage:** document/classifier feasibility only; prices and returns remain forbidden and
zero return identities are spent.

## What v1 proved and what v2 may change

V1 downloaded 159/160 submissions and extracted 125/160 Item 4 sections, or 78.13%, below its
locked 90% gate. The miss was directly attributable to official format variants, not a return
result: legacy headings include `Purpose of the Transaction`, plural `Transactions`, and a bare
number followed by the title on the next line; structured 2025 filings encode Item 4 as
`<item4><transactionPurpose>` and do not retain visible numbered headings. All ten structured
2025 rows therefore failed v1.

V2 keeps the identical 160 accessions, no replacements, the exact same classifier, and every v1
threshold. It may only:

1. accept optional `the` and singular/plural `transaction(s)` in legacy Item 4 headings;
2. accept `4.`/`5.` in addition to `Item 4`/`Item 5`; and
3. for exact structured `SCHEDULE 13D` XML, read `transactionPurpose` under `item4` and retain
   structured percentage fields rather than requiring headings erased by XML rendering.

The one accession containing two exact-form `<DOCUMENT>` blocks remains a failure. V2 may not
choose one. Machine and frozen 48-document manual accuracy gates remain exactly those in
`FEASIBILITY_ACTIVE_OWNERSHIP_13D_ITEM4.md`.

Passing machine gates with incomplete labels is `HUMAN_AUDIT_REQUIRED`, not authorization for
returns.

## Locked result

V2 is also `DATA_GATED`. On the unchanged 160 accessions, schema-aware extraction increased Item 4
coverage from 125 to 139 filings, or 86.88%, but remained below the unchanged 90% gate. The same
ambiguous two-primary-document accession remained a failure, as required. The classifier found 25
specific active-intent sections among the 139 extracted sections (17.99%); every positive retained
its source sentence and the class-balance gate passed. The frozen manual audit was not used to
rescue failed machine gates.

No parser v3 is opened from these misses. Further work requires an independently labelled
document-extraction program or a licensed point-in-time ownership/activism source. Zero prices,
returns, or return identities were spent.

Machine-readable v2 result:
`artifacts/feasibility/active_ownership_13d_item4_v2/result.json`.
