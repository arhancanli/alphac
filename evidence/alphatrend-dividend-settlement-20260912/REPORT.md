# Dividend settlement boundary for the proposed raw-price candidate

The existing engine already applies source-bound splits and signed dividends
before ex-date fills, checks event availability, converts queued split quantities
and rejects ambiguous simultaneous split/dividend events. Its Ledger credits
cash at ex-date because the lake lacks payment dates. Although documented as
receivable/payable accounting, that value shares the engine's cash balance. This
is not a distinct settled-cash model and must not be described as one.

Added an isolated Decimal simulation book. It records signed dividend entitlements
from the pre-ex quantity, retains receivables/payables until a supplied payment
timestamp, and moves the amount into settled cash only when payment is due. Long,
short and zero-holding cases preserve cash-plus-receivable wealth exactly. Identical
event retries and repeated settlements do not double count; conflicting retries,
late events, invalid dates and backwards chronology are rejected.

This component is not connected to the engine or broker. Actual paper payments
still require broker reconciliation. The simulation does not guess payment dates,
withholding, broker lending adjustments or fractional-share cash-in-lieu. Missing
payment-date inputs remain a barrier to integration. Current captured Polygon
pay dates are available as reference fields; receipt time cannot be replaced by a
historical declaration date to satisfy timing gates.

Validation: 93 tests passed across the new work chain, including eight settlement
cases. Ten existing corporate-action contract/boundary tests also pass. Their first
run had nine passes and one missing-artifact failure: this worktree lacked
artifacts/engineering/corporate_action_contract.json. The unchanged exporter
regenerated that local capability artifact; the completed rerun passed all ten.
Both test logs are retained. No frozen engine/ledger source was changed.

Next engineering work: integrate receivable valuation separately from cash used
for funding/order constraints, with explicit historical payment-date coverage and
end-to-end ex-entry/pay-date cases. Keep the frozen engine reproducible. The
SFP target ETF price-access issue and archive action semantics remain unresolved.
No new strategy-return measurement or hypothesis; union remains 238.
