# Terminal ledger implementation

Added opt-in TerminalEvent and TerminalLedger. Every event requires a positive finite price, finite nonnegative fee, exact timestamp, instrument identity and hash-bound source file. The basis is reported or modeled; modeled events require explicit caller opt-in. Reported is a source classification, not an automated authenticity certificate. Source hashes are checked again before settlement. Historical information availability remains a separate runner contract.

The remaining signed position closes through ordinary ledger accounting at the explicit settlement price, preserving realized gains/losses and fees. The audit identifies the closure as administrative settlement, not a liquidity-backed market fill. Repeated settlement is idempotent; later fills and backdated reopening fail. Marks, funding and other cash operations cannot pass an unprocessed boundary. Financing intervals cannot cross already processed terminal cash changes. Multiple terminal events must be processed chronologically.

Eleven focused tests pass: long-loss and short-profit arithmetic, fee deduction, idempotency, source tampering before mutation, explicit modeled opt-in, flat contract closure, invalid prices, later/backdated fill rejection, skipped boundaries, funding ordering and multiple-event ordering. Ruff passes. Tests use synthetic sources only and do not certify actual LUNA settlement.

## Integration boundary

This component is not yet connected to the historical engine. The runner must split its clock at15:30UTC, handle the partial15:00hour and funding/cash ordering, and bind an explicit reported or modeled settlement assumption before measuring returns. The generic ledger supports positive settlement prices only; zero-value settlement requires a separately tested accounting path. No hidden last-close default, production change, original result correction or new trial identity. Union273; goalactive.

Next: implement the bounded crypto replay adapter and its event-clock tests. Freeze all settlement scenarios and cost assumptions before full historical returns; retain source uncertainty and do not label modeled reconstruction exact execution evidence.
