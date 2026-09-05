# ALPHAC external review response matrix template

**Owner and author:** Arhan Canli  
**Status:** blank local template; no review or response is claimed

## Immutable review identity

- **Manuscript title:** `[exact title]`
- **Manuscript version:** `[semantic version]`
- **Manuscript SHA-256:** `[64-character hash]`
- **Review SHA-256 or venue identifier:** `[hash or protected identifier]`
- **Reviewer identity or venue-protected identifier:** `[identity]`
- **Review scope:** `[one or more protocol scopes]`
- **Review date:** `[ISO 8601 date]`
- **Response version:** `[semantic version]`
- **Resulting manuscript SHA-256:** `[64-character hash after revision]`

## Independence statement

Record the reviewer's qualifications, relationships, financial conflicts, compensation, permission
to publish their identity and comments, and any automated tools used during review. A blank field
is unresolved, not equivalent to `none`.

## Finding-level responses

Create one row per numbered reviewer finding. Preserve the reviewer's original severity and a
short faithful summary. Do not merge distinct objections merely because one revision addresses
several of them.

| Finding | Severity | Review scope | Reviewer finding | Author response | Disposition | Evidence or change | Remaining objection |
|---|---|---|---|---|---|---|---|
| R1 | `BLOCKING` | `[scope]` | `[faithful summary]` | `[specific response]` | `[ACCEPTED / PARTIALLY_ACCEPTED / REJECTED_WITH_REASON / OPEN]` | `[commit, section, artifact, or analysis]` | `[none or exact unresolved issue]` |

## Response rules

`ACCEPTED` means the manuscript or evidence was changed as requested and the exact change is
identified. `PARTIALLY_ACCEPTED` states which part changed and which part did not. A
`REJECTED_WITH_REASON` response engages the technical objection and cites evidence; disagreement
alone is not a reason. `OPEN` remains a release blocker when the finding is `BLOCKING`.

New return analysis performed in response to review must follow trial-accounting rules. It may
require a new hypothesis identity and cannot be described as an uncharged robustness check. A
revision never alters the immutable result artifact or the original review.

## Resolution summary

- **Blocking findings:** `[count]`
- **Blocking findings still open:** `[count]`
- **Major findings:** `[count]`
- **Major findings still open:** `[count]`
- **New return identities charged:** `[count and keys]`
- **Claims weakened or removed:** `[list]`
- **Independent replication attempted:** `[yes/no]`
- **Independent replication completed:** `[yes/no, with separate receipt]`
- **Author approval:** `[Arhan Canli signature or governed approval reference]`

## Claim boundary

Completing this matrix records an author response to one identified review. It does not establish
that the reviewer accepted the response, that independent replication succeeded, or that a venue
accepted or published the manuscript. Those states require separate external evidence.
