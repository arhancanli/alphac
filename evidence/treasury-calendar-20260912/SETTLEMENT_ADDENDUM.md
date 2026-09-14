# Addendum to the proposed phase-held Treasury specification

The regular-settlement paragraph in treasury-trade-spec-20260912/TRADE_SPEC.md is superseded for future implementation design by this requirement:

Determine settlement from source-bound instrument/venue conventions, the Fedwire Securities operating calendar, and the applicable market-good settlement calendar. Count only jointly eligible dates using the documented lag for that trade and instrument. An observed Fedwire opening does not establish secondary-market settlement eligibility. Money-market bill conventions require their own verification and must not inherit a note-specific exception automatically.

No missing day may default to open or to closed. The new regular_settlement_date helper enforces supplied calendar states and lag, but does not certify the calendars' provenance or completeness. WI and reopening-tranche dates still require their original/tranche lineage and route validation.

The 15 flagged trading boundaries remain unresolved. No historical date, sign, holding horizon or event membership has changed. The prior next-Fedwire-session helper remains a preserved artifact and is not production-ready for this study. All return gates remain closed.
