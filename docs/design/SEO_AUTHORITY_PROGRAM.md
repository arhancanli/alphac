# Canli Capital search authority program

Status: active  
Owner and author: Arhan Canli  
Canonical domain: <https://canlicapital.com/>  
Baseline date: 2026-08-24

## Objective and boundary

Make Canli Capital the most useful and verifiable result for the narrow subjects the project can
credibly own: open quantitative research governance, point-in-time backtesting, deflated-Sharpe
implementation, trial accounting, execution realism and independently checkable paper records.

“Dominance” does not mean manufacturing pages, links, credentials or certainty. Search placement
cannot be guaranteed. The program earns authority through original evidence, stable citations,
clear authorship and technically sound discovery. Incomplete trial stubs are not indexable papers;
publishing 174 thin pages would dilute the corpus rather than strengthen it.

## Live baseline

The content-hashed read-only audit on 2026-08-24 checked `robots.txt`, `sitemap.xml` and every live
sitemap URL directly:

- `robots.txt` returns HTTP 200, allows the root and declares the canonical sitemap;
- the live sitemap contains 424 unique, on-origin URLs;
- all 424 return HTTP 200 without a redirect, self-canonicalize, carry a unique title and
  description, render one H1 and parse their JSON-LD without error;
- 226 incomplete trial-detail pages are nevertheless in the live sitemap and indexable;
- 1,369 canonical-corpus navigation links point to raw Markdown instead of the HTML papers;
- all 102 unique raw Markdown targets checked return without `X-Robots-Tag: noindex`;
- branded and `site:canlicapital.com` searches again returned no Canli Capital result; and
- no Google Search Console coverage measurement is available in the repository.

The first three bullets show that this is not a basic robots, HTTP, metadata or canonical failure.
The next three identify controllable authority dilution. The corrected local candidate preserves
all 460 public HTML records while limiting the sitemap to 234 indexable canonical URLs, keeping the
226 incomplete trial records public under `noindex, follow`, canonicalizing corpus navigation, and
configuring `X-Robots-Tag: noindex` for raw evidence files. That candidate has not been deployed, so
none of those repairs is claimed live.

Firecrawl was not used for this observation because the connected account had insufficient
credits. No Firecrawl result is inferred. The durable direct-HTTP artifact is
`meridian/artifacts/seo/live_technical_audit.json`.

Google explicitly states that a sitemap is a discovery hint, not a guarantee of indexing or
ranking, and that Search Console ownership is required for URL inspection and recrawl requests.

Primary references:

- [Google: build and submit a sitemap](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap)
- [Google: ask for recrawling](https://developers.google.com/search/docs/crawling-indexing/ask-google-to-recrawl)
- [Google: crawling and indexing FAQ](https://developers.google.com/search/help/crawling-index-faq)
- [Google: ProfilePage structured data](https://developers.google.com/search/docs/appearance/structured-data/profile-page)

## Workstreams

### 1. Search Console and index coverage

This is the only blocking credential step.

1. Verify both the domain property and the canonical HTTPS URL-prefix property in Google Search
   Console. Add the supplied verification record without placing account credentials in git.
2. Submit `https://canlicapital.com/sitemap.xml` in Search Console.
3. Inspect and request indexing for `/`, `/research`, `/founder`, `/performance`, `/methodology`,
   `/verify` and `/measurements/program-status` first.
4. Record weekly: discovered URLs, crawled URLs, indexed URLs, exclusions by reason, impressions,
   clicks, branded queries and non-branded queries.
5. Treat “crawled, currently not indexed” as a content-quality signal. Do not respond by creating
   more near-duplicate pages.

Acceptance: Search Console is verified, the sitemap is processed without error, the seven priority
URLs are indexed or carry a diagnosed exclusion, and weekly measurements are archived.

### 2. Research assets that deserve citations

The authority engine is the research itself.

- Publish a complete packet only when it is bound to one hypothesis key and passes every section
  in `trial_packet_manifest.json`.
- Consolidate related parameter trials into a substantial family paper with identity-specific
  appendices. Every identity remains addressable without creating thin standalone pages.
- Give publication-grade papers a version, abstract, author, references, data/code availability,
  limitations, machine-readable citation and stable URL.
- Create tagged GitHub releases and archive major papers/code snapshots with a DOI provider such
  as Zenodo when the release is ready. Do not claim peer review unless it occurred.
- Submit genuinely novel methodological papers to appropriate repositories or journals; publish
  nulls and corrections under the same standard.

Priority family papers by uncovered identity count:

1. equity momentum and AlphaMax construction/weighting;
2. managed-futures trend;
3. crypto funding carry;
4. time-series momentum and cross-sectional momentum variants;
5. macro-vintage and equity fundamental families.

Acceptance: every union identity is covered by a verified family paper plus an exact identity
appendix, and the manifest reports complete packets equal to distinct identities.

### 3. Topic ownership

Build around questions a researcher actually asks, not generic “best quant fund” terms:

- how to count quantitative research trials;
- deflated Sharpe ratio implementation and failure modes;
- point-in-time backtest architecture;
- paper-trading broker reconciliation;
- execution-realistic backtesting;
- survivorship-bias and filing-vintage controls;
- correlation-gated sleeve admission;
- publishing killed quantitative strategies; and
- tamper-evident investment track records.

Each topic hub should link to one definitive methodological guide, original measurements, relevant
papers, code and the claim boundary. Existing topic hubs remain the navigation layer; new pages
must add a distinct answer rather than split one answer across keyword variants.

Acceptance: each target topic has one canonical hub, at least one original measurement, at least
one substantial paper and no competing internal page aimed at the same intent.

### 4. Earned authority and author identity

- Keep Arhan Canli as the consistent author entity across the site, repository, citation file and
  archived releases.
- Link the founder page from every paper through the same Person identifier.
- Add only real external profiles controlled by Arhan to `sameAs`; never invent credentials,
  affiliations, degrees or employment.
- Seek citations through useful releases: reproducible notebooks, datasets that may legally be
  redistributed, benchmark results, conference talks, technical write-ups and direct outreach to
  researchers whose work is replicated or challenged.
- Maintain a public corrections policy. Corrections strengthen the entity only when the original
  and revision remain inspectable.

Acceptance: the author graph is consistent, major releases have stable citations, and referring
domains grow from relevant technical/research sources rather than purchased or reciprocal links.

### 5. Technical quality and monitoring

- Keep the existing build-time checks for metadata, canonicals, structured data, sitemap coverage,
  internal depth and number provenance.
- Add live checks for HTTP status, canonical agreement, robots, sitemap freshness, program-status
  freshness and the trial-packet manifest.
- Track Core Web Vitals on the live domain and fix measured regressions, not hypothetical scores.
- Submit IndexNow only after a successful deployment; the script already validates the live key
  and live sitemap before sending.
- Keep raw JSON downloadable but do not index it as a substitute for explanatory HTML.

Acceptance: every deployment passes local publication audits, priority live URLs return 200, no
indexable page is orphaned, status artifacts are current, and measured Core Web Vitals meet the
project’s declared thresholds.

## Scorecard

| Metric | Baseline | Near-term target |
|---|---:|---:|
| Live sitemap URLs | 424 | Quality-controlled, not volume-targeted |
| Local candidate indexable URLs | 234 | Deploy only after the full publication gate passes |
| Public incomplete trial records | 226 indexable live | 226 public and `noindex, follow` |
| Static audit errors/warnings | 0 / 0 | 0 / 0 |
| Search-visible branded results | 0 observed | Homepage, founder and research hub indexed |
| Complete evidenced trial packets | 2 / 228 | Backfill only from preserved evidence; never invent history |
| IndexNow submission | 137 accepted on 2026-08-22 | Submit only after a material successful deploy |
| Google Search Console | Not verified in repository | Verified and measured weekly |

The weekly report must publish failures as measured. An unindexed page, rejected paper, weak
result or lost ranking is evidence for the next decision, not a reason to rewrite the baseline.
