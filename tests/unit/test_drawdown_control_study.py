"""The drawdown-control study measures a ladder declared in the contract, on the published
study's own paths, and applies an acceptance rule declared before any number was seen."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from alphaforge.research.owner_goals import load_owner_goals

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "analyze_drawdown_control.py"
_SPEC = importlib.util.spec_from_file_location("analyze_drawdown_control", SCRIPT)
assert _SPEC and _SPEC.loader
MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(MOD)

CONTRACT = json.loads(MOD.CONTRACT.read_text())


def _max_drawdowns(returns):
    wealth = np.cumprod(1.0 + returns, axis=1)
    peaks = np.maximum.accumulate(
        np.concatenate([np.ones((returns.shape[0], 1)), wealth], axis=1), axis=1
    )[:, 1:]
    return np.max(1.0 - wealth / peaks, axis=1)


def test_ladder_specs_are_read_from_the_contract_not_typed() -> None:
    specs = MOD.ladder_specs(CONTRACT)
    ladder = CONTRACT["ladder"]
    assert specs["absorbing"]["flat_cooldown_bars"] is None
    assert (
        specs["auto_rearm"]["flat_cooldown_bars"] == ladder["secondary_scenario_flat_cooldown_days"]
    )
    for spec in specs.values():
        assert spec["dd_half_frac"] == ladder["dd_half_frac"] == CONTRACT["bound"] / 2
        assert spec["dd_flat_frac"] == ladder["dd_flat_frac"] == CONTRACT["bound"]
        assert spec["release_frac"] == ladder["release_frac_of_half"]


def test_the_contract_is_declared_before_measurement_and_its_bound_is_the_owner_goal() -> None:
    # The bound is the owner's (config/owner_goals.json), never typed here.
    assert CONTRACT["bound"] == load_owner_goals()["goals"]["combined_max_drawdown"]["bound"]
    assert CONTRACT["bound_source"] == "config/owner_goals.json goals.combined_max_drawdown.bound"
    assert CONTRACT["acceptance_rule"]["declared_before_measurement"] is True
    assert CONTRACT["trial_accounting"]["hypothesis_identities_spent"] == 0
    # Activated 2026-09-15 by the owner's recorded decision (PR #44): live may be True only with
    # the activation date, the owner's words and the measurement made BEFORE that date on file.
    activation = CONTRACT["activation"]
    if activation["live"] is True:
        assert activation["activated_on"] == "2026-09-15"
        assert activation["decision"]["by"].startswith("Arhan Canli")
        assert activation["decision"]["words"]
        assert CONTRACT["measurement"]["measured_on"] < activation["activated_on"]
        assert CONTRACT["status"] == activation["status_after_activation"]
    else:
        assert activation["live"] is False
    protocol = MOD.PROTOCOL.read_text()
    assert "Frozen:** 2026-09-14, before executing the study" in protocol
    assert "## v1.1: the ladder re-derived from the 10 percent bound" in protocol
    assert CONTRACT["history"][0]["bound"] == 0.11 and CONTRACT["history"][0]["superseded_on"]
    rule = CONTRACT["acceptance_rule"]
    old_rule = CONTRACT["history"][0]["acceptance_rule"]
    old_bound = CONTRACT["history"][0]["bound"]
    for key in (
        "p95_max_drawdown_with_absorbing_ladder_max",
        "p99_max_drawdown_with_absorbing_ladder_max",
    ):
        assert rule[key] == pytest.approx(old_rule[key] / old_bound * CONTRACT["bound"], abs=1e-6)


def test_baseline_check_fails_closed_when_the_published_study_is_not_reproduced() -> None:
    computed = {"expected": 0.05, "p95": 0.10}
    MOD.check_baseline(
        computed, {"expected_max_drawdown": 0.05, "p95_max_drawdown": 0.10}, label="x"
    )
    with pytest.raises(ValueError, match="does not reproduce"):
        MOD.check_baseline(
            computed, {"expected_max_drawdown": 0.05, "p95_max_drawdown": 0.1001}, label="x"
        )


def test_evaluate_reports_every_declared_measure_and_the_ladder_reduces_the_tail() -> None:
    rng = np.random.default_rng(5)
    returns = rng.normal(0.0, 0.012, size=(400, 300))
    returns[:, 40:46] = -0.035  # a common crash so most paths breach the bound without a ladder
    specs = MOD.ladder_specs(CONTRACT)
    result = MOD.evaluate(
        iter([returns[:200], returns[200:]]),
        drift=0.0,
        specs=specs,
        bound=CONTRACT["bound"],
        max_drawdowns_fn=_max_drawdowns,
    )
    assert result["paths"] == 400 and result["horizon_days"] == 300
    for key in ("no_ladder", "absorbing", "auto_rearm"):
        assert set(result[key]["max_drawdown"]) == {
            "expected",
            "median",
            "p95",
            "p99",
            "max",
            "stderr",
        }
    assert result["absorbing"]["max_drawdown"]["p95"] < result["no_ladder"]["max_drawdown"]["p95"]
    assert 0.0 < result["absorbing"]["halt_probability"] <= 1.0
    assert result["absorbing"]["mean_auto_rearms_per_path"] == 0.0
    assert result["auto_rearm"]["mean_auto_rearms_per_path"] >= 0.0
    assert (
        result["absorbing"]["overshoot_beyond_bound_on_halted_paths"]["max"] <= 0.5 * 0.035 + 1e-9
    )


def test_acceptance_applies_the_declared_thresholds_to_the_worse_model() -> None:
    def cell(p95, p99):
        return {"zero_drift": {"absorbing": {"max_drawdown": {"p95": p95, "p99": p99}}}}

    rule = CONTRACT["acceptance_rule"]
    p95_max = float(rule["p95_max_drawdown_with_absorbing_ladder_max"])
    p99_max = float(rule["p99_max_drawdown_with_absorbing_ladder_max"])
    # Cells sit exactly on the declared thresholds (derived from the contract, never typed):
    # the worse model decides, and exactly-at-threshold is accepted.
    results = {
        "circular_moving_block_bootstrap_63": cell(p95_max - 0.02, p99_max - 0.02),
        "correlation_regime": cell(p95_max, p99_max),
    }
    verdict = MOD.acceptance(results, CONTRACT)
    assert verdict["conservative_p95_with_absorbing_ladder"] == p95_max
    assert verdict["accepted_as_bound_mechanism"] is True
    results["correlation_regime"] = cell(p95_max + 0.015, p99_max)
    assert MOD.acceptance(results, CONTRACT)["accepted_as_bound_mechanism"] is False


@pytest.mark.workspace_evidence
def test_the_published_study_binds_the_contract_and_reproduced_its_baseline() -> None:
    if not MOD.OUTPUT.exists():
        pytest.skip("study artifact lives in the working tree")
    study = json.loads(MOD.OUTPUT.read_text())
    assert study["bindings"]["contract"]["sha256"] == MOD._sha256(MOD.CONTRACT)
    assert study["bindings"]["protocol"]["sha256"] == MOD._sha256(MOD.PROTOCOL)
    for model in study["baseline_reproduction"].values():
        for check in model.values():
            assert check["regenerated"] == check["published"]
    assert study["trial_accounting"]["hypothesis_identities_spent"] == 0
    assert study["acceptance"]["accepted_as_bound_mechanism"] == (
        study["status"]
        == (
            "LADDER_ACCEPTED_AS_BOUND_MECHANISM_LIVE_SINCE_"
            + str(CONTRACT["activation"]["activated_on"])
            if CONTRACT["activation"]["live"] is True
            else "LADDER_ACCEPTED_AS_BOUND_MECHANISM_NOT_LIVE"
        )
    )
    body = {k: v for k, v in study.items() if k != "content_hash"}
    assert study["content_hash"] == MOD._content_hash(body)
