# Point-in-time cash and collateral financing replay

AlphaForge can now accrue explicit cash-credit, margin-debit, and short-collateral rates inside the
event-driven backtester. This is engineering evidence, not historical financing coverage or return
evidence. No market returns were opened and no hypothesis was spent.

## Enforced behavior

- Every schedule carries observed, available, valid-from, and valid-until timestamps.
- An enabled run requires one schedule that covers the complete holding interval. Missing or
  expired coverage halts the run rather than forward-filling a rate.
- Positive unrestricted cash earns the credit rate; negative cash pays the margin-debit rate.
- Positive cash up to current short market value is treated as segregated short-sale collateral and
  receives its own explicit rate rather than the ordinary cash-credit rate.
- ACT/360 and ACT/365 conventions are explicit and persisted.
- Enabled replay requires one ledger currency. Mixed-currency books fail closed until FX cash
  ledgers exist.
- Every interval persists to `financing.parquet`, including its cash bases, rates, convention,
  source label, and signed payment. The net amount is echoed in run metadata.
- With no provider, the previous zero-cash-financing path remains unchanged.

## Deliberate boundary

The platform does not bundle historical broker rate schedules, infer a rate from today’s account,
or claim account-tier coverage. It does not yet model multi-currency cash, security-specific
haircuts, rehypothecation, intraday margin calls, forced liquidation, futures initial or maintenance
margin, options portfolio margin, or live broker statement reconciliation.

This foundation is intentionally separate from security borrow. Borrow fees price the availability
of a borrowed security; financing prices cash and collateral balances. Treating one as the other
would double-count or omit material carrying costs.

The machine-readable contract is available at
[`/glassbox/financing_contract.json`](/glassbox/financing_contract.json).
