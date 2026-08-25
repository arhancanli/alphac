# ALPHAC external review acquisition plan

**Owner and author:** Arhan Canli  
**Status:** preparation only; zero reviewers contacted, assigned, or completed  
**Applies to:** the five flagship manuscripts named in `config/external_review_protocol.json`

## Objective

Obtain criticism that can change the manuscripts and expose errors. The first review wave requires
ten conflict-free domain reviews: one methods review and one data-lineage or reproducibility review
for each flagship paper. A favorable comment, an arXiv endorsement, a repository DOI, or an AI
assessment does not satisfy this objective.

## Review sequence

1. Freeze one manuscript version, PDF, result artifact, trial union, and reproduction archive.
2. Arhan completes the paper-specific technical audit and approves the exact manuscript hash.
3. A fresh-context reader identifies the hypothesis, estimand, information set, decision rule,
   result, limitations, and reproduction command without verbal help.
4. Select two external reviewers through independent channels. One covers statistics,
   econometrics, or quantitative finance. One covers data lineage and reproducibility.
5. Record qualifications, relationships, financial conflicts, compensation, publication consent,
   scope, and tool use before review begins.
6. Send the immutable packet and ask for criticism rather than endorsement. Require numbered
   findings with `BLOCKING`, `MAJOR`, `MINOR`, or `QUESTION` severity.
7. Arhan answers every finding in the governed response matrix. Any new return analysis enters the
   trial ledger before interpretation.
8. Preserve the original review, response, resulting commit, revised manuscript hash, and every
   unresolved objection.
9. Ask a person outside the project to run the released protocol in an environment they control.
   Record commands, dependency state, result hashes, deviations, and the outcome.
10. Publish an immutable preprint only after rights review, clean replay, author approval, and
    explicit authorization. Then request an open review against that exact public version.

## Reviewer eligibility

A reviewer qualifies for one declared scope only when the packet records evidence that a reader
can check. Useful evidence includes relevant publications, graduate research, professional
quantitative work, research-software maintenance, data engineering, or reproducibility audits.
Prestige alone is not a qualification.

The following conditions block assignment:

- a financial stake in a reported strategy or approval-contingent compensation
- a close personal, supervisory, business, or recent coauthor relationship that is not disclosed
- inability to assess the assigned scope
- refusal to preserve the manuscript version and finding record
- use of an AI agent as the purported independent reviewer

A reviewer may be paid a fixed amount for time. The amount and terms remain part of the review
receipt whether the review is favorable or adverse.

## Sourcing channels

Use several channels so one social circle does not control the result:

- authors of directly cited econometrics, backtest-overfitting, or portfolio-evaluation work
- doctoral researchers and research staff in statistics, econometrics, financial engineering, or
  computer science
- quantitative developers with public evidence of research implementation
- research-software maintainers and reproducibility communities
- journal or conference reviewers assigned through a formal editorial process

Contact must be individual and limited. Do not send bulk endorsement requests or imply an
affiliation with a reviewer's institution. Reviewer candidates require a paper-specific conflict
screen before contact.

## Review routes and claim boundaries

| Route | Role | What it establishes | What it does not establish |
|---|---|---|---|
| Direct commissioned review | Private or publishable technical criticism | A named review after the receipt is complete | Peer review, acceptance, or replication |
| Zenodo | Immutable paper or reproduction archive with a DOI | Preservation, citation identity, and versioning | Editorial screening or peer review |
| arXiv | Moderated disciplinary preprint | Public scientific manuscript after acceptance by moderation | Correctness or peer review; endorsement is not review |
| PREreview | Public review request tied to a supported preprint | Open comments and responses after they exist | Guaranteed review or journal acceptance |
| Peer Community in Registered Reports | Candidate Stage 1 and Stage 2 route for future trials, subject to scope confirmation | Prospective review only if the trial and venue accept it before outcomes are known | Eligibility or retrospective validation of completed sleeve searches |
| Journal of Open Source Software | Public editorial review of research software | Formal software review after its screening gates are met | Review of new strategy performance results |
| OpenReview | Infrastructure used by a specific venue | The status granted by that venue | A general self-submission or review service |

Current official guidance says that PREreview requests use a supported public preprint identifier.
arXiv accepts topical, refereeable scientific contributions and may require endorsement, but its
official guidance states that endorsement is not peer review. Journal of Open Source Software
currently requires a feature-complete open-source release, tests, documentation, demonstrated
research use, and more than six months of genuine public development history. Those requirements
must be checked again immediately before any external action.

- PREreview request workflow: <https://prereview.org/how-to-use>
- arXiv submission guidance: <https://info.arxiv.org/help/submit/index.html>
- arXiv endorsement boundary: <https://info.arxiv.org/help/endorsement.html>
- Zenodo record model: <https://help.zenodo.org/docs/deposit/about-records/>
- Journal of Open Source Software submission requirements:
  <https://joss.readthedocs.io/en/latest/submitting.html>
- Peer Community in Registered Reports: <https://rr.peercommunityin.org/about/about>
- OpenReview documentation: <https://docs.openreview.net/>

## Manuscript and authorship standard

The paper must sound like its research record because its reasoning comes from that record. Each
paper states the mechanism, information set, estimand, search breadth, decision rule, negative
evidence, implementation choices, and evidence that could reverse the conclusion. It does not use
promotional adjectives, fictitious collective voice, canned transitions, or manufactured stylistic
variation.

Arhan must be able to defend every retained claim and must write the five research-account answers
in `docs/design/AUTHOR_TECHNICAL_AUDIT_TEMPLATE.md`. Venue-specific AI assistance disclosure is
mandatory when required. AI-detector optimization is prohibited: detector scores neither prove
authorship nor measure scientific quality.

## Current state

The local repository contains five hash-bound flagship commissioning packets with ten blank review
roles. It also contains sixteen blank author technical-audit worksheets. No reviewer has been
contacted, assigned, or completed; no independent reproduction has occurred; no preprint review or
formal peer review is claimed. External outreach, account creation, DOI reservation, and submission
remain unauthorized.
