# Customer–supplier propagation — source and identity review

**Reviewed:** 2026-08-16. **Research stage:** literature and source engineering only. No prices,
returns, signs, thresholds, or portfolio statistics were inspected.

## Economic claim under review

Cohen and Frazzini document delayed incorporation of economically linked firms' news: customer
returns predict subsequent supplier returns when links are defined from suppliers' disclosed major
customers. The investable interpretation is limited attention to indirect cash-flow news, not a
generic momentum strategy. Later evidence is an important adversarial check: shared analyst
coverage can subsume several momentum-spillover effects, so a future implementation must
neutralize direct stock/industry momentum and test whether the relationship survives in a modern,
strictly out-of-sample period.

The candidate here is therefore not “buy suppliers of stocks that went up.” A relationship may
exist only after a supplier filing publicly identifies a material customer. Any future signal must
be tied to a later, timestamped customer event and must be evaluated after neutralizing supplier
momentum, customer momentum, industry momentum, size, beta, and shared-news exposure.

## Disclosure reality

US segment-reporting rules require disclosure when revenue from one customer reaches 10% of total
revenue, including the amount and relevant segment. They do not create a dependable requirement
to publish the customer's legal identity. Filers commonly use labels such as “Customer A,” “one
customer,” or a customer category. Consequently, the existence of a concentration disclosure is
not proof that an executable customer–supplier graph can be reconstructed from public filings.

SEC submissions and filing archives provide immutable accession identity and acceptance timing.
SEC XBRL APIs expose filed financial-statement facts in real time, but issuer-specific extensions
and dimensions do not guarantee a stable, historical customer identifier. Current SEC ticker/name
maps are not a point-in-time alias history and cannot safely resolve old customer names by
themselves.

## Falsification priorities

1. Measure the prevalence of concentration language in the already hash-addressed 10-K corpus.
2. On a deterministic, year-balanced sample, measure whether the disclosure names a customer
   rather than using an anonymous label.
3. Separate textual name extraction from historical issuer resolution; neither implies the other.
4. Fail closed if unresolved aliases, private customers, governments, subsidiaries, or current-map
   survivorship prevent a point-in-time public-company edge.
5. If source feasibility eventually passes, register this as one economic family and count every
   customer-event/sign/horizon variant in the same family-wise trial account.

## Primary sources

- Lauren Cohen and Andrea Frazzini, *Economic Links and Predictable Returns* (original paper):
  https://users.nber.org/~confer/2006/bfs06/frazzini.pdf
- Usman Ali and David Hirshleifer, *Shared Analyst Coverage: Unifying Momentum Spillover Effects*
  (adversarial evidence): https://www.nber.org/papers/w25201
- SEC EDGAR APIs and bulk-data documentation:
  https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- FASB Statement No. 14, major-customer disclosure rule (historical source for the 10% rule):
  https://storage.fasb.org/fas14.pdf

## Claim boundary

This review establishes an economically motivated candidate and a serious source-risk hypothesis.
It makes no claim that the effect persists, that public filings provide a sufficient graph, or that
the candidate has positive net returns, diversification value, capacity, or admission eligibility.
