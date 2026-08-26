# Protocol review: Treasury auction schedule state machine

- **Author and reviewer:** Arhan Canli
- **Status:** awaiting Arhan's review; no approval claimed
- **Protocol SHA-256:** `12b3fa9cfb774bd926945bf39111f9cd3ba50e0c87ba67220f9d8e1423b8563f`
- **Evidence SHA-256:** `bcc88540e06b4de8db142c7a81f6fbf5c43c00fa8b0b575e218e3c7112cd8634`
- **Evidence content hash:** `sha256:46dfc56e7a2bd92cf55cacc1cb69ce4d09d8803a56376ab93faeb0d4b45ebef2`
- **Required decision:** `APPROVED_FOR_SEPARATE_RETURN_PREREGISTRATION`

## What approval would authorize

Write and seal a separate return preregistration before any market data is opened.

It would not prove alpha, admit a sleeve, establish Sharpe or drawdown, constitute independent
review, or authorize any external submission.

## Arhan's technical account

These answers must be written and approved by Arhan. Automation may not invent, paraphrase, or
approve them.

### 1. Describe the event clock and state machine in your own words, including tentative, confirmed, post-only, cancelled, and closed paths.

`[Arhan's answer required]`

### 2. Explain the pre-auction and post-auction position identity and which economic direction is deliberately unchanged.

`[Arhan's answer required]`

### 3. Explain why revised, late, post-event, and missing schedules receive their declared treatment without final-calendar hindsight.

`[Arhan's answer required]`

### 4. Explain how overlapping event windows must be netted for execution while preserving event-level attribution and costs.

`[Arhan's answer required]`

### 5. List the information still prohibited at this stage and the fields that a later return preregistration must freeze.

`[Arhan's answer required]`

### 6. Record every required correction, or explain why the exact bound protocol is acceptable for the next declared stage.

`[Arhan's answer required]`

## Technical checks

- [ ] `ALL_156_EVENTS_HAVE_ONE_DETERMINISTIC_PATH`: Arhan's evidence and confirmation required
- [ ] `REVISIONS_LATE_UPDATES_AND_MISSING_RECORDS_FAIL_CLOSED`: Arhan's evidence and confirmation required
- [ ] `POSITION_SIGN_AND_EVENT_WINDOWS_ARE_NOT_RETUNED`: Arhan's evidence and confirmation required
- [ ] `OVERLAPS_PRESERVE_EVENT_LEVEL_ATTRIBUTION`: Arhan's evidence and confirmation required
- [ ] `MARKET_AND_RETURN_COLUMNS_ARE_ABSENT`: Arhan's evidence and confirmation required
- [ ] `SEPARATE_RETURN_PREREGISTRATION_REMAINS_REQUIRED`: Arhan's evidence and confirmation required

## AI-assistance disclosure

Arhan must identify every system used, describe its scope, approve the public disclosure text, and
confirm that he personally reviewed every retained claim.

## Approval

- **Decision:** `[required exact governed decision / REVISION_REQUIRED / WITHDRAWN]`
- **Blocking issues:** `[required]`
- **Author responsibility statement:** `[required]`
- **Explicit authorization reference:** `[required]`

This blank packet proves no author answer, approval, identity, external review, or authorization.
