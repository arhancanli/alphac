# Retained crypto cash residual trace

Traced **1,029 retained local snapshots**, from June 29, 2026 at 07:00 UTC through September 13 at 04:00 UTC. Initial capital is unchanged, and previously retained fills are neither removed nor changed across adjacent snapshots. These checks do not establish uninterrupted observation coverage.

The first material residual change (>0.01 quote units) occurs at the **August 12, 21:00 UTC cycle label**, adding 23.47889017589 quote units. All **188 material changes** occur at labels 01:00, 05:00, 09:00, 13:00, 17:00 or 21:00 UTC. The final residual is **+935.608931006426 quote units**. The full trace retains small changes and intervals without changes; none were selectively dropped from reconciliation.

This recurring pattern is consistent with funding processing, but is not payment-level attribution. Cycle labels are not authenticated payment timestamps, and snapshots can span missing intervals. Initial-capital and fill continuity excludes those two specific explanations for the observed residual; it does not exclude corrections or other unrecorded cash mutations.

A targeted `rg` search for `funding_settled`, `funding settled` and `funding_settle` in local `var/log` files named with crypto/alphaforge returned no matches. This does not establish absence from remote, rotated-away or differently named logs. Git history first includes `apply_funding` in the August 18 checkpoint commit `c0eecea`; that commit time is not proof of the deployment date or the origin of the August 12 change. No remote queries or unverified historical payment reconstruction were attempted.

The [prospective ledger specification](PAYMENT_LEDGER_SPEC.md) requires durable event identities, source and price references, explicit currency, signed amounts, atomic payment/cash application and replay conflict handling. It also separates query coverage from settlement completeness. No ledger installation or backfill occurred.

Validation: 13 focused tests passed (three new trace tests plus ten accounting tests), Ruff clean. Retained snapshot hashes and cash residuals are independently cross-checked against the existing accounting evaluator; the complete delta sum reconciles the terminal residual. Compressed original snapshot rows, per-snapshot trace, source snapshots and a manifest are saved here. Decimal conversion of stored JSON provides diagnostic precision, not original source precision.

Phase complete. Production, baseline returns and clock settings are unchanged. No new strategy trial, epoch or admission. The residual is localized but remains unattributed at payment level. Next proposed phase: implement the prospective event ledger in isolation and test atomic cash application and crash recovery. The combined performance and sleeve-count targets remain unestablished.
