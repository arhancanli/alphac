# ALPHAC external reviewer brief template

**Owner and author:** Arhan Canli  
**Status:** local template; no reviewer contact or review is claimed

## Purpose of the request

Use this brief to request a bounded technical review of one immutable manuscript and its evidence
bundle. The request asks for criticism, not endorsement. It must not imply that the reviewer,
their employer or their institution supports Canli Capital, AlphaC Algorithms or an investment
claim.

## Manuscript identity

- **Title:** `[exact manuscript title]`
- **Author:** Arhan Canli
- **Version:** `[semantic version]`
- **Manuscript SHA-256:** `[64-character hash]`
- **Canonical preprint DOI or URL:** `[identifier after it exists]`
- **Reproduction bundle DOI or URL:** `[distinct identifier after it exists]`
- **Capital boundary:** `[research simulation, Alpaca paper, or funded capital]`
- **Review status at request time:** `[not peer reviewed or exact evidenced status]`

## Requested review scope

Select one or more scopes before contacting the reviewer:

- `STATISTICS_AND_ECONOMETRICS`: estimand, dependence, uncertainty, multiplicity, selection and
  decision-rule validity
- `QUANTITATIVE_FINANCE`: economic mechanism, portfolio construction, benchmarks, exposure overlap
  and interpretation
- `DATA_AND_POINT_IN_TIME_INTEGRITY`: source lineage, vintages, universes, corporate actions,
  leakage and survivorship controls
- `EXECUTION_AND_RISK`: costs, financing, borrow, market impact, capacity, drawdown and operational
  assumptions
- `REPRODUCIBILITY`: environment, commands, permitted inputs, output hashes and deviation handling
- `MANUSCRIPT`: structure, definitions, tables, citations, claim boundaries and readability

## Questions for the reviewer

1. What is the strongest reason the central conclusion could be wrong?
2. Does the information set contain any plausible look-ahead, survivorship or revision leakage?
3. Does the trial accounting cover every inspected return identity that should affect inference?
4. Are the estimator, uncertainty measure and decision threshold appropriate for the stated
   decision?
5. Do costs, turnover, financing, borrow and capacity assumptions support the interpretation?
6. Can every result-bearing table and figure be traced to a released artifact?
7. Which claim should be weakened, removed or tested prospectively?
8. Is the manuscript clear enough to reproduce without guidance from the author?

## Independence and disclosure

The reviewer records:

- relevant qualifications
- current or past relationship with Arhan Canli, Canli Capital or AlphaC Algorithms
- financial exposure to the instruments or strategies discussed
- compensation, including an explicit statement when none was paid
- whether their identity may be public
- whether comments may be published verbatim
- any use of automated tools during review

Compensation may pay for time. It must never depend on approval, a favorable conclusion or a
performance result. An AI agent cannot satisfy an external human review or independent replication
requirement.

## Review deliverables

The requested package contains:

1. a marked manuscript or numbered review letter
2. a severity for each finding: `BLOCKING`, `MAJOR`, `MINOR` or `QUESTION`
3. a statement of review scope and conflicts
4. reproduction commands and environment details if execution was attempted
5. observed output hashes and deviations if reproduction was attempted
6. an explicit distinction between editorial review and independent replication

Arhan answers every finding in a public or venue-confidential response matrix. Each response states
`ACCEPTED`, `PARTIALLY_ACCEPTED`, `REJECTED_WITH_REASON` or `OPEN`. The revised manuscript receives
a new version and hash. Earlier versions and unresolved objections remain available.

Use `docs/design/EXTERNAL_REVIEW_RESPONSE_MATRIX_TEMPLATE.md` for the governed response. Filling
the template without an identified review and immutable review evidence advances no review state.

## Claim boundary

Sending this brief proves no review occurred. A completed review requires a receipt that satisfies
`config/external_review_protocol.json`. Journal submission and repository posting remain separate
actions requiring owner authorization.
