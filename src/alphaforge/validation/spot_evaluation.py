"""Deterministic spot execution simulation; real inputs require trial reservation.

Quote snapshots model fills, not prove achievable execution. IOC quantities are
capped at displayed side size and charged the limit price (conservative versus
the observed touch), with 25bps deducted from the received asset immediately.
The model has no queue/impact dynamics and cannot establish live capacity.
"""

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from alphaforge.execution.spot_plan import Asset, Holding, Quote, Snapshot, plan_orders
from alphaforge.portfolio.spot_restart import DAY_MS, SYMBOLS, DailyClose, target_weights

D = Decimal


@dataclass(frozen=True)
class EvaluationDay:
    decision_ms: int
    histories: dict[str, tuple[DailyClose, ...]]
    assets: dict[str, Asset]
    quotes: dict[str, Quote]
    bid_sizes: dict[str, Decimal]
    ask_sizes: dict[str, Decimal]


def evaluate(days: tuple[EvaluationDay, ...], *, initial_cash: Decimal) -> dict:
    """Evaluate a frozen path; no fitting, parameter search, or missing-day omission.

    A production runner must validate reservation and input hashes BEFORE calling.
    Day-end marks here mean post-decision liquidation marks at the supplied bid,
    not midnight closes. Daily returns include intervening marks and modeled fees.
    """
    if not isinstance(initial_cash, Decimal) or not initial_cash.is_finite() or initial_cash <= 0:
        raise ValueError("positive finite initial cash required")
    if not days:
        raise ValueError("evaluation days required")
    cash = initial_cash
    holdings = {s: D(0) for s in SYMBOLS}
    buyhold_cash = initial_cash * D("0.10")
    buyhold = {s: D(0) for s in SYMBOLS}
    rows = []
    previous_equity = initial_cash
    previous_buyhold = initial_cash
    previous_day = None
    observations = {}
    phase = None
    for index, day in enumerate(days):
        day_start = day.decision_ms // DAY_MS * DAY_MS
        offset = day.decision_ms % DAY_MS
        if previous_day is not None and day_start != previous_day + DAY_MS:
            raise ValueError("missing or reordered evaluation day")
        if phase is not None and offset != phase:
            raise ValueError("decision time drift changes the frozen path")
        previous_day, phase = day_start, offset
        targets = target_weights(day.histories, decision_ms=day.decision_ms)
        # Reject revised historical observations within a single frozen dataset.
        for symbol, bars in day.histories.items():
            for bar in bars:
                key = (symbol, bar.end_ms)
                if key in observations and observations[key] != bar.close:
                    raise ValueError("conflicting historical close")
                observations[key] = bar.close
        for sizes in (day.bid_sizes, day.ask_sizes):
            if set(sizes) != set(SYMBOLS) or any(
                not isinstance(v, Decimal) or not v.is_finite() or v < 0 for v in sizes.values()
            ):
                raise ValueError("finite nonnegative displayed size required")
        if set(day.quotes) != set(SYMBOLS):
            raise ValueError("missing quote")
        # Marking and trading are different operations. Preserve blocked trading
        # days rather than condition the return sample on executable snapshots.
        blocked_reasons = []
        for symbol, quote in day.quotes.items():
            if (
                any(
                    not isinstance(v, Decimal) or not v.is_finite() or v <= 0
                    for v in (quote.bid, quote.ask)
                )
                or quote.bid > quote.ask
            ):
                raise ValueError("invalid valuation quote")
            if any(
                type(ts) is not int or ts < 0
                for ts in (quote.source_ms, quote.received_ms, day.decision_ms)
            ):
                raise ValueError("invalid valuation timestamp")
            if not quote.source_ms <= quote.received_ms <= day.decision_ms:
                raise ValueError("disordered valuation quote")
            age = day.decision_ms - quote.source_ms
            if age > 60_000:
                raise ValueError("valuation quote exceeds one-minute bound")
            if age > 1000:
                blocked_reasons.append(symbol + ":stale_for_trade")
            if (quote.ask - quote.bid) / quote.bid > D("0.005"):
                blocked_reasons.append(symbol + ":wide_for_trade")
        equity = cash + sum(holdings[s] * day.quotes[s].bid for s in SYMBOLS)
        snapshot = Snapshot(
            "research-fixture-account",
            day.decision_ms,
            equity,
            cash,
            cash,
            {s: Holding(q, q) for s, q in holdings.items()},
            0,
            0,
            True,
            False,
        )
        orders = (
            ()
            if blocked_reasons
            else plan_orders(
                epoch="registered-research-path",
                decision_ms=day.decision_ms,
                expected_account_binding="research-fixture-account",
                snapshot=snapshot,
                assets=day.assets,
                quotes=day.quotes,
                targets=targets,
            )
        )
        fills = []
        fee_usd = D(0)
        for order in orders:
            symbol, side = order["symbol"], order["side"]
            size = day.ask_sizes[symbol] if side == "buy" else day.bid_sizes[symbol]
            step = day.assets[symbol].qty_step
            qty = (min(D(order["qty"]), size) / step).to_integral_value(rounding=ROUND_DOWN) * step
            if qty <= 0:
                continue
            price = D(order["limit_price"])
            notional = qty * price
            if side == "buy":
                cash -= notional
                base_fee = qty * D("0.0025")
                holdings[symbol] += qty - base_fee
                fee_asset, fee_qty = symbol.split("/")[0], base_fee
            else:
                holdings[symbol] -= qty
                quote_fee = notional * D("0.0025")
                cash += notional - quote_fee
                fee_asset, fee_qty = "USD", quote_fee
            fee_usd += notional * D("0.0025")
            fills.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "planned_qty": order["qty"],
                    "filled_qty": str(qty),
                    "price": str(price),
                    "fee_asset": fee_asset,
                    "fee_qty": str(fee_qty),
                }
            )
        if cash < 0 or any(q < 0 for q in holdings.values()):
            raise ValueError("simulation violated cash or long-only invariant")
        # Reference only: 45/45/10 initial allocation at observed ask plus 10bps,
        # full-fill analytical benchmark, explicitly not a capacity comparison.
        if index == 0:
            for symbol in SYMBOLS:
                buyhold[symbol] = (
                    initial_cash * D("0.45") / (day.quotes[symbol].ask * D("1.001"))
                ) * D("0.9975")
        equity_after = cash + sum(holdings[s] * day.quotes[s].bid for s in SYMBOLS)
        benchmark = buyhold_cash + sum(buyhold[s] * day.quotes[s].bid for s in SYMBOLS)
        rows.append(
            {
                "decision_ms": day.decision_ms,
                "cash": str(cash),
                "holdings": {s: str(q) for s, q in holdings.items()},
                "equity": str(equity_after),
                "return": str(equity_after / previous_equity - 1),
                "buyhold_equity": str(benchmark),
                "buyhold_return": str(benchmark / previous_buyhold - 1),
                "cash_benchmark_equity": str(initial_cash),
                "fee_usd_at_fill": str(fee_usd),
                "fills": fills,
                "blocked_rebalance_reasons": blocked_reasons,
                "valuation_quote_age_ms": {
                    s: day.decision_ms - q.source_ms for s, q in day.quotes.items()
                },
            }
        )
        previous_equity, previous_buyhold = equity_after, benchmark
    return {
        "status": "MODELED_PATH_NOT_ADMISSION",
        "rows": rows,
        "capacity_validated": False,
        "live_execution_validated": False,
        "benchmark_fill_assumption": "analytical_full_fill_not_liquidity_matched",
        "fee_posting_assumption": "immediate_economic_debit_not_broker_posting_time",
    }
