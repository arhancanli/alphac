# Acceptance clock semantics

Official source checked September13,2026: https://www.sec.gov/about/webmaster-frequently-asked-questions , sections on EDGAR timestamps and publication lag.

The SEC describes header acceptance time as EST and separates acceptance from website dissemination. Its FAQ says there is no timestamp for when filing content first becomes available on sec.gov, and publication lag is not guaranteed. Therefore neither the header nor the filing index accepted-clock display establishes actual historical public availability.

All395 manifest clock strings match the raw headers. That is a cross-format consistency check, not an independent observation of dissemination. The cited EST wording alone does not settle whether a historical summer wall-clock should use fixed UTC−05:00 or daylight-aware America/New_York. Keep the raw string and this unresolved conversion issue explicit; do not silently label it UTC. No entry timestamp or availability lag was selected here.

Any eventual trading protocol needs a declared timing policy and must not present an assumed lag as measured receipt evidence. The primary anchor acceptance also is not automatically the earliest binding announcement time; the365-day source-resolution search remains separate.
