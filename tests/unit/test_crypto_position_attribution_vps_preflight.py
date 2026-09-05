from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = ROOT / "artifacts" / "engineering" / "crypto_position_attribution_vps_preflight.json"
OBSERVATION = (
    ROOT
    / "artifacts"
    / "engineering"
    / "crypto_position_attribution_vps_preflight_observation.json"
)
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy_crypto_position_attribution_vps.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def test_vps_preflight_is_hash_locked_and_never_self_authorizes() -> None:
    payload = json.loads(PREFLIGHT.read_text(encoding="utf-8"))

    assert payload["schema"] == "canli.alphac-crypto-position-attribution-vps-preflight.v1"
    assert payload["status"] == "READY_FOR_AUTHORIZED_DEPLOYMENT"
    assert payload["authorization"] == {
        "granted": False,
        "remote_mutations_performed": False,
        "required_before_rollout": True,
    }

    files = payload["required_files"]
    assert [item["path"] for item in files] == [
        "src/alphaforge/execution/paper.py",
        "src/alphaforge/live/store.py",
        "src/alphaforge/live/loop.py",
    ]
    for item in files:
        assert _sha256(ROOT / item["path"]) == item["desired_sha256"]
        assert len(item["remote_sha256"]) == 64


def test_vps_preflight_preserves_strategy_and_requires_safe_rollout() -> None:
    payload = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    scope = payload["change_scope"]

    for key in (
        "historical_backfill",
        "signal_logic_changed",
        "portfolio_weights_changed",
        "risk_limits_changed",
        "order_generation_changed",
        "trade_schedule_changed",
        "strategy_fingerprint_changed",
    ):
        assert scope[key] is False

    rollout = payload["rollout_contract"]
    assert rollout[0] == "REVERIFY_ALL_THREE_REMOTE_SHA256_VALUES"
    assert "REENABLE_TIMER_WITHOUT_FORCING_AN_EXTRA_TRADING_CYCLE" in rollout
    assert "WAIT_FOR_THE_NEXT_NATURAL_SCHEDULED_CYCLE" in rollout
    assert payload["current_remote_state"]["attribution_gate_status"] == ("SCHEMA_NOT_YET_MIGRATED")
    assert "does not claim deployment" in payload["claim_boundary"]


def test_latest_read_only_preflight_observation_is_current_and_fail_closed() -> None:
    contract = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    observation = json.loads(OBSERVATION.read_text(encoding="utf-8"))

    assert observation["content_hash"] == _content_hash(observation)
    assert observation["status"] == "PASS_READ_ONLY_PREFLIGHT_DEPLOYMENT_NOT_AUTHORIZED"
    assert observation["passes_read_only_preflight"] is True
    assert observation["remote_mutations_performed"] is False
    assert observation["deployment_authorized"] is False
    assert observation["forced_cycle_run"] is False
    assert observation["remote_snapshot"]["timer_state"] == "active"
    assert observation["remote_snapshot"]["service_state"] == "inactive"
    assert observation["remote_snapshot"]["files"] == {
        item["path"]: item["remote_sha256"] for item in contract["required_files"]
    }
    assert not set(observation["remote_snapshot"]["position_snapshot_columns"]).intersection(
        {"mark_price", "mark_source", "market_value_quote", "unrealized_pnl_quote"}
    )
    bindings = observation["source_bindings"]
    assert bindings["deployment_tool_sha256"] == _sha256(DEPLOY_SCRIPT)
    assert bindings["preflight_contract_sha256"] == _sha256(PREFLIGHT)
    assert "does not claim deployment" in observation["claim_boundary"]
