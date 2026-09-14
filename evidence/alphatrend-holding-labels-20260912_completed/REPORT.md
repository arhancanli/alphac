# AlphaTrend forward holding-label validation

The synthetic wealth-index open ratio is not the same label as a position bought
at a raw entry open and sold at a raw exit open. Entry-day distributions belong to
the pre-existing holder; a new buyer at that ex-date open has no entitlement.
The wealth index also reinvests distributions at each close, whereas an explicit
cash-accrual holding label retains them as receivables. These conventions must not
be silently interchanged.

Implemented raw-open labels with one initial share, explicit splits and dividend
receivables. Entry actions are excluded; exit actions are included. Dividend cash
is not reinvested. This measures gross economic wealth at exit, including unpaid
receivables; it is not payment-date spendable cash or net broker P&L. Simultaneous
split/dividend share-basis ambiguity fails closed.

Decision t enters at XNYS t+1, exits at t+1+h, and releases at the actual exit
session close. The v2 guard rejects action snapshots first observed after this
fixed release, even when computation occurs later. The frozen v1 accounting
implementation remains for the current-vintage diagnostic; candidate specification
explicitly requires v2. Neither version is integrated into the existing producer.

The fixed 21-session real-data diagnostic produced 119 labels across 17 ETFs.
An independent one-dollar fractional-share and cash book matches all labels with
maximum floating error 2.22e-16. The synthetic-index ratio differs by more than
0.000001 bp for 28 labels, with maximum difference 0.408808 bp. This is label
accounting evidence, not IC, portfolio returns, candidate selection or improvement.
All real-data labels are explicitly current-vintage diagnostics.

78 tests passed across labels, release guard, OHLC/close bridges, capture layers,
producer and journal. Cases include entry/exit entitlement, splits, cash retained
without reinvestment, weekend/holiday indexing, late records, incomplete scope and
exit-close maturity. Ruff checks pass for new label modules/tests and completed
runner. The first harness attempt passed NumPy scalar prices to a native-number
contract; it failed before producing label measurements. Its source/protocol and
failure record are retained in the sibling non-completed directory.

`candidate_specification.json` records the proposed price/label convention and
unchanged controls. It is a DRAFT, not registered or executable. Full raw/action
history, observation provenance, separated feature/label/execution inputs and
frozen comparison criteria must be sealed before registration or strategy returns.
The old candidate is not relabelled. No new hypotheses; union remains 238.
