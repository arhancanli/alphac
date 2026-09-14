from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alphaforge.validation.experiments import ExperimentLog, ExperimentUnion, hypothesis_hash

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "reconcile_trial_debt.py"


def _live_union_identities() -> int:
    """The union as the public ledger counts it, computed rather than typed."""
    union = ExperimentUnion.discover(REPO / "var" / "experiments.jsonl", REPO)
    keys: set[str] = set()
    for path in union.paths:
        if path.exists():
            keys.update(hypothesis_hash(r.config) for r in ExperimentLog(path).all())
    return len(keys)


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
    # The applied artifact is history and its numbers are fixed. The CURRENT union is whatever
    # the ledgers hold today (229 on 2026-08-23, 347 after the 2026-09-14 external-ledger
    # import), so idempotence is asserted against the live union, never against a typed count.
    live_union = _live_union_identities()
    assert live_union >= 229
    assert current["selection_identities_before"] == live_union
    assert current["selection_identities_after"] == live_union
    assert current["new_records_pending_before_run"] == 0
