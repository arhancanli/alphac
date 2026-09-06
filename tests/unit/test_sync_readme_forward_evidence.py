from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "sync_readme_forward_evidence.py"


def _module():
    spec = importlib.util.spec_from_file_location("sync_readme_forward_evidence_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _evidence(failed_checks: list[str]) -> dict:
    return {
        "generated_at": "2026-08-26T00:00:00+00:00",
        "provenance_gate": {"passes": not failed_checks, "failed_checks": failed_checks},
        "record": {
            "daily_return_observations": 17,
            "first_mark": "2026-08-07",
            "last_mark": "2026-08-26",
            "cumulative_return": -0.02,
        },
        "drawdown_evidence": {
            "realized_live_max_drawdown": 0.024,
            "current_composition_conservative_expected_max_drawdown": 0.09,
            "current_composition_conservative_p95_max_drawdown": 0.16,
        },
        "diversification_evidence": {
            "current_sleeves": 4,
            "target_total_sleeves": 14,
            "average_pairwise_correlation": 0.02,
        },
    }


README_TEMPLATE = """**Evidence snapshot:** 2026-08-25. Later marks follow.

| Paper sleeves | old |
| Forward record | old |
| Drawdown | old |
| Diversification | old |

No forward Sharpe is established. The 16-return record is too short, and its provenance gate
currently passes.
Historical simulations, modeled risk and broker-derived paper marks remain separately labelled.
"""


def test_sync_names_stale_crypto_cycle_instead_of_claiming_rollout_is_missing() -> None:
    updated = _module().synchronize(
        _evidence(["crypto_position_attribution_covers_last_mark"]), README_TEMPLATE
    )

    assert "crypto attribution does not cover the latest mark" in updated
    assert "latest composite mark is newer than the last attributed crypto cycle" in updated
    assert "until crypto position attribution is deployed" not in updated


def test_sync_reports_a_passing_provenance_gate_directly() -> None:
    updated = _module().synchronize(_evidence([]), README_TEMPLATE)

    assert "provenance currently passes the publication gate" in updated
    assert "its provenance gate currently passes" in updated
