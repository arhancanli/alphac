# Active ownership escalation — Schedule 13D Item 4 source-schema v3

**Short title:** Active ownership Item 4 v3
**Author:** Arhan Canli
**Declared:** 2026-08-16 after v2 closed `DATA_GATED` and before running v3 aggregate results.
**Stage:** document/classifier feasibility only. Prices, returns, event outcomes, and portfolio data
remain forbidden; zero return identities are spent.

## Why v3 is a source correction, not parser tuning

V2 used the unchanged 160-accession sample and added the SEC structured Schedule 13D schema, but
the implementation required the primary bytes to begin with an XML declaration. Actual EDGAR SGML
wraps structured primary documents inside an outer `<XML>` envelope, so all ten sampled 2025
structured filings bypassed the schema parser. One legacy submission also contained two exact-form
documents; the v1/v2 parser ignored the standard SGML sequence field and therefore could not select
the sequence-1 primary document.

V3 may change only these source mechanics:

1. unwrap one outer EDGAR `<XML>` envelope before parsing the namespaced `edgarSubmission` tree;
2. when multiple exact-form documents exist, retain the unique document whose SGML `<SEQUENCE>` is
   `1`; and
3. retain the v2 structured `item4/transactionPurpose` extraction and legacy heading patterns
   unchanged.

No heading phrase, minimum length, active-intent classifier, ownership regex, sample row, threshold,
or label is changed. The original 160 accessions remain frozen. This protocol does not replace or
erase either failed result.

## Unchanged machine and human gates

- 160/160 submissions succeed;
- at least 98% have one exact primary after the sequence-1 rule;
- at least 90% yield Item 4;
- every positive classification retains a source sentence;
- positive class rate remains between 10% and 90%; and
- the frozen 48-row human audit must eventually achieve at least 95% positive precision, 80% recall,
  and 90% exact ownership agreement.

Machine success with incomplete labels is `HUMAN_AUDIT_REQUIRED`, not a pass to returns. Any machine
failure is `DATA_GATED`. The unchanged sample may be used as a source-schema regression corpus; a
future return protocol still requires a disjoint untouched event holdout.

## Pre-label scoring clarification — 2026-08-22

The original scorer left `ownership_exact_rate` permanently null, making the declared ownership
gate impossible to pass even after all labels were complete. Before any of the 48 human labels was
opened, the scoring contract was therefore completed as follows: the frozen machine percentage
output is the sole candidate when exactly one candidate exists, and `unresolved` otherwise. Exact
agreement requires equality to the human percentage or agreement on `unresolved`; there is no
tolerance, inference, summation, or post-label rule selection. This clarification does not alter the
regex, corpus, thresholds, classifier, or machine results and can make the gate fail.

The blind packet under `artifacts/labeling/active_ownership_13d_item4_v3_blind/` contains all 48
source excerpts, an empty review sheet, a blank independence-attestation template, exact frozen
labeling rules, and a standard-library-only verifier in deterministic shuffled order. The
authoritative packet identity is the self-verifying `content_hash` in `manifest.json`; no copied
hash in this prose may supersede it. Before labeling, the independent reviewer runs
`python3 verify_review.py` and proceeds only on `PACKET_VALID`. After completing copies named
`completed_labels.csv` and `completed_attestation.json`, the reviewer reruns the verifier and
returns exactly those two files only on `REVIEW_RETURN_VALID`.

The governed importer independently verifies the manifest, source lineage, immutable row metadata,
templates, completed files, and independence attestation before it can alter the canonical frozen
labels. The packet and its deterministic handoff archive deliberately exclude machine
classifications, matched sentences, percentage candidates, prices, and returns. Structural
verification cannot itself prove reviewer independence or label correctness; those remain the
reviewer's attested responsibility and the subsequent frozen scoring gate.

## Machine outputs

- `artifacts/feasibility/active_ownership_13d_item4_v3/document_audit.parquet`
- `artifacts/feasibility/active_ownership_13d_item4_v3/frozen_human_labels.csv`
- `artifacts/feasibility/active_ownership_13d_item4_v3/result.json`

## Claim boundary

V3 can establish document extraction feasibility only. It cannot establish classification accuracy
until frozen labels are complete, and it cannot establish returns, Sharpe, drawdown, correlation,
capacity, or sleeve admission.
