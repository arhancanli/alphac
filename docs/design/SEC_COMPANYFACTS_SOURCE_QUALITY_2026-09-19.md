# SEC Company Facts source-quality correction

The existing selected research cohort records 520 successful cached responses and
80 terminal 404s. A later website audit found that 146 of those cached responses
lack a usable entity identity/name. Parser v3 could label JSON parsing as a successful
fetch without checking these fields. The original receipts describe that historical
process and must remain unchanged.

Parser v4 validates the requested integer CIK, nonempty entity name and fact-container
shapes before extracting rows. It records invalid_payload with raw-byte hashes and
cache provenance, keeps corrupt cache bytes rather than deleting/refetching them,
and excludes invalid or missing statuses from completion. Prior-parser success does
not count as current validation. Valid entities without relevant accounting concepts
can still be successfully retrieved; that does not establish usable financial coverage.

New downloads receive an atomic capture receipt binding URL, CIK, source-byte hash
and a recorded UTC retrieval time. Cached sources use a receipt only if it matches
the exact bytes and entity. Legacy caches retain an unknown capture time. This local
receipt is acquisition metadata, not an independently trusted timestamp or proof of
research validity.

Use a separate raw/output/result directory for deliberate refreshed collection.
Do not overwrite or backdate the old study's raw sources, parts or receipts. Source
validation does not replace accounting-semantic audits, point-in-time reconstruction,
return validation, or research admission. No strategy outcome changes here.

Validation: 24 collector and downstream-audit tests; Ruff. Read-only validation of
all 520 existing cached files initially found 146 invalid payloads and 374 valid
retrievals, matching the website identity exclusions; original bytes remained unchanged.
The final code is rechecked against that cohort in the CanliCapital goal evidence.
No network collection, original-receipt rewrite or production deployment was run.
