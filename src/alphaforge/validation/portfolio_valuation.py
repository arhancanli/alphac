"""Isolated structural paper-valuation checks; not source authentication or admission.

USD only; midnight UTC cuts; separately partitioned accounts; external flows at
the closing cut only. No scheduler, transport, trading, or missing-data fallback.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from decimal import Context, Decimal, localcontext
from functools import wraps

import exchange_calendars as xcals
import pandas as pd

DAY_MS = 86_400_000


class ValuationError(ValueError):
    pass


def timestamp(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValuationError("Nonnegative integer millisecond timestamp required")
    return value


def money(value: str) -> Decimal:
    if not isinstance(value, str) or len(value) > 80 or not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        raise ValuationError("Finite plain decimal string required")
    number = Decimal(value)
    if len(value) > 80:
        raise ValuationError("Decimal input too long")
    return number


def fixed_precision(function):
    @wraps(function)
    def run(*args, **kwargs):
        with localcontext(Context(prec=200)):
            return function(*args, **kwargs)
    return run


def digest(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValuationError("SHA-256 digest required")


@dataclass(frozen=True)
class Component:
    name: str
    role: str  # sleeve, cash, overlay; attribution labels, not independence claims
    ledger_id: str  # whole-account/partition binding from trusted acquisition


@dataclass(frozen=True)
class Policy:
    epoch: str
    effective_cut_ms: int
    components: tuple[Component, ...]
    max_receipt_delay_ms: int  # must be frozen from acquisition capability
    reconciliation_tolerance_usd: str
    allocation_manifest_sha256: str
    instrument_calendars: tuple[tuple[str, str], ...] = ()

    def fingerprint(self) -> str:
        timestamp(self.effective_cut_ms)
        if self.effective_cut_ms % DAY_MS or not isinstance(self.epoch, str) or not self.epoch:
            raise ValuationError("Epoch and UTC-midnight effective cut required")
        timestamp(self.max_receipt_delay_ms)
        if self.max_receipt_delay_ms >= DAY_MS:
            raise ValuationError("Receipt delay must be shorter than a day")
        if not 0 <= money(self.reconciliation_tolerance_usd) <= Decimal('.01'):
            raise ValuationError("Reconciliation tolerance must be within one USD cent")
        digest(self.allocation_manifest_sha256)
        if not 1 <= len(self.components) <= 64:
            raise ValuationError("One to 64 declared components required")
        for component in self.components:
            if not all(isinstance(v, str) and v for v in [component.name, component.ledger_id]):
                raise ValuationError("Component name and ledger binding required")
            if component.role not in {'sleeve', 'cash', 'overlay'}:
                raise ValuationError("Unsupported component role")
        if len({c.name for c in self.components}) != len(self.components):
            raise ValuationError("Duplicate component")
        if len({c.ledger_id for c in self.components}) != len(self.components):
            raise ValuationError("Capital counted twice: duplicate ledger binding")
        if len(dict(self.instrument_calendars)) != len(self.instrument_calendars):
            raise ValuationError("Duplicate instrument calendar binding")
        for instrument, calendar in self.instrument_calendars:
            if not instrument or calendar not in {'XNYS', 'UTC24X7'}:
                raise ValuationError("Unsupported instrument calendar binding")
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True,
                                         separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class Position:
    instrument: str
    quantity: str
    price_usd: str
    price_asof_ms: int
    calendar: str  # XNYS official close or UTC24X7 exact cut
    source_sha256: str


@dataclass(frozen=True)
class Snapshot:
    component: str
    ledger_id: str
    epoch: str
    policy_sha256: str
    cut_ms: int
    cash_asof_ms: int
    positions_asof_ms: int
    received_ms: int
    cash_usd: str
    receivables_usd: str
    liabilities_usd: str
    reported_nav_usd: str
    positions: tuple[Position, ...]
    source_sha256: str
    cashflows_complete: bool


def expected_price_time(cut_ms: int, calendar: str) -> int:
    """Declared end-of-day marking rule, not a quote freshness assertion."""
    if calendar == 'UTC24X7':
        return cut_ms
    if calendar != 'XNYS':
        raise ValuationError("Unsupported valuation calendar")
    cut = pd.Timestamp(cut_ms, unit='ms', tz='UTC')
    cal = xcals.get_calendar('XNYS', start='2000-01-01', end='2030-12-31')
    if cut < cal.first_session.tz_localize('UTC') or cut > cal.last_session.tz_localize('UTC'):
        raise ValuationError("Valuation outside supported calendar range")
    # Midnight UTC is outside the US regular session. The latest completed
    # official close is permitted, including weekends/holidays; older closes are not.
    session = cal.date_to_session(cut.tz_localize(None).normalize(), direction='previous')
    close = cal.session_close(session)
    if close > cut:
        close = cal.session_close(cal.previous_session(session))
    return int(close.value // 1_000_000)


@fixed_precision
def value_book(policy: Policy, snapshots: tuple[Snapshot, ...], *,
               cut_ms: int, evaluated_ms: int) -> dict:
    fingerprint = policy.fingerprint()
    timestamp(cut_ms)
    timestamp(evaluated_ms)
    if cut_ms % DAY_MS or cut_ms < policy.effective_cut_ms:
        raise ValuationError("Invalid cut or pre-epoch valuation")
    expected = {c.name: c for c in policy.components}
    if len(snapshots) != len(expected) or {s.component for s in snapshots} != set(expected):
        raise ValuationError("Missing, duplicate or extra portfolio component")
    total = Decimal(0)
    components = {}
    evidence = []
    for snapshot in snapshots:
        if snapshot.ledger_id != expected[snapshot.component].ledger_id:
            raise ValuationError("Ledger binding mismatch")
        if snapshot.epoch != policy.epoch or snapshot.policy_sha256 != fingerprint:
            raise ValuationError("Mixed epoch or policy")
        for value in [snapshot.cut_ms, snapshot.cash_asof_ms, snapshot.positions_asof_ms]:
            if timestamp(value) != cut_ms:
                raise ValuationError("Cash, holdings and NAV must refer to the same cut")
        received = timestamp(snapshot.received_ms)
        if not cut_ms <= received <= cut_ms + policy.max_receipt_delay_ms:
            raise ValuationError("Receipt outside frozen reporting window")
        if evaluated_ms < received:
            raise ValuationError("Evidence not yet received at evaluation")
        if snapshot.cashflows_complete is not True:
            raise ValuationError("Cash-flow coverage incomplete")
        digest(snapshot.source_sha256)
        if len(snapshot.positions) > 10000:
            raise ValuationError("Position budget exceeded")
        if len({p.instrument for p in snapshot.positions}) != len(snapshot.positions):
            raise ValuationError("Duplicate position")
        if expected[snapshot.component].role == 'cash' and snapshot.positions:
            raise ValuationError("Cash component contains market positions")
        assets = Decimal(0)
        for position in snapshot.positions:
            digest(position.source_sha256)
            if dict(policy.instrument_calendars).get(position.instrument) != position.calendar:
                raise ValuationError("Instrument calendar not bound by policy")
            if not position.instrument or money(position.price_usd) <= 0:
                raise ValuationError("Instrument and positive price required")
            if timestamp(position.price_asof_ms) != expected_price_time(cut_ms, position.calendar):
                raise ValuationError("Missing, future or stale valuation price")
            assets += money(position.quantity) * money(position.price_usd)
        receivables = money(snapshot.receivables_usd)
        liabilities = money(snapshot.liabilities_usd)
        if receivables < 0 or liabilities < 0:
            raise ValuationError("Receivables and liabilities require nonnegative magnitudes")
        nav = money(snapshot.cash_usd) + assets + receivables - liabilities
        if abs(nav - money(snapshot.reported_nav_usd)) > money(policy.reconciliation_tolerance_usd):
            raise ValuationError("Component NAV does not reconcile")
        components[snapshot.component] = str(nav)
        total += nav
        evidence.append(snapshot.source_sha256)
    evidence_hash = hashlib.sha256(json.dumps({
        'policy': fingerprint, 'cut_ms': cut_ms, 'evaluated_ms': evaluated_ms,
        'snapshots': [asdict(s) for s in sorted(snapshots, key=lambda s: s.component)],
    }, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'status': 'STRUCTURAL_VALUATION_ONLY', 'epoch': policy.epoch,
            'valuation_evidence_sha256': evidence_hash,
            'policy_sha256': fingerprint, 'cut_ms': cut_ms, 'nav_usd': str(total),
            'components': components, 'source_sha256': evidence,
            'nonpositive_nav': total <= 0, 'authentication_verified': False,
            'runtime_clearance': False, 'portfolio_targets_established': False}


@dataclass(frozen=True)
class ExternalFlow:
    flow_id: str
    at_ms: int
    amount_usd: str  # positive deposit, negative withdrawal, included in closing cash
    source_sha256: str


@dataclass(frozen=True)
class CashBenchmark:
    start_ms: int
    end_ms: int
    simple_return: str
    source_sha256: str


@fixed_precision
def measured_interval(policy: Policy, opening: tuple[Snapshot, ...],
                      closing: tuple[Snapshot, ...], flows: tuple[ExternalFlow, ...],
                      benchmark: CashBenchmark, *, start_ms: int, end_ms: int,
                      evaluated_ms: int, flow_inventory_complete: bool) -> dict:
    if timestamp(end_ms) - timestamp(start_ms) != DAY_MS:
        raise ValuationError("One complete UTC day required; no bridging missing marks")
    before = value_book(policy, opening, cut_ms=start_ms, evaluated_ms=evaluated_ms)
    after = value_book(policy, closing, cut_ms=end_ms, evaluated_ms=evaluated_ms)
    if flow_inventory_complete is not True:
        raise ValuationError("External-flow inventory incomplete")
    if len(flows) > 10000:
        raise ValuationError("External-flow budget exceeded")
    if len({f.flow_id for f in flows}) != len(flows):
        raise ValuationError("Duplicate external flow")
    adjustment = Decimal(0)
    for flow in flows:
        if not flow.flow_id or timestamp(flow.at_ms) != end_ms:
            raise ValuationError("Only closing-boundary external flows supported")
        digest(flow.source_sha256)
        adjustment += money(flow.amount_usd)
    digest(benchmark.source_sha256)
    if timestamp(benchmark.start_ms) != start_ms or timestamp(benchmark.end_ms) != end_ms:
        raise ValuationError("Cash benchmark must cover the exact portfolio interval")
    reference = money(benchmark.simple_return)
    if reference <= -1:
        raise ValuationError("Invalid cash benchmark return")
    base = money(before['nav_usd'])
    if base <= 0:
        raise ValuationError("Cannot compute a return from nonpositive opening capital")
    end = money(after['nav_usd']) - adjustment
    net_return = end / base - 1
    evidence_hash = hashlib.sha256(json.dumps({
        'opening': before['valuation_evidence_sha256'],
        'closing': after['valuation_evidence_sha256'],
        'flows': [asdict(f) for f in sorted(flows, key=lambda f: f.flow_id)],
        'benchmark': asdict(benchmark),
    }, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'status': 'STRUCTURAL_INTERVAL_ONLY', 'net_return': str(net_return),
            'interval_evidence_sha256': evidence_hash,
            'excess_return': str(net_return - reference),
            'external_flow_usd': str(adjustment), 'flow_adjusted_closing_nav_usd': str(end),
            'capital_loss_at_least_100pct': end <= 0,
            'cash_benchmark_sha256': benchmark.source_sha256,
            'epoch': policy.epoch, 'policy_sha256': policy.fingerprint(),
            'start_ms': start_ms, 'end_ms': end_ms, 'authentication_verified': False,
            'runtime_clearance': False, 'portfolio_targets_established': False}
