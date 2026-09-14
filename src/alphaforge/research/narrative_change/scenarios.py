"""Diagnostic scenarios: every declared assumption set re-simulated on the sealed decisions.

WHY. The v2 reservation declares, before any return, the cost, execution and capacity scenarios
that must be able to challenge the primary result (config/trial_accounting_evidence_classes.json,
class ``mandatory_diagnostic_scenario``). A diagnostic recomputes outcomes on top of the exact
decisions the primary path made (the same cohorts, weights, entry and exit sessions); it never
changes which decisions were made, never spends an identity and can never be selected. This
module is the one place those assumptions are turned into a re-simulation, so the packet builder
and the reservation author read the same vocabulary.

Every assumption key below is a knob on ``portfolio.simulate_book`` or a post-processing step on
its result; an unknown key is an error, never a silent no-op, because a scenario that silently
does nothing is a scenario that cannot fail.

Assumption vocabulary (all optional; absent means the primary path's value):

- ``stock_bps``, ``spy_bps``, ``borrow_annual``: the cost schedule (baseline 15 / 1 / 0.03).
- ``latency_bps``: added to ``stock_bps`` (an adverse move between decision and fill).
- ``fill_ratio``: fraction of every target weight actually filled, in (0, 1].
- ``missing_open_fraction``, ``reject_fraction``: fraction of (name, session) opens removed at
  random (seeded); a removed open defers the target exactly as a halt does.
- ``outage_fraction``: fraction of whole sessions whose opens are removed for every name.
- ``borrow_unavailable_fraction``: fraction of short names per cohort that cannot be located
  and are dropped from the cohort (no renormalization: the unfilled short stays unfilled).
- ``borrow_recall_sessions`` with ``borrow_recall_fraction``: that fraction of short names is
  force-covered that many sessions after entry.
- ``financing_annual``: an annual charge on the stock gross exposure, per session.
- ``impact_bps_per_sqrt_participation`` with ``capital_usd``: square-root market impact per
  unit of turnover, participation being the traded dollar amount over the name's trailing
  21-session median dollar ADV at that session.
- ``adv_participation_cap_bps`` with ``capital_usd``: every cohort weight is capped so that the
  position at that capital is at most that many basis points of the name's ADV at entry.
- ``delisting_haircut``: an extra loss of that fraction of the held weight on every force-flat.
- ``seed``: the deterministic seed for every random removal above.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd

from alphaforge.research.narrative_change import evaluation, portfolio
from alphaforge.research.narrative_change.inputs import DailyPanel, SessionCalendar

KNOWN_KEYS = frozenset(
    {
        "stock_bps",
        "spy_bps",
        "borrow_annual",
        "latency_bps",
        "fill_ratio",
        "missing_open_fraction",
        "reject_fraction",
        "outage_fraction",
        "borrow_unavailable_fraction",
        "borrow_recall_sessions",
        "borrow_recall_fraction",
        "financing_annual",
        "impact_bps_per_sqrt_participation",
        "capital_usd",
        "adv_participation_cap_bps",
        "delisting_haircut",
        "seed",
        "label",
    }
)
ADV_WINDOW = 21
SESSIONS_PER_YEAR = 252.0


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _rng(assumptions: Mapping[str, Any]) -> np.random.Generator:
    return np.random.default_rng(int(assumptions.get("seed", 20260914)))


def _adv_at(panel: DailyPanel, calendar: SessionCalendar, iid: str, pos: int) -> float:
    dollar = panel.dollar_volume()
    if iid not in dollar.columns:
        return float("nan")
    end = pos - 1
    window = calendar.opens[max(0, end - ADV_WINDOW + 1) : end + 1]
    return float(dollar[iid].reindex(window).median())


def _transform_cohorts(
    active: list[portfolio.ActiveCohort],
    panel: DailyPanel,
    calendar: SessionCalendar,
    assumptions: Mapping[str, Any],
) -> list[portfolio.ActiveCohort]:
    """Pre-normalization edits: a recalled short leaves its cohort early. Nothing else."""
    rng = _rng(assumptions)
    recall_sessions = assumptions.get("borrow_recall_sessions")
    recall_fraction = float(assumptions.get("borrow_recall_fraction", 0.0))
    out: list[portfolio.ActiveCohort] = []
    for cohort in active:
        exits = dict(cohort.name_exit_pos)
        if recall_sessions is not None and recall_fraction > 0.0:
            shorts = sorted(iid for iid, w in cohort.weights.items() if w < 0.0)
            recalled = rng.random(len(shorts)) < recall_fraction
            for iid, recall in zip(shorts, recalled, strict=True):
                if recall:
                    exits[iid] = min(cohort.exit_pos, cohort.entry_pos + int(recall_sessions))
        out.append(replace(cohort, name_exit_pos=exits))
    return out


def _target_transform(
    active: list[portfolio.ActiveCohort],
    panel: DailyPanel,
    calendar: SessionCalendar,
    assumptions: Mapping[str, Any],
) -> Callable[[dict[str, float], float, int], tuple[dict[str, float], float]] | None:
    """Post-normalization edits of the target book: partial fills, unavailable borrows, caps."""
    fill_ratio = float(assumptions.get("fill_ratio", 1.0))
    unavailable = float(assumptions.get("borrow_unavailable_fraction", 0.0))
    cap_bps = assumptions.get("adv_participation_cap_bps")
    capital = float(assumptions.get("capital_usd", 0.0))
    if fill_ratio >= 1.0 and unavailable <= 0.0 and (cap_bps is None or capital <= 0.0):
        return None
    rng = _rng(assumptions)
    shorts = sorted({iid for c in active for iid, w in c.weights.items() if w < 0.0})
    excluded = {
        iid for iid, drop in zip(shorts, rng.random(len(shorts)) < unavailable, strict=True) if drop
    }
    entry_by_name: dict[str, int] = {}
    for cohort in active:
        for iid in cohort.weights:
            entry_by_name.setdefault(iid, cohort.entry_pos)

    def transform(
        target: dict[str, float], hedge: float, pos: int
    ) -> tuple[dict[str, float], float]:
        edited = {iid: w for iid, w in target.items() if iid not in excluded}
        if cap_bps is not None and capital > 0.0:
            for iid, w in list(edited.items()):
                adv = _adv_at(panel, calendar, iid, entry_by_name.get(iid, pos))
                if np.isfinite(adv) and adv > 0.0:
                    limit = float(cap_bps) / 10_000.0 * adv / capital
                    if abs(w) > limit:
                        edited[iid] = float(np.sign(w) * limit)
        if fill_ratio < 1.0:
            edited = {iid: w * fill_ratio for iid, w in edited.items()}
            hedge = hedge * fill_ratio
        return edited, hedge

    return transform


def _transform_panel(
    panel: DailyPanel,
    calendar: SessionCalendar,
    assumptions: Mapping[str, Any],
    *,
    start_pos: int,
    end_pos: int,
) -> DailyPanel:
    missing = float(assumptions.get("missing_open_fraction", 0.0))
    rejects = float(assumptions.get("reject_fraction", 0.0))
    outages = float(assumptions.get("outage_fraction", 0.0))
    if missing <= 0.0 and rejects <= 0.0 and outages <= 0.0:
        return panel
    rng = _rng(assumptions)
    open_frame = panel.open.copy()
    grid = calendar.opens[start_pos:end_pos]
    rows = open_frame.index.isin(grid)
    if missing + rejects > 0.0:
        mask = rng.random(open_frame.shape) < (missing + rejects)
        mask[~rows, :] = False
        open_frame = open_frame.mask(mask)
    if outages > 0.0:
        session_mask = rng.random(len(open_frame.index)) < outages
        session_mask[~rows] = False
        open_frame.loc[session_mask, :] = np.nan
    return DailyPanel(
        open=open_frame,
        close=panel.close,
        volume=panel.volume,
        adjusted_close=panel.adjusted_close,
        actions=panel.actions,
    )


def evaluate_scenario(
    assumptions: Mapping[str, Any],
    *,
    active: list[portfolio.ActiveCohort],
    panel: DailyPanel,
    spy: DailyPanel,
    calendar: SessionCalendar,
    start_pos: int,
    end_pos: int,
) -> dict[str, Any]:
    """Re-simulate the sealed decisions under one assumption set and report the series."""
    unknown = set(assumptions) - KNOWN_KEYS
    if unknown:
        raise ValueError("unknown scenario assumption(s): " + ", ".join(sorted(unknown)))
    costs = portfolio.CostSchedule(
        stock_bps=float(assumptions.get("stock_bps", portfolio.BASELINE_COSTS.stock_bps))
        + float(assumptions.get("latency_bps", 0.0)),
        spy_bps=float(assumptions.get("spy_bps", portfolio.BASELINE_COSTS.spy_bps)),
        borrow_annual=float(
            assumptions.get("borrow_annual", portfolio.BASELINE_COSTS.borrow_annual)
        ),
    )
    cohorts = _transform_cohorts(copy.deepcopy(active), panel, calendar, assumptions)
    scenario_panel = _transform_panel(
        panel, calendar, assumptions, start_pos=start_pos, end_pos=end_pos
    )
    impact = assumptions.get("impact_bps_per_sqrt_participation")
    capital = float(assumptions.get("capital_usd", 0.0))
    turnover_cost = None
    if impact is not None and capital > 0.0:
        dollar = panel.dollar_volume()
        opens = calendar.opens

        def _impact(iid: str, pos: int, abs_delta: float) -> float:
            if iid not in dollar.columns:
                return 0.0
            end = pos - 1
            window = opens[max(0, end - ADV_WINDOW + 1) : end + 1]
            adv = float(dollar[iid].reindex(window).median())
            if not np.isfinite(adv) or adv <= 0.0:
                return 0.0
            participation = abs_delta * capital / adv
            return float(impact) / 10_000.0 * float(np.sqrt(participation)) * abs_delta

        turnover_cost = _impact
    book = portfolio.simulate_book(
        cohorts,
        scenario_panel,
        spy,
        calendar,
        start_pos=start_pos,
        end_pos=end_pos,
        costs=costs,
        turnover_cost=turnover_cost,
        target_transform=_target_transform(cohorts, panel, calendar, assumptions),
    )
    net = np.array(book.net_return, dtype="float64")
    financing = float(assumptions.get("financing_annual", 0.0))
    if financing > 0.0:
        net = net - np.array(book.stock_gross, dtype="float64") * financing / SESSIONS_PER_YEAR
    haircut = float(assumptions.get("delisting_haircut", 0.0))
    if haircut > 0.0:
        session_index = {session: k for k, session in enumerate(book.sessions)}
        for event in book.events:
            if event.kind == "FORCE_FLAT" and event.session in session_index:
                net[session_index[event.session]] -= abs(event.weight) * haircut
    series = pd.Series(net, index=pd.Index(book.sessions))
    stats = evaluation.series_stats(series).as_dict()
    return {
        "assumptions": dict(assumptions),
        "assumptions_sha256": canonical_sha256(dict(assumptions)),
        "net": stats,
        "turnover_total": float(np.sum(book.turnover)),
        "mean_stock_gross": float(np.mean(book.stock_gross)),
        "mean_hedge_abs_weight": float(np.mean(np.abs(book.hedge_weight))),
        "events": {
            "deferred": sum(1 for e in book.events if e.kind == "DEFERRED"),
            "force_flat": sum(1 for e in book.events if e.kind == "FORCE_FLAT"),
        },
        "series_sha256": hashlib.sha256(series.to_numpy(dtype="float64").tobytes()).hexdigest(),
    }
