from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "reconcile_trial_debt.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("reconcile_trial_debt", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_forensic_inventory_covers_every_persisted_named_configuration() -> None:
    module = _module()
    candidates = module._all_candidates()

    assert len(candidates) == 78
    by_probe: dict[str, int] = {}
    for candidate in candidates:
        by_probe[candidate["probe"]] = by_probe.get(candidate["probe"], 0) + 1

    assert by_probe == {
        "alphamax_hyst_live": 6,
        "alphamax_turnover": 8,
        "alphatrend_arp": 3,
        "alphatrend_breadth": 4,
        "crypto_vrp_proxy": 1,
        "forensic_alphamax_construction": 8,
        "forensic_alphamax_weighting": 48,
    }


def test_weighting_robustness_and_posthoc_breadth_selectors_are_charged() -> None:
    module = _module()
    candidates = module._all_candidates()
    variants = {candidate["variant"] for candidate in candidates}

    assert len({v for v in variants if v.startswith("no_drift_")}) == 16
    assert len({v for v in variants if v.startswith("volatility_guard_")}) == 16
    assert "EXP_minus_SHY" in variants
    assert "PRUNED_22" in variants

    breadth_configs = {
        candidate["config"]["basket"]
        for candidate in candidates
        if candidate["probe"] == "alphatrend_breadth"
    }
    assert breadth_configs == {
        "BASE_17",
        "EXPANDED_33",
        "EXPANDED_MINUS_LARGEST_CONTRIBUTOR",
        "GREEDY_NEFF_PRUNED",
    }


def test_applied_reconciliation_preserves_first_delta_and_is_now_idempotent() -> None:
    module = _module()
    applied = module.json.loads(module.OUT.read_text())
    current = module.reconcile(apply=False)

    assert applied["selection_identities_before"] == 174
    assert applied["selection_identities_after"] == 228
    assert applied["new_records_pending_before_run"] == 54
    assert current["selection_identities_before"] == 229
    assert current["selection_identities_after"] == 229
    assert current["new_records_pending_before_run"] == 0
