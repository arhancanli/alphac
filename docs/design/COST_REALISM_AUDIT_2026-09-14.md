# Cost realism on the paper-live record — audit, 2026-09-14

**Owner goal (2026-09-14):** "not forgetting real-life costs which may occur on it on our paper live."
`config/owner_goals.json` records it as `program.real_life_costs_on_paper_live` with status
`PARTIALLY_MODELLED_AUDIT_REQUIRED`. This is the audit. It reads code, charges nothing, spends no
identity, and establishes no result.

## What the published forward record charges today

| Cost | Research (walk-forward) | Paper-live: crypto sleeve | Paper-live: equity sleeves |
|---|---|---|---|
| Commission | charged (`backtest/fills.py:176`) | charged, taker fee (`execution/paper.py:638`, debited `:724`) | **not charged**: Alpaca paper fills carry `fee_quote=0.0` (`execution/alpaca_broker.py:181`) and `scripts/live_cycle.py` never imports the cost model |
| Bid-ask spread | charged, 2.5 bp crypto / 3.0 bp equity (`costs/model.py:186`) | charged for real: fills walk the live book (`execution/paper.py:236-271`), marks at mid | **not charged locally**; whatever Alpaca's paper matcher gives |
| Market impact | charged, square-root law (`costs/model.py:196-222`) | charged for real (book walk) | **not charged** |
| Latency add-on | charged, flat 2 bp (`costs/model.py:224`) | recorded as an audit row, not charged (`execution/paper.py:663-710`) | not charged |
| Perpetual funding | charged (`backtest/engine.py:1009-1020`) | charged since 2026-08-06 (`live/loop.py:1279`, `:1620-1668`; PIT source `cli/paper_cmds.py:786-863`) | n/a |
| Short borrow | charged, flat 50 bp/yr (`backtest/engine.py:886,963`) | n/a | **not charged**; `scripts/paper_trading_state.py:862,1395` says "we charge at 50bp/yr" but nothing touches `live_curve` |
| Financing / margin interest | implemented (`backtest/engine.py:902-928`, `execution/financing.py`) but **no production caller** | **absent** | **absent** |
| Cash yield on idle capital | absent | absent | absent |
| FX conversion | absent (mixed currency fails closed) | absent | absent |

The published NAV for the equity sleeves is Alpaca's account equity written verbatim
(`scripts/live_cycle.py:929-950`, read by `scripts/paper_trading_state.py:376-405`); the combined
`live_curve` (`scripts/glassbox_export.py:1183-1229`) carries no cost fields.

## The three gaps that matter

1. **Equity paper-live charges zero frictions.** Research charges roughly 6 bp per side plus 50 bp
   a year on shorts; the forward record charges none of it. Every equity mark in the forward record
   is therefore gross of costs a funded book would pay, and the owner's Sharpe target is net.
2. **Financing is implemented and wired nowhere.** Margin debit, cash credit and short-proceeds
   accounting exist in `execution/financing.py` and the backtest engine, with no caller in research
   or live.
3. **Cash yield and FX are unmodelled on both paths.** Idle capital earns nothing in the record;
   a funded book would earn the cash rate, and a mixed-currency book would pay conversion.

## What the fix has to look like (next PR, not this one)

The owner's document says an accounting repair may correct a baseline but must retain the
original and disclose the correction. So:

- **Declare** a cost contract (`config/cost_realism_contract.json`) naming every cost a funded book
  would pay, the model for each, its parameters and source, and where the paper record charges it.
  Every row is either CHARGED_AT_SOURCE (the venue charges it), CHARGED_BY_MODEL (we charge it on
  the published curve) or NOT_CHARGED (with the reason and the date it will be).
- **Charge** the equity sleeves by model on the published curve: commission and spread plus impact
  on each fill through the same `TransactionCostModel` research uses, borrow on short notional
  daily, financing on margin debit, and cash yield on idle cash; keep the broker NAV as the
  original and publish the cost-charged curve beside it. The forward evidence evaluates the
  cost-charged curve from the date the contract takes force, and the change is declared in
  `config/live_change_contract.json` as an accounting change with `contaminates_forward_record`
  stated explicitly, so the epoch rule decides, not the author.
- **Prove** it: a test that the cost-charged curve is never above the broker curve, a reconciliation
  that the per-fill charges sum to the daily gap, a mutation that deletes one charge and is caught,
  and a README row that publishes the cumulative cost drag beside the return.

Nothing in this audit changes a published number. Until the next PR lands, the forward record
should be read as **gross of equity frictions**, and `owner_goals.json` says so.
