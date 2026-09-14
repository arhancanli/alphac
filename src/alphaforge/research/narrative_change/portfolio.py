"""Task 5 of the plan: portfolio, execution, costs and capacity.

Transcribed from the pre-registration's *Timing and portfolio* section:

- Enter each cohort at the second XNYS session open after calendar month-end; hold exactly 63
  sessions; cohorts never refresh, restart or exit on later news.
- Each cohort is equal notional, 50 percent long and 50 percent short. Concurrent cohort weight
  vectors are averaged and stock gross exposure is normalized to 1.0; positions shared across
  cohorts net before costs.
- Hedge trailing 252-session SPY beta estimated only from adjusted-close returns ending at the
  cohort month-end; clamp each stock's beta to [-1, 1]; combine with the cohort's signed
  weights; aggregate the active cohorts' stock weights and hedge their resulting beta with SPY;
  normalize total gross including the hedge to 1.0.
- Baseline costs: 15 bps one-way on stocks, 1 bp on SPY, 3 percent annualized borrow on every
  short. Stress: 30 bps, 2 bps, 6 percent. Costs apply to actual netted turnover.
- Missing-open execution: a stock target may change only on a session with an observed open
  for that stock; a halt spanning an intended change holds the prior weight (and its beta
  contribution) until the next observed open, realizing the reopening interval before turnover
  cost; deferred changes are reported.
- Delisting: the last observed open force-flats the position with normal cost; the move into
  that final bar is realized; every such event is reported and any occurrence makes the result
  DATA-ESCALATE rather than ADD (the runner enforces the label; this module reports the events).
- Capacity at 1, 5 and 10 bps of trailing 21-session median dollar ADV; no stock position above
  1 percent of ADV is admissible.

Execution convention. A position is taken at a session's open and its daily return is the move
from that open to the next observed open, on adjusted opens (the raw open scaled by the same
split and dividend factor the adjusted close carries). Nothing here reads a signal; it consumes
the cohorts Task 4 produced and the panel Task 3 loaded.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from alphaforge.research.narrative_change.inputs import DailyPanel, SessionCalendar
from alphaforge.research.narrative_change.signal import CohortResult

HOLD_SESSIONS = 63
BETA_LOOKBACK = 252
BETA_CLAMP = 1.0
ADV_WINDOW = 21
SESSIONS_PER_YEAR = 252


@dataclass(frozen=True)
class CostSchedule:
    stock_bps: float
    spy_bps: float
    borrow_annual: float

    @property
    def stock_rate(self) -> float:
        return self.stock_bps / 10_000.0

    @property
    def spy_rate(self) -> float:
        return self.spy_bps / 10_000.0

    @property
    def borrow_per_session(self) -> float:
        return self.borrow_annual / SESSIONS_PER_YEAR


BASELINE_COSTS = CostSchedule(stock_bps=15.0, spy_bps=1.0, borrow_annual=0.03)
STRESS_COSTS = CostSchedule(stock_bps=30.0, spy_bps=2.0, borrow_annual=0.06)


@dataclass(frozen=True)
class ActiveCohort:
    year: int
    month: int
    entry_pos: int
    exit_pos: int
    weights: dict[str, float]
    betas: dict[str, float]
    #: Per-name early exits (session position, exclusive) a diagnostic scenario imposes, for
    #: example a borrow recall. Empty for the primary path; never set by the signal.
    name_exit_pos: dict[str, int] = field(default_factory=dict)


@dataclass
class ExecutionEvent:
    session: dt.date
    instrument_id: str
    kind: str
    detail: str
    weight: float = 0.0  # the held weight the event acted on (force-flat haircuts need it)


@dataclass
class BookResult:
    """The daily book on the session grid plus every reported event."""

    sessions: list[dt.date]
    gross_return: np.ndarray
    net_return: np.ndarray
    stressed_net_return: np.ndarray
    stock_gross: np.ndarray
    hedge_weight: np.ndarray
    turnover: np.ndarray
    positions: np.ndarray
    events: list[ExecutionEvent] = field(default_factory=list)
    capacity: dict[str, Any] = field(default_factory=dict)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "session": self.sessions,
                "gross_return": self.gross_return,
                "net_return": self.net_return,
                "stressed_net_return": self.stressed_net_return,
                "stock_gross": self.stock_gross,
                "hedge_weight": self.hedge_weight,
                "turnover": self.turnover,
                "positions": self.positions,
            }
        ).set_index("session")

    @property
    def force_flat_events(self) -> int:
        return sum(1 for e in self.events if e.kind == "FORCE_FLAT")

    @property
    def deferred_changes(self) -> int:
        return sum(1 for e in self.events if e.kind == "DEFERRED")


def adjusted_open(panel: DailyPanel) -> pd.DataFrame:
    """The raw open scaled by the adjusted-close factor of the same session."""
    factor = panel.adjusted_close / panel.close
    return panel.open * factor


def cohort_betas(
    panel: DailyPanel,
    spy: DailyPanel,
    calendar: SessionCalendar,
    instrument_ids: list[str],
    month_end_session: dt.date,
) -> dict[str, float]:
    """Trailing 252-session SPY beta from adjusted-close returns ending at the month-end
    session, clamped to [-1, 1]. A stock with fewer than 60 paired returns gets beta 1.0 (the
    conservative hedge of a name whose beta cannot be estimated) and is reported by the caller."""
    end_pos = calendar.position(month_end_session)
    start_pos = max(0, end_pos - BETA_LOOKBACK)
    grid = calendar.opens[start_pos : end_pos + 1]
    spy_id = spy.instrument_ids[0]
    spy_ret = spy.adjusted_close[spy_id].reindex(grid).pct_change()
    betas: dict[str, float] = {}
    for iid in instrument_ids:
        if iid not in panel.adjusted_close.columns:
            betas[iid] = BETA_CLAMP
            continue
        ret = panel.adjusted_close[iid].reindex(grid).pct_change()
        pair = pd.concat([ret, spy_ret], axis=1).dropna()
        if len(pair) < 60:
            betas[iid] = BETA_CLAMP
            continue
        x = pair.iloc[:, 1].to_numpy(dtype="float64")
        y = pair.iloc[:, 0].to_numpy(dtype="float64")
        var = float(np.var(x, ddof=1))
        beta = float(np.cov(x, y, ddof=1)[0, 1] / var) if var > 0 else BETA_CLAMP
        betas[iid] = float(np.clip(beta, -BETA_CLAMP, BETA_CLAMP))
    return betas


def schedule_cohorts(
    cohorts: list[CohortResult],
    panel: DailyPanel,
    spy: DailyPanel,
    calendar: SessionCalendar,
    *,
    last_admissible_exit: dt.date,
) -> tuple[list[ActiveCohort], list[str]]:
    """Ranked cohorts with an entry session and a 63-session exit inside the window.

    A cohort whose exact exit falls after ``last_admissible_exit`` is excluded rather than
    truncated (the prereg's window rule); the exclusions are returned for the report.
    """
    active: list[ActiveCohort] = []
    excluded: list[str] = []
    for cohort in cohorts:
        if cohort.is_flat or cohort.entry_session is None:
            continue
        entry_pos = calendar.position(cohort.entry_session)
        exit_pos = entry_pos + HOLD_SESSIONS
        if exit_pos >= len(calendar) or calendar.dates[exit_pos] > last_admissible_exit:
            excluded.append(f"{cohort.year}-{cohort.month:02d}")
            continue
        month_end = calendar.offset(cohort.entry_session, -2)
        if month_end is None:
            excluded.append(f"{cohort.year}-{cohort.month:02d}")
            continue
        weights = cohort.weights()
        betas = cohort_betas(panel, spy, calendar, list(weights), month_end)
        active.append(ActiveCohort(cohort.year, cohort.month, entry_pos, exit_pos, weights, betas))
    return active, excluded


def target_book(active: list[ActiveCohort], pos: int) -> tuple[dict[str, float], float]:
    """Averaged, gross-normalized stock weights of the cohorts live at session ``pos`` and the
    SPY hedge weight that neutralizes their aggregate beta, with total gross normalized to 1."""
    live = [c for c in active if c.entry_pos <= pos < c.exit_pos]
    if not live:
        return {}, 0.0
    summed: dict[str, float] = {}
    beta_sum: dict[str, float] = {}
    for cohort in live:
        for iid, w in cohort.weights.items():
            if iid in cohort.name_exit_pos and pos >= cohort.name_exit_pos[iid]:
                continue  # a scenario-imposed early exit: the name is flat from here on
            summed[iid] = summed.get(iid, 0.0) + w / len(live)
            beta_sum[iid] = beta_sum.get(iid, 0.0) + w * cohort.betas[iid] / len(live)
    stock_gross = sum(abs(w) for w in summed.values())
    if stock_gross <= 0.0:
        return {}, 0.0
    scale = 1.0 / stock_gross
    weights = {iid: w * scale for iid, w in summed.items() if abs(w) > 1e-12}
    book_beta = sum(b * scale for b in beta_sum.values())
    hedge = -book_beta
    total = sum(abs(w) for w in weights.values()) + abs(hedge)
    if total <= 0.0:
        return weights, 0.0
    return {iid: w / total for iid, w in weights.items()}, hedge / total


def simulate_book(
    active: list[ActiveCohort],
    panel: DailyPanel,
    spy: DailyPanel,
    calendar: SessionCalendar,
    *,
    start_pos: int,
    end_pos: int,
    costs: CostSchedule = BASELINE_COSTS,
    stress: CostSchedule = STRESS_COSTS,
    turnover_cost: Callable[[str, int, float], float] | None = None,
    target_transform: Callable[[dict[str, float], float, int], tuple[dict[str, float], float]]
    | None = None,
) -> BookResult:
    """Run the book from ``start_pos`` to ``end_pos`` (session positions, end exclusive).

    Two optional hooks exist for diagnostic scenarios and are never set by the primary path:
    ``turnover_cost(instrument_id, session_pos, abs_weight_change)`` is an extra cost per unit
    of turnover (market impact at a capital point), charged to both the net and the stressed
    series; ``target_transform(target, hedge, session_pos)`` edits the NORMALIZED target book
    after it is composed (a partial fill, an unavailable borrow, an ADV cap), so the edit is
    not undone by the gross normalization inside ``target_book``.
    """
    aopen = adjusted_open(panel)
    spy_id = spy.instrument_ids[0]
    spy_open = adjusted_open(spy)[spy_id]
    grid = calendar.opens
    n = end_pos - start_pos
    gross = np.zeros(n)
    net = np.zeros(n)
    stressed = np.zeros(n)
    stock_gross = np.zeros(n)
    hedge_w = np.zeros(n)
    turnover = np.zeros(n)
    positions = np.zeros(n, dtype="int64")
    events: list[ExecutionEvent] = []
    held: dict[str, float] = {}
    held_hedge = 0.0
    # Deferred targets: a stock whose target could not change (no observed open) keeps its
    # prior weight; the last observed open per stock is tracked for the force-flat rule.
    last_observed_open_pos: dict[str, int] = {}
    # A force-flatted stock is administratively closed: its cohort target is ignored from then
    # on (a delisted name cannot be re-entered), so the closure is reported once, not deferred
    # every remaining session of the hold.
    flattened: set[str] = set()
    ids_all = sorted({iid for c in active for iid in c.weights})
    open_obs = {
        iid: aopen[iid].reindex(grid).to_numpy(dtype="float64")
        for iid in ids_all
        if iid in aopen.columns
    }
    spy_obs = spy_open.reindex(grid).to_numpy(dtype="float64")
    for k, pos in enumerate(range(start_pos, end_pos)):
        session = calendar.dates[pos]
        target, target_hedge = target_book(active, pos)
        if target_transform is not None:
            target, target_hedge = target_transform(target, target_hedge, pos)
        # --- execute: change a stock's weight only on a session with an observed open ---
        new_held: dict[str, float] = {}
        session_turnover = 0.0
        extra_cost = 0.0
        for iid in set(held) | set(target):
            wanted = 0.0 if iid in flattened else target.get(iid, 0.0)
            current = held.get(iid, 0.0)
            series = open_obs.get(iid)
            has_open = series is not None and np.isfinite(series[pos])
            if has_open:
                last_observed_open_pos[iid] = pos
            if wanted == current:
                if current != 0.0:
                    new_held[iid] = current
                continue
            if not has_open:
                # cannot trade: hold the prior weight, report the deferral
                if current != 0.0:
                    new_held[iid] = current
                events.append(
                    ExecutionEvent(
                        session, iid, "DEFERRED", f"target {wanted:+.4f} held at {current:+.4f}"
                    )
                )
                continue
            session_turnover += abs(wanted - current)
            if turnover_cost is not None:
                extra_cost += turnover_cost(iid, pos, abs(wanted - current))
            if wanted != 0.0:
                new_held[iid] = wanted
        held = new_held
        hedge_turnover = abs(target_hedge - held_hedge)
        held_hedge = target_hedge
        # --- realize: open at pos -> next observed open, per stock ---
        day_return = 0.0
        for iid, w in list(held.items()):
            series = open_obs.get(iid)
            if series is None or not np.isfinite(series[pos]):
                continue  # inside a halt: the reopening interval is realized when it reopens
            here = float(series[pos])
            nxt = pos + 1
            while nxt < len(grid) and not np.isfinite(series[nxt]):
                nxt += 1
            if nxt >= len(grid) or nxt - pos > HOLD_SESSIONS:
                # No later observed open inside a hold's reach: this is the final observed
                # open. Force-flat here with normal cost; the move into this bar was realized
                # on the previous session. Reported, and the runner labels DATA-ESCALATE.
                session_turnover += abs(w)
                if turnover_cost is not None:
                    extra_cost += turnover_cost(iid, pos, abs(w))
                events.append(
                    ExecutionEvent(session, iid, "FORCE_FLAT", "no later observed open", weight=w)
                )
                del held[iid]
                flattened.add(iid)
                continue
            if nxt == pos + 1:
                day_return += w * (float(series[nxt]) / here - 1.0)
            # nxt > pos + 1: a halt begins after this open; the weight is held and the whole
            # interval to the reopening open is realized below when it reopens.
        for iid, w in held.items():
            series = open_obs.get(iid)
            if series is None or not np.isfinite(series[pos]) or pos == 0:
                continue
            if np.isfinite(series[pos - 1]):
                continue  # an ordinary session, realized above by the previous session
            back = pos - 1
            while back >= 0 and not np.isfinite(series[back]):
                back -= 1
            if back >= 0 and back >= start_pos - 1:
                day_return += w * (float(series[pos]) / float(series[back]) - 1.0)
        if np.isfinite(spy_obs[pos]) and pos + 1 < len(grid) and np.isfinite(spy_obs[pos + 1]):
            day_return += held_hedge * (spy_obs[pos + 1] / spy_obs[pos] - 1.0)
        short_gross = sum(-w for w in held.values() if w < 0.0)
        cost_base = (
            session_turnover * costs.stock_rate
            + hedge_turnover * costs.spy_rate
            + short_gross * costs.borrow_per_session
        )
        cost_stress = (
            session_turnover * stress.stock_rate
            + hedge_turnover * stress.spy_rate
            + short_gross * stress.borrow_per_session
        )
        gross[k] = day_return
        net[k] = day_return - cost_base - extra_cost
        stressed[k] = day_return - cost_stress - extra_cost
        stock_gross[k] = sum(abs(w) for w in held.values())
        hedge_w[k] = held_hedge
        turnover[k] = session_turnover + hedge_turnover
        positions[k] = len(held)
    return BookResult(
        sessions=calendar.dates[start_pos:end_pos],
        gross_return=gross,
        net_return=net,
        stressed_net_return=stressed,
        stock_gross=stock_gross,
        hedge_weight=hedge_w,
        turnover=turnover,
        positions=positions,
        events=events,
    )


def capacity_report(
    active: list[ActiveCohort], panel: DailyPanel, calendar: SessionCalendar
) -> dict[str, Any]:
    """Capital at which the largest entry position reaches 1, 5, 10 bps and 1 percent of its
    stock's trailing 21-session median dollar ADV, taken over every cohort entry."""
    dollar = panel.dollar_volume()
    binding: list[tuple[float, str, str]] = []  # (weight / ADV, iid, cohort)
    for cohort in active:
        end = cohort.entry_pos - 1
        window = calendar.opens[max(0, end - ADV_WINDOW + 1) : end + 1]
        for iid, w in cohort.weights.items():
            if iid not in dollar.columns:
                continue
            adv = float(dollar[iid].reindex(window).median())
            if not np.isfinite(adv) or adv <= 0.0:
                continue
            binding.append((abs(w) / adv, iid, f"{cohort.year}-{cohort.month:02d}"))
    if not binding:
        return {"status": "NO_ENTRIES", "capital_at": {}}
    worst = max(binding)
    ratio, iid, cohort_label = worst
    capital_at = {
        label: float(fraction / ratio)
        for label, fraction in (
            ("1bp_adv", 1e-4),
            ("5bp_adv", 5e-4),
            ("10bp_adv", 1e-3),
            ("1pct_adv", 1e-2),
        )
    }
    return {
        "status": "REPORTED",
        "binding_position": {
            "instrument_id": iid,
            "cohort": cohort_label,
            "weight_over_adv": ratio,
        },
        "capital_at": capital_at,
        "admissibility_rule": (
            "no stock position above 1 percent of trailing 21-session median dollar ADV"
        ),
    }
