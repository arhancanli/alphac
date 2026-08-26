# From Backtest to Public Record

Version 0.1.0 is an author-review draft of a cross-sleeve methodology paper for possible arXiv submission.

The paper's contribution is a fail-closed evidence architecture for prospective validation of systematic trading systems. ALPHAC is the case study. The manuscript intentionally reports the unfavorable and immature state at the dated snapshot rather than presenting the project as a completed performance result.

## Contents

- `source/paper.tex`: arXiv-oriented LaTeX source.
- `source/references.bib`: bibliography.
- `source/case_study_equity.csv`: complete normalized composite used in the paper figure.
- `case_study_snapshot.json`: aggregate case-study values and source hashes.
- `submission_metadata.json`: draft arXiv metadata and unresolved author decisions.
- `AUTHOR_APPROVAL_REQUIRED.md`: mandatory human approval boundary.
- `paper.pdf`: locally compiled 14-page author-review artifact.
- `arxiv-upload-v0.1.0.zip`: minimal TeX upload package with the snapshot under `anc/`.
- `build_report.json`: compile, PDF, visual-inspection, and archival-hygiene receipt.
- `SHA256SUMS`: checksum inventory for the complete draft bundle.

The source package compiles without credentials, private files, shell escape, or repository-relative dependencies. The local PDF passed machine checks and internal visual inspection of all 14 pages. That is preflight evidence, not author approval or independent review.

No arXiv upload or external submission is authorized by the existence of this directory.
