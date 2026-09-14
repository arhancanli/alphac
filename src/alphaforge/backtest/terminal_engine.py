"""Research-only crypto replay with explicit intrabar terminal settlement events."""

from dataclasses import asdict

from alphaforge.backtest.engine import EventDrivenBacktester
from alphaforge.backtest.terminal_ledger import TerminalLedger
from alphaforge.core.types import AssetClass


class TerminalBacktester(EventDrivenBacktester):
    """Split cash-event ordering at termination without generating strategy bars.

    Coincident funding and termination are rejected pending a sourced tie policy.
    Funding valuation explicitly selects hourly open or parent hourly close.
    Both are proxies, not asserted historical funding marks. No-event runs
    default to unchanged parent funding. Financing/borrow providers are not
    supported in this crypto-only adapter; they require explicit interval splits.
    """

    def __init__(
        self,
        *args,
        terminal_events=(),
        allow_modeled=False,
        funding_mark_policy=None,
        carry_terminal_eligibility=False,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.terminal_events = tuple(terminal_events)
        self.allow_modeled = allow_modeled
        self.carry_terminal_eligibility = carry_terminal_eligibility
        self._active_terminal_events = self.terminal_events
        self.funding_mark_policy = funding_mark_policy or (
            "interval_open_proxy" if self.terminal_events else "parent_interval_close"
        )
        if self.funding_mark_policy not in {"interval_open_proxy", "parent_interval_close"}:
            raise ValueError("Unknown funding mark policy")
        if self._asset_class is not AssetClass.CRYPTO_PERP:
            raise ValueError("Terminal adapter supports crypto perpetuals only")
        if self._financing_data is not None or self._borrow_data is not None:
            raise ValueError("Terminal adapter requires separately implemented financing splits")

    def run(self, strategy, instrument_ids, *, start, end, initial_cash=100_000.0):
        seen = set()
        for event in self.terminal_events:
            event.verify_source()
            if event.instrument_id not in instrument_ids or event.instrument_id in seen:
                raise ValueError("Unknown or duplicate terminal instrument")
            seen.add(event.instrument_id)
            if event.basis == "modeled" and not self.allow_modeled:
                raise ValueError("Modeled settlement requires explicit opt-in")
            if not self.carry_terminal_eligibility and not start < event.effective_ts <= end:
                raise ValueError("Terminal event must fall after start and at or before end")
        # Each parent run starts flat. Past events retain their execution block;
        # they must not settle again or alter the inherited opening cash.
        self._active_terminal_events = tuple(
            e for e in self.terminal_events if start < e.effective_ts <= end
        )
        return super().run(
            strategy, instrument_ids, start=start, end=end, initial_cash=initial_cash
        )

    def _create_ledger(self, initial_cash, instruments):
        return TerminalLedger(
            initial_cash,
            instruments,
            events=self._active_terminal_events,
            allow_modeled=self.allow_modeled,
        )

    def _execute(self, order, insts, bars, provider, ledger, counters, record_by_order):
        if any(
            e.instrument_id == order.instrument_id and order.decision_ts >= e.effective_ts
            for e in self.terminal_events
        ):
            record_by_order[order.client_order_id]["status"] = "blocked_terminal_contract"
            counters["terminal_orders_blocked"] = counters.get("terminal_orders_blocked", 0) + 1
            return 0.0
        return super()._execute(order, insts, bars, provider, ledger, counters, record_by_order)

    def _process_interval_funding(
        self, ledger, funding_events, funding_ptr, bars, prev_open, last_close, t
    ):
        if not self._active_terminal_events and self.funding_mark_policy == "parent_interval_close":
            return super()._process_interval_funding(
                ledger, funding_events, funding_ptr, bars, prev_open, last_close, t
            )
        timeline = []
        for iid, events in funding_events.items():
            ptr = funding_ptr[iid]
            while ptr < len(events) and events[ptr][0] <= t:
                when, rate = events[ptr]
                if when < prev_open:
                    raise ValueError("Funding event precedes replay interval")
                timeline.append((when, 0, iid, rate))
                ptr += 1
            funding_ptr[iid] = ptr
        for event in self._active_terminal_events:
            if event.instrument_id not in ledger._settled and event.effective_ts <= t:
                if event.effective_ts < prev_open:
                    raise ValueError("Terminal event precedes replay interval")
                timeline.append((event.effective_ts, 1, event.instrument_id, None))
        for when, kind, iid, value in sorted(timeline):
            if kind == 1:
                ledger.settle_at(iid, when)
            else:
                # Do not invent an exchange policy for simultaneous cash events.
                coincident = any(e.effective_ts == when for e in self._active_terminal_events)
                if coincident:
                    raise ValueError("Coincident funding and termination need a sourced tie policy")
                bar = bars[iid].get(prev_open)
                mark = (
                    (bar.open if self.funding_mark_policy == "interval_open_proxy" else bar.close)
                    if bar is not None
                    else last_close.get(iid)
                )
                if mark is not None:
                    ledger.apply_funding(iid, when, value, mark)

    def _build_result(self, ledger, *args, **kwargs):
        # Settlement rows remain in the accounting fill table, but must never
        # masquerade as liquidity-backed strategy executions.
        reasons = dict(kwargs["reason_by_order"])
        for event in self.terminal_events:
            reasons[f"terminal-{event.effective_ts}-{event.instrument_id}"] = (
                "administrative_terminal_settlement"
            )
        kwargs["reason_by_order"] = reasons
        result = super()._build_result(ledger, *args, **kwargs)
        result.config["terminal_events"] = [
            {**asdict(e), "source_path": str(e.source_path)} for e in self.terminal_events
        ]
        result.config["terminal_records"] = list(ledger.terminal_records)
        result.config["terminal_research_only"] = True
        result.config["funding_mark_policy"] = self.funding_mark_policy
        result.config["carry_terminal_eligibility"] = self.carry_terminal_eligibility
        return result
