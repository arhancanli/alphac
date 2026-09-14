# Timing and lifecycle evidence audit — 11 September 2026

The source audit found a material timestamp hazard and corroborated four contract
expiration dates. It did not establish historical first-publication timestamps
or certify strategy contract eligibility. No returns or new market-data purchases.

## Archive timestamps cannot become trading timestamps

The four archived release pages for July/August 2018 and July/August 2025 each
contain an HTML datetime of 12:00 UTC. On these dates that is 08:00 New York,
four hours before the noon Eastern scheduled reference. The visible page labels
show dates only. Treating these fields as first-publication times would introduce
an unsupported early signal. We retain them as archive metadata, with verified
availability explicitly null. [Example: August 2025 release page](https://esmis.nal.usda.gov/publication/world-agricultural-supply-and-demand-estimates/2025-08-12).

The PDFs' creation timestamps range from 10:23 to 11:20 Eastern on their report
dates. Creation is not public dissemination. HTTP Last-Modified is also unsuitable:
the two 2018 files report September modification dates, July 2025 reports July 14,
and August 2025 reports 13:01:04 Eastern. These observations do not establish that
reports were unavailable earlier, nor do they prove which bytes were available
at the strategy's proposed 12:05 decision.

An official USDA communications bulletin bears a send time of 14:22 Eastern on
August 12, 2025 and links the report. It corroborates a later announcement, not
noon availability or the historical bytes of the separate TXT format used by our
extractor. Moving the trading clock to this bulletin would change the hypothesis
and must not be silently adopted. [USDA bulletin](https://content.govdelivery.com/accounts/USDAOC/bulletins/3ed883b).

## Dated delivery notices corroborate expiration, with limits

| Diagnostic contracts | First intent date in notice | Last trade date | Notice date |
|---|---|---|---|
| ZCZ8, ZWZ8 | 2018-11-29 | 2018-12-14 | 2018-11-20 |
| ZSX8 | 2018-10-30 | 2018-11-14 | 2018-10-19 |
| ZSX5 | 2025-10-30 | 2025-11-14 | 2025-10-17 |

Sources: CME [18-462](https://www.cmegroup.com/notices/clearing/2018/11/Chadv18-462.pdf),
[18-053](https://www.cmegroup.com/notices/clearing/2018/10/Chadv18-053.pdf),
[25-328](https://www.cmegroup.com/content/dam/cmegroup/notices/clearing/2025/10/chadv25-328.pdf).
All four last-trade dates agree with instrument definitions received before the
August diagnostic decisions. The CBOT tables identify first intent; do not copy
first-notice dates from the metals tables elsewhere in these documents.

All three notices postdate the August decisions. They are retrospective checks,
not proof of rules or calendar availability at those decisions. First-notice
values remain null. The December 2025 memo landing page was located, but its
underlying grain table was not recovered in this pass; ZCZ5 and ZWZ5 remain
uncorroborated by a reviewed delivery notice. No nearest-contract or 20-session
eligibility claim is made.

## Reproducible evidence and remaining work

`evidence/wasde-timing-lifecycle/receipt.json` freezes nine retrieved sources:
four PDFs, four release pages and one bulletin. All nine hashes verify.
Three direct CME PDF downloads failed; their facts were reviewed through the
web tool, and this access limitation is retained instead of claiming local PDFs.
`audit.json` records each timestamp discrepancy and expiration comparison.
Both collector and auditor pass Ruff; the auditor ran against the actual files.
The collector refuses to overwrite its evidence directory.

To unlock the original historical hypothesis, obtain timestamped dissemination
records tied to report content, plus pre-decision lifecycle rules/calendars.
Otherwise retain this candidate as data-gated. A prospectively captured report
receipt can establish future observation times, but cannot repair historical
availability. Schedule-assumed exploratory returns would require separate trial
accounting and could not qualify the sleeve under the current specification.

## Follow-up source search and queue decision

USDA's [2018 equal-access announcement](https://content.govdelivery.com/accounts/USDAOC/bulletins/1fda258)
states that from August 1, 2018 the public and media would receive NASS/WAOB
reports at noon Eastern. This strengthens the policy basis for the scheduled
reference, but does not authenticate the historical bytes and capture time of
each archived format. A copy is preserved under `evidence/share-class-rights/`
with its source receipt from this follow-up batch.

The former Cornell release API was located in documentation, but the tested
historical endpoint did not return usable evidence through the web tool. The
additional CME search did not close the pre-decision lifecycle requirement.
Keep this candidate data-gated until a new dissemination/calendar source is
available. Research has advanced to the two share-class legal cases in
`SHARE_CLASS_FEASIBILITY.md`; no schedule-assumed return trial was substituted.
