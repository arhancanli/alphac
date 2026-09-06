# Author technical approval protocol

**Owner and intended author:** Arhan Canli

**Current state:** verifier available; zero completed author approvals

## Why this exists

The publication tree contains one immutable blank technical-audit worksheet for each of the 16
registered manuscripts. A blank worksheet is useful only if a completed response can be bound to
the exact worksheet, manuscript, PDF, bundle manifest, and evidence files it reviews. Editing the
generated worksheet in place is unsafe because the next deterministic rebuild replaces it.

This protocol therefore uses a separate response overlay. The engine may prepare the overlay and
verify its structure. It may not write Arhan's answers, decide that a claim matches, approve an AI
disclosure, or invoke the final import without Arhan's explicit authorization.

## Workflow

Prepare one response outside the tracked publication tree:

```text
uv run python scripts/verify_author_technical_approval.py prepare \
  --registry-key alphavintage_macro_surprise \
  --output var/author_reviews/alphavintage.json
```

Arhan then completes every field in that response himself. The response requires:

- five manuscript-specific research-account answers;
- one trace row for every result-bearing claim, table, and figure;
- the current SHA-256 of every cited evidence file;
- all 11 research-integrity checks with evidence;
- an explicit AI-assistance declaration and venue disclosure text;
- an approval decision bound to the current manuscript and PDF hashes; and
- a reference to the exact user action that authorized import.

Verify without writing a public receipt:

```text
uv run python scripts/verify_author_technical_approval.py verify \
  --input var/author_reviews/alphavintage.json
```

After Arhan explicitly authorizes publication of that approval receipt, pass an unused output
path. The verifier refuses to overwrite an existing receipt.

```text
uv run python scripts/verify_author_technical_approval.py verify \
  --input var/author_reviews/alphavintage.json \
  --output artifacts/publication/author_technical_approvals/alphavintage-v1.json
```

## Fail-closed rules

Approval fails if any bound file changed, any question is missing, any integrity check lacks
evidence, any result claim lacks a source hash, any value is marked mismatched, or the AI-use
declaration is incomplete. A response cannot approve a different manuscript version by changing
its own hashes; the verifier re-derives the authoritative hashes from the repository.

The resulting receipt records a self-attestation. It does not independently prove that Arhan typed
the answers, does not constitute external review, and does not authorize a repository submission.
The author must still personally review the receipt and perform or explicitly authorize each
venue-specific account action.
