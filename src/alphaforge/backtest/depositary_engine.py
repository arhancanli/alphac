# Research fork of payable_engine.py; original preserved. Explicit timely USD terms only.
"""Opt-in chronological daily-equity loop with explicit payable-date cash.

Run/action methods fork the retained loop; shared execution/risk/result helpers
remain inherited. Model session timestamps are still midnight labels, not actual
exchange-open timestamps. Payment timestamps must use this documented time axis.
An explicit retrospective vintage plus complete action schedule opts into current-
vintage research. This schedule is authoritative for that mode; historical PIT
reader cutoffs and publication-time claims are not used for its action replay.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal
from itertools import pairwise

from alphaforge.backtest.engine import (
    _DAY_MS,
    _DIVIDEND_SANITY_MAX_PRE_CLOSE_MULTIPLE,
    _LOG,
    _SPLIT_SANITY_MAX_ABS_LOG,
    COUNTER_NAMES,
    AssetClass,
    BacktestResult,
    BarView,
    CorporateAction,
    CorporateActionType,
    CostInputProvider,
    EventDrivenBacktester,
    Instrument,
    LakeCostInputs,
    Ledger,
    Mapping,
    Ms,
    OrderRequest,
    ParticipationCappedFill,
    Sequence,
    Strategy,
    StrategyContext,
    _finite_positive,
    accrue_borrow_charge,
    math,
    replace,
)
from alphaforge.backtest.depositary_dividend_ledger import DepositaryDividendLedger
from alphaforge.core.time import Timeframe
from alphaforge.execution.financing import accrue_financing
from alphaforge.validation.trend_dividend_settlement import DividendSettlementBook


class DepositaryEquityBacktester(EventDrivenBacktester):
    def __init__(
        self, *args, payments, depositary_terms, retrospective_vintage_ms=None, retrospective_actions=None, **kwargs
    ):
        super().__init__(*args, **kwargs)
        if self._asset_class is not AssetClass.EQUITY or self._tf != Timeframe.D1:
            raise ValueError("Payable loop supports daily equities only")
        self._payments = tuple(payments)
        self._depositary_terms = tuple(depositary_terms)
        if (retrospective_vintage_ms is None) != (retrospective_actions is None):
            raise ValueError("Retrospective vintage and complete action schedule required together")
        self._retrospective_vintage_ms = retrospective_vintage_ms
        self._retrospective_actions = None
        self._retrospective_digest = None
        if retrospective_vintage_ms is not None:
            DividendSettlementBook(Decimal(0), retrospective_vintage_ms=retrospective_vintage_ms)
            actions = tuple(retrospective_actions)
            keys = set()
            required = {}
            for action in actions:
                if not isinstance(action, CorporateAction):
                    raise ValueError("Typed retrospective actions required")
                action.require_known_by(retrospective_vintage_ms)
                key = (action.instrument_id, action.ex_date, action.action_type)
                if key in keys:
                    raise ValueError("Duplicate retrospective action")
                keys.add(key)
                if action.action_type is CorporateActionType.CASH_DIVIDEND:
                    required[key[:2]] = Decimal(str(action.cash_amount))
            paid = {}
            event_ids = set()
            for event in self._payments:
                DividendSettlementBook(
                    Decimal(0), retrospective_vintage_ms=retrospective_vintage_ms
                ).accrue(event, Decimal(0), as_of_ms=event.ex_ms)
                key = (event.symbol, event.ex_ms)
                if key in paid or event.event_id in event_ids:
                    raise ValueError("Duplicate retrospective payment")
                paid[key] = event.cash_per_share
                event_ids.add(event.event_id)
            if paid != required:
                raise ValueError("Exact complete retrospective dividend schedule required")
            self._retrospective_actions = actions
            self._retrospective_digest = hashlib.sha256(
                json.dumps(
                    {
                        "vintage_ms": retrospective_vintage_ms,
                        "actions": [asdict(a) for a in actions],
                    },
                    sort_keys=True,
                    default=str,
                ).encode()
            ).hexdigest()
        self._payment_digest = hashlib.sha256(
            json.dumps(
                [asdict(e) for e in self._payments],
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()

    def _load_corporate_actions(self, ids, *, start, end):
        if self._retrospective_actions is None:
            return super()._load_corporate_actions(ids, start=start, end=end)
        # This explicit, bound schedule is the retrospective source of authority.
        # Do not rewrite available_at or route it through a historical PIT cutoff.
        if any(a.instrument_id not in ids for a in self._retrospective_actions):
            raise ValueError("Retrospective schedule contains instruments outside the run")
        result = {}
        for action in self._retrospective_actions:
            if start <= action.ex_date < end:
                result.setdefault(action.instrument_id, []).append(action)
        for events in result.values():
            events.sort(key=lambda a: (a.ex_date, a.action_type.value))
        return result

    def _advance_cash_interval(self, ledger, start, end, marks, counters):
        boundaries = sorted({e.pay_ms for e in self._payments if start <= e.pay_ms <= end})
        cursor = start
        for boundary in sorted({*boundaries, end}):
            if boundary > cursor and self._financing_data is not None:
                currencies = {inst.quote for inst in ledger._instruments.values()}
                if len(currencies) != 1:
                    raise ValueError("Single financing currency required")
                quote = self._financing_data.quote(next(iter(currencies)), as_of=cursor)
                if quote is None:
                    raise ValueError("Missing financing quote at payment segment")
                short_value = sum(
                    abs(pos.qty) * marks[iid]
                    for iid, pos in ledger.positions().items()
                    if pos.qty < 0
                )
                accrual = accrue_financing(
                    quote,
                    cash_balance=ledger.cash,
                    short_market_value=short_value,
                    start_ts=cursor,
                    end_ts=boundary,
                    decision_ts=cursor,
                )
                ledger.apply_financing(accrual)
                counters["financing_intervals_applied"] += 1
            ledger.settle_dividends(as_of_ms=boundary)
            cursor = boundary

    def _build_result(self, ledger, *args, **kwargs):
        result = super()._build_result(ledger, *args, **kwargs)
        result.config.update(
            {
                "cash_accounting": "payable_dividend_chronological_v1",
                "payment_schedule_sha256": self._payment_digest,
                "dividend_settlements": ledger.dividend_settlements(),
                "depositary_cash_records": ledger.depositary_records(),
                "depositary_terms": [asdict(t) for t in self._depositary_terms],
                "terminal_pending_dividends": ledger.pending_dividends,
                "terminal_settled_cash": ledger.cash,
                "base_loop_source_sha256": (
                    "0b7b4af71abd736256f8844249de39d1ca5f1ea433bd67116b9cc5b3508a6736"
                ),
            }
        )
        if self._retrospective_vintage_ms is not None:
            result.config.update(
                {
                    "research_mode": "RETROSPECTIVE_CURRENT_VINTAGE",
                    "point_in_time_proven": False,
                    "retrospective_vintage_ms": self._retrospective_vintage_ms,
                    "retrospective_action_schedule_sha256": self._retrospective_digest,
                    "retrospective_action_records": [
                        asdict(a) for a in self._retrospective_actions
                    ],
                }
            )
        return result

    def run(
        self,
        strategy: Strategy,
        instrument_ids: Sequence[str],
        *,
        start: Ms,
        end: Ms,
        initial_cash: float = 100_000.0,
    ) -> BacktestResult:
        """Run ``strategy`` over ``[start, end)`` and return the full result.

        ``start``/``end`` must be ``tf``-aligned epoch-ms UTC; bars with
        ``ts_open in [start, end)`` define the run. Raises ``ValueError`` on
        unknown instruments, an empty/too-short bar set (< 2 bar closes), or
        malformed bounds. Propagates :class:`LookaheadError` (contract breach
        — a bug, never a data condition) and
        :class:`~alphaforge.core.errors.CostModelMisuse` (an order escaped
        the sizing guards) — both must halt the run, not be smoothed over.
        """
        ids = list(dict.fromkeys(instrument_ids))
        if not ids:
            raise ValueError("instrument_ids must be non-empty")
        if end <= start:
            raise ValueError(f"end ({end}) must be > start ({start})")
        if start % self._tf.ms or end % self._tf.ms:
            raise ValueError(
                f"start/end must be {self._tf.value}-aligned epoch-ms, got {start}/{end}"
            )
        if not _finite_positive(initial_cash):
            raise ValueError(f"initial_cash must be finite and > 0, got {initial_cash!r}")

        insts: dict[str, Instrument] = {}
        for iid in ids:
            inst = self._instruments.get(iid, as_of=end)
            if inst is None:
                # SCD2 validity starts at first INGESTION time, so a run that
                # ends before the store's first record resolves no version at
                # as_of=end. Fall back to the EARLIEST recorded version (the
                # nearest-in-time record for a historical run) — a documented
                # v1 simplification consistent with the static as_of=end
                # attribute resolution above; truly unknown ids still raise.
                history = self._instruments.history(iid)
                if not history:
                    raise ValueError(f"unknown instrument {iid!r} (no SCD2 record)")
                inst = history[0][2]
            insts[iid] = inst
        market_status_coverage_hash: str | None = None
        if self._market_status is not None:
            market_status_coverage_hash = self._market_status.require_coverage(
                tuple(ids), start=start, end=end
            )
        if self._financing_data is not None:
            currencies = {inst.quote for inst in insts.values()}
            if len(currencies) != 1:
                raise ValueError(
                    f"financing replay requires one ledger currency; got {sorted(currencies)!r}"
                )

        bars = self._load_bars(ids, start=start, end=end)
        # The decision grid is the set of bar *closes*, each modelled as the open
        # of the bar an order would fill into: the close of bar ``o`` is
        # ``calendar.next_bar_open(o, tf)`` — for the 24/7 crypto calendar this is
        # exactly ``o + tf.ms`` (byte-identical to the prior bare-step grid), and for
        # an XNYS session calendar a Friday close maps to the following Monday open so
        # the fill target ``bars[iid].get(decision_ts)`` lands on a real session bar
        # instead of a phantom weekend slot.
        grid = sorted(
            {
                self._calendar.next_bar_open(ts_open, self._tf)
                for rows in bars.values()
                for ts_open in rows
            }
        )
        for left, right in pairwise(grid):
            if self._calendar.next_bar_open(left, self._tf) != right:
                raise ValueError("Missing union session; cannot skip financing/event time")
        if len(grid) < 2:
            raise ValueError(
                f"need at least 2 bar closes in [{start}, {end}) for {ids}, got {len(grid)}"
            )
        last_close_of: dict[str, Ms] = {
            iid: self._calendar.next_bar_open(max(rows), self._tf)
            for iid, rows in bars.items()
            if rows
        }
        funding_events = self._load_funding(insts, start=start, end=end)
        funding_ptr: dict[str, int] = dict.fromkeys(funding_events, 0)
        # Corporate-action splits (EQUITY sleeve only; 2026-07-18 marking-fix campaign):
        # a position held across a split ex-date must convert (qty·ratio, avg/ratio) or
        # the raw-close mark fabricates a 1/ratio-sized phantom P&L jump (the ALIT
        # 1-for-20 defect). Crypto/MF paths are untouched: the load is gated on the
        # asset class AND their lakes carry no corporate_actions partitions.
        corporate_actions = (
            self._load_corporate_actions(ids, start=start, end=end)
            if self._asset_class is AssetClass.EQUITY
            else {}
        )
        corporate_action_ptr: dict[str, int] = dict.fromkeys(corporate_actions, 0)
        provider: CostInputProvider = (
            LakeCostInputs(
                self._reader,
                ids,
                start=start,
                end=end,
                anchor_tf=self._tf,
                calendar=self._calendar,
            )
            if self._cost_inputs is None
            else self._cost_inputs
        )

        ledger = DepositaryDividendLedger(
            initial_cash,
            insts,
            payments=self._payments,
            depositary_terms=self._depositary_terms,
            retrospective_vintage_ms=self._retrospective_vintage_ms,
        )
        counters: dict[str, int] = dict.fromkeys(COUNTER_NAMES, 0)
        if isinstance(self._fill_model, ParticipationCappedFill):
            counters.update(
                {
                    "dropped_no_bar_liquidity": 0,
                    "partial_fill_orders": 0,
                    "partial_fill_residual_canceled": 0,
                }
            )
        if self._borrow_data is not None:
            counters.update(
                {
                    "borrow_locates_denied": 0,
                    "borrow_locates_partial": 0,
                    "borrow_quotes_missing": 0,
                    "borrow_recall_fills_applied": 0,
                    "borrow_recalls_queued": 0,
                    "dynamic_borrow_charges_applied": 0,
                    "forced_buy_ins_queued": 0,
                }
            )
        if self._market_status is not None:
            counters.update(
                {
                    "market_status_blocks": 0,
                    "market_status_close_only_blocks": 0,
                }
            )
        order_records: list[dict[str, object]] = []
        position_records: list[dict[str, object]] = []
        reason_by_order: dict[str, str] = {}
        record_by_order: dict[str, dict[str, object]] = {}
        last_close: dict[str, float] = {}
        pending: list[OrderRequest] = []
        recall_remaining: dict[tuple[str, Ms, Ms, Ms], float] = {}
        recall_keys_by_order: dict[str, tuple[tuple[str, Ms, Ms, Ms], ...]] = {}
        final_close = grid[-1]
        # Short-borrow carry: a single general-collateral per-day rate (0 for a crypto
        # perp book -> the accrual below is skipped, byte-identical). Accrued on the SHORT
        # leg over the CALENDAR days between consecutive bars (weekends included).
        borrow_rate = self._cost_model.borrow_frac_per_day()

        for t in grid:
            counters["bars_processed"] += 1
            # The bar that just closed at decision instant ``t`` is the session bar
            # whose open is ``floor_bar(t - 1, tf)``: for the 24/7 calendar this is
            # exactly ``t - tf.ms`` (byte-identical), and for an XNYS session calendar
            # the prior open of a Monday decision is the preceding Friday session
            # (never a phantom weekend slot at ``t - tf.ms``).
            prev_open = self._calendar.floor_bar(t - 1, self._tf)

            # Apply ex-date entitlement/splits before this session's fills.
            if corporate_actions:
                pending = self._apply_due_corporate_actions(
                    corporate_actions,
                    corporate_action_ptr,
                    bars,
                    ledger,
                    last_close,
                    pending,
                    record_by_order,
                    counters,
                    prev_open,
                    t,
                )

            ledger.settle_dividends(as_of_ms=prev_open)

            # (0) fill orders queued at the previous close against the bar
            #     opening at that close (ts_open == decision_ts).
            for order in pending:
                filled_qty = self._execute(
                    order, insts, bars, provider, ledger, counters, record_by_order
                )
                recall_keys = recall_keys_by_order.pop(order.client_order_id, ())
                qty_to_allocate = filled_qty
                for key in recall_keys:
                    allocated = min(recall_remaining[key], qty_to_allocate)
                    recall_remaining[key] -= allocated
                    qty_to_allocate -= allocated
                    if allocated > 0.0:
                        counters["borrow_recall_fills_applied"] += 1
                    if qty_to_allocate <= 0.0:
                        break
            pending = []
            # Positions now reflect fills at prev_open. Process cash events and
            # financing chronologically through the next modeled session boundary.
            interval_marks = {
                iid: rows[prev_open].open if prev_open in rows else last_close.get(iid)
                for iid, rows in bars.items()
            }
            self._advance_cash_interval(ledger, prev_open, t, interval_marks, counters)
            # Borrow charges cover post-fill holdings over [prev_open, t],
            # valued at the session open (with last-known marks for gaps).
            if self._borrow_data is not None and prev_open is not None:
                for iid, pos in ledger.positions().items():
                    if pos.qty >= 0.0:
                        continue
                    mark = interval_marks.get(iid)
                    if mark is None:
                        continue
                    quote = self._borrow_data.quote(iid, as_of=prev_open)
                    if quote is None:
                        raise ValueError(
                            f"missing PIT borrow quote for open short {iid!r} at {prev_open}"
                        )
                    accrue_borrow_charge(
                        quote,
                        short_qty=abs(pos.qty),
                        mark_price=mark,
                        start_ts=prev_open,
                        end_ts=t,
                        decision_ts=prev_open,
                    )
                    days = (t - prev_open) / _DAY_MS
                    rate_per_day = quote.annual_fee_bps * 1e-4 / quote.day_count_basis
                    ledger.apply_borrow(iid, t, rate_per_day, days, mark)
                    counters["borrow_charges_applied"] += 1
                    counters["dynamic_borrow_charges_applied"] += 1
            elif borrow_rate > 0.0 and prev_open is not None:
                days = (t - prev_open) / _DAY_MS
                for iid, pos in ledger.positions().items():
                    if pos.qty < 0.0:
                        mark = interval_marks.get(iid)
                        if mark is not None:
                            ledger.apply_borrow(iid, t, borrow_rate, days, mark)
                            counters["borrow_charges_applied"] += 1

            # (1) stored funding events with ts_funding in (prev_close, t];
            #     pointer per instrument is monotone, so "<= t" is exact.
            for iid, events in funding_events.items():
                ptr = funding_ptr[iid]
                while ptr < len(events) and events[ptr][0] <= t:
                    ts_funding, rate = events[ptr]
                    ptr += 1
                    bar = bars[iid].get(prev_open)
                    mark = bar.close if bar is not None else last_close.get(iid)
                    if mark is not None:  # no close ever seen => provably flat: no-op
                        ledger.apply_funding(iid, ts_funding, rate, mark)
                funding_ptr[iid] = ptr

            # (2) mark at close[t] (last-known closes carry across per-
            #     instrument gaps so open positions always mark — documented).
            for iid, rows in bars.items():
                bar = rows.get(prev_open)
                if bar is not None:
                    last_close[iid] = bar.close
            state = ledger.mark(
                {iid: last_close[iid] for iid in ledger.positions()},
                t,
            )

            # (3) administratively close only lifecycle-confirmed delistings. A terminal
            #     history for an instrument whose metadata still says active is a stale/
            #     missing-price defect, not permission to fabricate a same-bar exit.
            if t < final_close:
                for pos in list(ledger.positions().values()):
                    if last_close_of.get(pos.instrument_id) != t:
                        continue
                    inst = insts[pos.instrument_id]
                    if inst.delisted_ts is None or inst.delisted_ts > final_close:
                        raise ValueError(
                            f"terminal price history for active instrument "
                            f"{pos.instrument_id!r} ends at {t}; refusing to infer a "
                            "delisting or fabricate an exit without lifecycle metadata"
                        )
                    self._force_flat(
                        pos.instrument_id,
                        inst,
                        ledger,
                        last_close[pos.instrument_id],
                        t,
                        counters,
                        order_records,
                        reason_by_order,
                    )
                state = ledger.mark(
                    {iid: last_close[iid] for iid in ledger.positions()},
                    t,
                )
            equity = state.equity_quote

            # snapshot positions at this close (post administrative actions)
            for pos in state.positions:
                mark = last_close[pos.instrument_id]
                position_records.append(
                    {
                        "ts": t,
                        "instrument_id": pos.instrument_id,
                        "qty": pos.qty,
                        "mark": mark,
                        "weight": pos.qty * mark / equity,
                        "unreal_pnl": pos.qty * (mark - pos.avg_entry_price),
                    }
                )

            # (4) strategy decision at close t
            ctx = StrategyContext(
                reader=self._reader,
                tf=self._tf,
                ts=t,
                equity=equity,
                positions={p.instrument_id: p.qty for p in state.positions},
                instruments=insts,
                asset_class=self._asset_class,
            )
            targets = strategy.on_bar_close(ctx)

            # (5) discretize targets -> orders queued for the next close
            pending = self._discretize(
                targets,
                insts,
                bars,
                ledger,
                equity,
                t,
                prev_open,
                counters,
                order_records,
                reason_by_order,
                record_by_order,
            )
            if self._borrow_data is not None:
                pending = self._queue_borrow_recalls(
                    pending,
                    ledger,
                    insts,
                    t,
                    last_close,
                    recall_remaining,
                    recall_keys_by_order,
                    counters,
                    order_records,
                    reason_by_order,
                    record_by_order,
                )

        if self._retrospective_actions is not None and any(
            corporate_action_ptr[iid] != len(events) for iid, events in corporate_actions.items()
        ):
            raise ValueError("Retrospective action schedule not fully consumed")

        # Orders decided on the final bar have no t+1: zero fills, loud counter.
        for order in pending:
            counters["unfilled_final_bar"] += 1
            record_by_order[order.client_order_id]["status"] = "unfilled_final_bar"

        return self._build_result(
            ledger,
            insts,
            ids,
            start=start,
            end=end,
            initial_cash=initial_cash,
            counters=counters,
            order_records=order_records,
            position_records=position_records,
            reason_by_order=reason_by_order,
            market_status_coverage_hash=market_status_coverage_hash,
        )

    def _apply_due_corporate_actions(
        self,
        actions: Mapping[str, list[CorporateAction]],
        action_ptr: dict[str, int],
        bars: Mapping[str, dict[Ms, BarView]],
        ledger: Ledger,
        last_close: dict[str, float],
        pending: list[OrderRequest],
        record_by_order: dict[str, dict[str, object]],
        counters: dict[str, int],
        prev_open: Ms,
        t: Ms,
    ) -> list[OrderRequest]:
        """Apply due ex-date groups before fills and return the converted order queue.

        Cash dividends accrue against the position held before the ex-date fill, so an
        order buying at the ex open receives no prior entitlement. Splits convert both
        open positions and pre-ex queued quantities. Mixed split/dividend events on the
        same boundary fail closed while exposed because the lake lacks deliverable-basis
        metadata needed to order them safely.
        """
        for iid, events in actions.items():
            ptr = action_ptr[iid]
            while ptr < len(events) and events[ptr].ex_date <= prev_open:
                ex_date = events[ptr].ex_date
                if ex_date != prev_open:
                    raise ValueError("Missing exact ex-date session; no delayed action replay")
                end_ptr = ptr
                while end_ptr < len(events) and events[end_ptr].ex_date == ex_date:
                    events[end_ptr].require_known_by(
                        t
                        if self._retrospective_vintage_ms is None
                        else self._retrospective_vintage_ms
                    )
                    end_ptr += 1
                group = events[ptr:end_ptr]
                split_events = [
                    event for event in group if event.action_type is CorporateActionType.SPLIT
                ]
                dividends = [
                    event
                    for event in group
                    if event.action_type is CorporateActionType.CASH_DIVIDEND
                ]
                pos = ledger.positions().get(iid)
                has_pending = any(order.instrument_id == iid for order in pending)
                if split_events and dividends and (pos is not None or has_pending):
                    raise ValueError(
                        f"mixed split/dividend boundary for exposed instrument {iid!r} "
                        f"at {ex_date} lacks deliverable-basis ordering"
                    )
                if split_events and (pos is not None or has_pending):
                    bar = bars[iid].get(prev_open)
                    if bar is None:
                        break  # defer conversion until a post-boundary bar is observable
                    ratio = math.prod(event.ratio for event in split_events)
                    pre_close = last_close.get(iid)
                    if (
                        pre_close is None
                        or not _finite_positive(pre_close)
                        or not _finite_positive(bar.open)
                    ):
                        raise ValueError(
                            f"split for {iid!r} at {ex_date} has no verifiable price boundary"
                        )
                    log_err = abs(math.log((bar.open / pre_close) * ratio))
                    verified_ratio = self._verified_split_events.get((iid, ex_date))
                    exact_event_verified = verified_ratio is not None and math.isclose(
                        ratio,
                        verified_ratio,
                        rel_tol=0.0,
                        abs_tol=1e-12,
                    )
                    if log_err > _SPLIT_SANITY_MAX_ABS_LOG and not exact_event_verified:
                        raise ValueError(
                            f"split record(s) for {iid} at ex={ex_date} failed the sanity "
                            f"guard: stored ratio {ratio:.6g} disagrees with the actual price "
                            f"move {pre_close:.6g} -> {bar.open:.6g} (|log err| {log_err:.3f} "
                            f"> {_SPLIT_SANITY_MAX_ABS_LOG:.2f}); refusing to continue with "
                            "an unconverted exposed position or order"
                        )
                    if log_err > _SPLIT_SANITY_MAX_ABS_LOG:
                        _LOG.info(
                            "issuer-verified split bypassed price-gap heuristic: "
                            "instrument=%s ex_date=%s ratio=%.12g log_error=%.6f",
                            iid,
                            ex_date,
                            ratio,
                            log_err,
                        )
                    if pos is not None:
                        ledger.apply_split(iid, ex_date, ratio)
                    last_close[iid] = pre_close / ratio
                    converted: list[OrderRequest] = []
                    for order in pending:
                        if order.instrument_id == iid:
                            order = replace(order, qty=order.qty * ratio)
                            record = record_by_order.get(order.client_order_id)
                            if record is not None:
                                record["qty"] = order.qty
                        converted.append(order)
                    pending = converted
                    counters["corporate_actions_applied"] += len(split_events)
                if dividends and pos is not None:
                    pre_close = last_close.get(iid)
                    if pre_close is None or not _finite_positive(pre_close):
                        raise ValueError(
                            f"cash dividend for {iid!r} at {ex_date} has no verifiable pre-ex close"
                        )
                    total_cash = sum(event.cash_amount or 0.0 for event in dividends)
                    multiple = total_cash / pre_close
                    if multiple > _DIVIDEND_SANITY_MAX_PRE_CLOSE_MULTIPLE:
                        raise ValueError(
                            f"cash dividend for {iid!r} at {ex_date} is {total_cash:.12g} "
                            f"per share, {multiple:.6g}x the pre-ex close {pre_close:.12g}; "
                            "refusing unverified dividend units/lifecycle semantics"
                        )
                for dividend in dividends:
                    if ledger.apply_cash_dividend(iid, ex_date, dividend.cash_amount or 0.0) != 0.0:
                        counters["corporate_actions_applied"] += 1
                        counters["cash_dividends_applied"] += 1
                ptr = end_ptr
                action_ptr[iid] = ptr
        return pending
