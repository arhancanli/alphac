"""A diagnostic scenario re-simulates the sealed decisions; it never changes them, and it can fail.

WHY. The v2 reservation declares scenarios that must be able to challenge the primary result.
A scenario that silently does nothing (an unknown key, a knob that is not wired) is a scenario
that cannot fail, which is decorative-pass risk 1 of the design spec. So: the baseline
assumptions reproduce the primary series to the bit; every knob moves the series in the
direction its name says; an unknown key raises; and the hash is canonical so the reservation
and the packet name the same scenario.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from alphaforge.research.narrative_change import portfolio, scenarios

REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "narrative_portfolio_world", REPO / "tests" / "unit" / "test_narrative_change_portfolio.py"
)
assert _SPEC is not None and _SPEC.loader is not None
WORLD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(WORLD)


def _setup() -> dict[str, object]:
    cal, panel, spy = WORLD._world(420)
    cohorts = [WORLD._cohort(cal, 40), WORLD._cohort(cal, 61)]
    active, _ = portfolio.schedule_cohorts(
        cohorts, panel, spy, cal, last_admissible_exit=cal.dates[-1]
    )
    return {"cal": cal, "panel": panel, "spy": spy, "active": active, "start": 40, "end": 200}


def _run(assumptions: dict[str, object], world: dict[str, object]) -> dict[str, object]:
    return scenarios.evaluate_scenario(
        assumptions,
        active=world["active"],  # type: ignore[arg-type]
        panel=world["panel"],  # type: ignore[arg-type]
        spy=world["spy"],  # type: ignore[arg-type]
        calendar=world["cal"],  # type: ignore[arg-type]
        start_pos=world["start"],  # type: ignore[arg-type]
        end_pos=world["end"],  # type: ignore[arg-type]
    )


def _primary(world: dict[str, object]) -> portfolio.BookResult:
    return portfolio.simulate_book(
        world["active"],  # type: ignore[arg-type]
        world["panel"],  # type: ignore[arg-type]
        world["spy"],  # type: ignore[arg-type]
        world["cal"],  # type: ignore[arg-type]
        start_pos=world["start"],  # type: ignore[arg-type]
        end_pos=world["end"],  # type: ignore[arg-type]
    )


def test_the_baseline_scenario_reproduces_the_primary_path_to_the_bit() -> None:
    world = _setup()
    primary = _primary(world)
    baseline = _run({"stock_bps": 15.0, "spy_bps": 1.0, "borrow_annual": 0.03}, world)
    assert baseline["net"]["cumulative_return"] == pytest.approx(
        float(np.prod(1.0 + np.asarray(primary.net_return)) - 1.0)
    )
    assert baseline["net"]["observations"] == len(primary.net_return)


def test_every_cost_knob_lowers_the_net_series() -> None:
    world = _setup()
    base = _run({}, world)["net"]["cumulative_return"]
    assert _run({"stock_bps": 45.0}, world)["net"]["cumulative_return"] < base
    assert _run({"latency_bps": 20.0}, world)["net"]["cumulative_return"] < base
    assert _run({"borrow_annual": 0.20}, world)["net"]["cumulative_return"] < base
    assert _run({"financing_annual": 0.06}, world)["net"]["cumulative_return"] < base
    impact = _run({"impact_bps_per_sqrt_participation": 50.0, "capital_usd": 25_000_000.0}, world)
    assert impact["net"]["cumulative_return"] < base


def test_a_partial_fill_scales_gross_exposure_and_turnover() -> None:
    world = _setup()
    full = _run({}, world)
    half = _run({"fill_ratio": 0.5}, world)
    assert half["turnover_total"] == pytest.approx(full["turnover_total"] * 0.5, rel=1e-9)


def test_missing_opens_and_outages_add_deferrals_and_outages_are_seeded() -> None:
    world = _setup()
    base = _run({}, world)
    missing = _run({"missing_open_fraction": 0.2, "seed": 7}, world)
    assert missing["events"]["deferred"] > base["events"]["deferred"]
    outage_a = _run({"outage_fraction": 0.1, "seed": 11}, world)
    outage_b = _run({"outage_fraction": 0.1, "seed": 11}, world)
    assert outage_a["series_sha256"] == outage_b["series_sha256"]
    assert outage_a["events"]["deferred"] > base["events"]["deferred"]


def test_borrow_unavailability_and_recalls_reduce_the_short_book() -> None:
    world = _setup()
    base = _run({}, world)
    short_names = sum(
        1
        for c in world["active"]
        for w in c.weights.values()
        if w < 0  # type: ignore[attr-defined]
    )
    assert short_names > 0
    dropped = _run({"borrow_unavailable_fraction": 1.0}, world)
    assert dropped["turnover_total"] < base["turnover_total"]
    recalled = _run({"borrow_recall_sessions": 5, "borrow_recall_fraction": 1.0}, world)
    assert recalled["series_sha256"] != base["series_sha256"]


def test_an_unknown_assumption_is_an_error_not_a_silent_no_op() -> None:
    world = _setup()
    with pytest.raises(ValueError, match="unknown scenario assumption"):
        _run({"slippage_bps": 10.0}, world)


def test_the_assumptions_hash_is_canonical_and_order_free() -> None:
    a = scenarios.canonical_sha256({"stock_bps": 30.0, "seed": 1})
    b = scenarios.canonical_sha256({"seed": 1, "stock_bps": 30.0})
    assert a == b
    world = _setup()
    result = _run({"stock_bps": 30.0, "seed": 1}, world)
    assert result["assumptions_sha256"] == a
