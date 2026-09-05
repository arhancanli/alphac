# Author review for approval-gated research protocols

**Owner and intended author:** Arhan Canli

**Current state:** two hash-bound blank packets; zero author protocol approvals

## Why this exists

The merger-announcement and Treasury-auction redesigns have passed their no-return structural
tests, but software cannot decide that Arhan understands or approves them. A chat reply also should
not silently authorize the next research stage without binding the exact protocol and evidence
versions being reviewed.

Each tracked packet therefore freezes the protocol SHA-256, evidence-file SHA-256, evidence content
hash, six author questions, six technical checks, the exact approval decision, and the narrow next
stage it would authorize. Every answer and judgment remains blank. The packets are preparation,
not approval.

## Current packets

- `merger-announcement-identity-v2` binds the disjoint no-return confirmation design. Its governed
  approval would authorize only acquisition and freezing of the 2006–2015 SEC confirmation corpus.
- `treasury-auction-state-machine` binds the no-return schedule state machine. Its governed approval
  would authorize only writing a separate return preregistration.

Neither decision authorizes a return run, sleeve admission, external submission, independent-review
claim, or performance claim.

## Workflow

Prepare a private response outside the tracked publication tree:

```text
uv run python scripts/verify_author_protocol_approval.py prepare \
  --review-key merger-announcement-identity-v2 \
  --output var/author_reviews/merger-announcement-identity-v2.json
```

or:

```text
uv run python scripts/verify_author_protocol_approval.py prepare \
  --review-key treasury-auction-state-machine \
  --output var/author_reviews/treasury-auction-state-machine.json
```

Arhan must personally complete every answer, confirm every technical check with evidence, disclose
all AI assistance, review every retained claim, record corrections, and bind the decision to the
current protocol and evidence hashes. He must also change the response status to
`AUTHOR_COMPLETED_RESPONSE`. Automation may explain a prompt but may not write, paraphrase, or
approve Arhan's response.

Verify a completed response without writing a tracked receipt:

```text
uv run python scripts/verify_author_protocol_approval.py verify \
  --input var/author_reviews/merger-announcement-identity-v2.json
```

Only after Arhan explicitly authorizes importing the verified result may an unused output path be
provided. The verifier refuses to overwrite an existing receipt.

```text
uv run python scripts/verify_author_protocol_approval.py verify \
  --input var/author_reviews/merger-announcement-identity-v2.json \
  --output artifacts/governance/author_protocol_approvals/merger-announcement-identity-v2-v1.json
```

## Fail-closed rules

Verification fails when a bound file changes, a question or technical check is absent, evidence is
missing, the AI-assistance declaration is incomplete, the decision differs from the registry, any
blocking issue remains, or the approved hashes do not match the current files.

A passing receipt is still self-attestation. It does not independently prove who typed the answers,
does not count as external review, and does not establish alpha, Sharpe, drawdown, diversification,
or sleeve admission.
