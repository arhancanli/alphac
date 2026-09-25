# Trial-reasoning dataset (v0): datasheet

Every governed ALPHAC trial as one record a model can learn from: what was tested, how it was
fixed before any result, what evidence exists and what is missing, and, where a closure is sealed,
the verdict and every gate it failed. Built by `scripts/build_trial_reasoning_dataset.py`; the
counts below are the 2026-09-25 build (`artifacts/datasets/trial_reasoning/v0/manifest.json`,
content hash in the manifest). Rebuild with `--write`; nothing is published by the build.

## Why it exists

Research datasets almost only show what worked. This one is mostly what did not, with the
reasons, from a project that registers every hypothesis before measuring it. That makes it
material for training and evaluating financial reasoning: overfitting, cost realism, capacity,
data rights and pre-registration discipline, on real decisions rather than textbook examples.

## Composition (2026-09-25)

- **349 trials**, one record each (a packet published under both a hash and an alias counts once).
- **121 with a sealed decision**: 120 KILL, 1 INCOMPLETE. **No admitted trial is in the dataset.**
  A model trained on it learns why ideas fail, not what a surviving one looks like.
- **118 carry their own sealed preregistration inline**, used only when the file's bytes still
  match the hash sealed in the closure.
- **123 complete packets**; the other 226 are legacy identities whose packets record missing
  evidence sections explicitly (`missing_sections`). They are kept, not filtered: the gap is data.
- Trial accounts: largest are `managed_futures_trend` (125), `alphamax_equity_momentum` (115),
  `crypto_carry` (26), `crypto_momentum` (18). 25 accounts in all.

## Record fields

`hypothesis_key`, `family_trial_account` (the account the trial is **charged to**, not a
description of the strategy: 38 combined-book trials of equity momentum and crypto carry are
charged to `managed_futures_trend`), `alpha_names`, `label`, `evidence_date`, `packet_status`,
`complete`, `configuration` (as fixed; instruments are named by id), `first_measurement`
(annualized Sharpe, observations, skew, kurtosis where recorded), `evidence_sections` (section →
status), `missing_sections`, `preregistration` (path, sha256, document) or null, `decision`
(closure schema, disposition, admitted, the study's own verdict sentence, checks evaluated, every
failed gate, fields never frozen, headline statistics) or null, `data_sources`, `rights_tier`,
`packet_content_hash`, `content_hash`.

## Rights

No record contains vendor rows. Each carries a `rights_tier` from the sources its trial used: the
account's sleeve in `artifacts/publication/all_sleeve_data_rights_audit.json`, plus every venue its
own instruments name (a trial that traded a Binance perpetual names Binance whatever its account).

| Tier | Records | Meaning |
| --- | ---: | --- |
| `COMMERCIAL_CANDIDATE` | 0 | every source is public government data with documented reuse (SEC, EIA); an owner decision is still required before any sale |
| `FREE_RESULTS_ONLY` | 333 | a source restricts derived publication (Binance, Yahoo, Polygon, Sharadar, Deribit); mirrors what the glass box already publishes; may not be sold or licensed |
| `UNMAPPED` | 16 | the account has no sleeve in the rights audit; excluded from every release |

A sold dataset is therefore not possible today without written consent from those vendors.

## Known limits

- **Outcome imbalance**: every sealed verdict is a failure or incomplete (see Composition).
- **Legacy thinness**: 226 records predate the complete-packet standard and lack sections.
- **Statistics are in-sample research measurements**, not forward results; `first_measurement` is
  the immutable first reading, not a best-of.
- **Not investment advice**, and not evidence that any listed idea would or would not work today.

## Release

The owner decides any external release (for example a public dataset host). Until then the dataset
exists only in the author's workspace.
