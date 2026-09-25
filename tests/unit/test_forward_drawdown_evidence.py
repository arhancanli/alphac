from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _module():
    path = REPO / "scripts/seal_forward_drawdown_evidence.py"
    spec = importlib.util.spec_from_file_location("forward_drawdown_evidence_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _paper_state():  # type: ignore[no-untyped-def]
    path = Path(__file__).resolve().parents[2] / "scripts/paper_trading_state.py"
    spec = importlib.util.spec_from_file_location("paper_state_for_drawdown_evidence", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sealer():
    return _module()


def _model(sealer):
    return json.loads(sealer.MODEL.read_text())


def test_seal_preserves_study_values_but_refuses_live_equivalence(sealer) -> None:
    payload = sealer.build()
    objective = payload["objective"]
    equivalence = payload["production_equivalence"]
    assert payload["status"] == (
        "CURRENT_COMPOSITION_EXPECTED_WITHIN_OBJECTIVE_LIVE_NOT_ESTABLISHED"
    )
    assert payload["integrity_passes"] is True
    assert objective["study_production_labelled_expected_max_drawdown"] == pytest.approx(
        0.10251155801473733
    )
    assert objective["study_production_labelled_p95_max_drawdown"] == pytest.approx(
        0.1876321103559252
    )
    assert objective["live_expected_max_drawdown_established"] is False
    # The current-composition figures are the current-book study's own (re-measured whenever the
    # book changes: four sleeves in v3, three from v4), never literals typed here.
    study = json.loads(sealer.CURRENT_BOOK_MODEL.read_text())["objective"]
    assert objective["current_composition_conservative_expected_max_drawdown"] == pytest.approx(
        study["conservative_modeled_expected_max_drawdown"]
    )
    assert objective["current_composition_conservative_p95_max_drawdown"] == pytest.approx(
        study["conservative_modeled_p95_max_drawdown"]
    )
    assert equivalence["passes"] is False
    assert set(equivalence["failed_checks"]) == set(equivalence["checks"])
    assert equivalence["declared_live_sleeves"] == _paper_state().N_SLEEVES
    assert equivalence["declared_constituent_blend_strategy_volatility_target"] == 0.15
    assert equivalence["declared_live_book_level_volatility_target"] is None
    # Activated on 2026-09-15: the published ladder is the contract's, read from the contract.
    control = json.loads(sealer.DRAWDOWN_CONTROL_CONTRACT.read_text())
    ladder = equivalence["declared_live_book_level_drawdown_ladder"]
    if control["activation"]["live"]:
        for key in ("dd_half_frac", "dd_flat_frac", "release_frac_of_half"):
            assert ladder[key] == control["ladder"][key]
    else:
        assert ladder is None
    assert payload["content_hash"] == sealer._content_hash(payload)


def test_simulation_design_drift_fails_closed(sealer) -> None:
    model = _model(sealer)
    model["parameters"]["paths"] = 10_000
    with pytest.raises(ValueError, match="simulation design drifted"):
        sealer.build(model=model)


def test_production_cell_drift_fails_closed(sealer) -> None:
    model = _model(sealer)
    model["production_setting"]["expected_max_drawdown"] += 0.001
    with pytest.raises(ValueError, match="not uniquely bound"):
        sealer.build(model=model)


def test_unordered_tail_quantile_fails_closed(sealer) -> None:
    model = _model(sealer)
    model["grid"][0]["p95_max_drawdown"] = 0.01
    with pytest.raises(ValueError, match="quantiles are unordered"):
        sealer.build(model=model)


def test_live_declaration_drift_fails_closed(sealer) -> None:
    live = json.loads(sealer.LIVE_CHANGE_CONTRACT.read_text())
    live = copy.deepcopy(live)
    live["declared_surface"]["strategy_settings"]["cov_window_bars"] = 360
    with pytest.raises(ValueError, match="do not match production code"):
        sealer.build(live_change_contract=live)


def test_flagship_aggregation_drift_fails_closed(sealer) -> None:
    live = json.loads(sealer.LIVE_CHANGE_CONTRACT.read_text())
    live = copy.deepcopy(live)
    live["declared_surface"]["book_aggregation_settings"]["book_level_vol_target_ann"] = 0.10
    with pytest.raises(ValueError, match="does not bind the live specification"):
        sealer.build(live_change_contract=live)


def test_current_book_drawdown_mutation_fails_closed(sealer) -> None:
    current = json.loads(sealer.CURRENT_BOOK_MODEL.read_text())
    current = copy.deepcopy(current)
    current["objective"]["conservative_modeled_expected_max_drawdown"] += 0.001
    with pytest.raises(ValueError, match="content hash is invalid"):
        sealer.build(current_book_model=current)
