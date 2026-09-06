from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
# Path literals below deliberately keep "artifacts/..." joined in one string (rather than split
# across separate Path("artifacts") / "engineering" segments): scripts/mutation_ledger.py discovers
# guards over published claims by searching each test file's source text for the literal substring
# "artifacts/", and a split literal is invisible to that search -- a guard present in the suite but
# absent from the derived coverage list. See PUBLISHED_MARKERS in scripts/mutation_ledger.py.
PREFLIGHT = ROOT / "artifacts/engineering/crypto_position_attribution_vps_preflight.json"
OBSERVATION = (
    ROOT / "artifacts/engineering" / "crypto_position_attribution_vps_preflight_observation.json"
)
ROLLOUT_VERIFICATION = (
    ROOT / "artifacts/engineering" / "crypto_position_attribution_rollout_verification.json"
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

    # The contract is legitimately re-pinned over time (desired_revisions records each move), so
    # a fixed historical observation cannot stay bound to the CURRENT contract hash forever --
    # that would make this assertion a gate nobody can pass again after the first legitimate
    # re-pin. What must hold is weaker but still fail-closed: the observation's binding must equal
    # either today's contract hash, or a hash some desired_revisions entry itself records as the
    # contract state it superseded (its "preceding_contract_sha256"), dated after the observation
    # was taken. A contract edit that forgets to record its predecessor hash leaves no match here
    # and still fails.
    observed_contract_sha256 = bindings["preflight_contract_sha256"]
    current_contract_sha256 = _sha256(PREFLIGHT)
    if observed_contract_sha256 != current_contract_sha256:
        observed_at = datetime.fromisoformat(observation["observed_at_utc"])
        superseding_entries = [
            entry
            for entry in contract.get("desired_revisions", [])
            if entry.get("preceding_contract_sha256") == observed_contract_sha256
        ]
        assert superseding_entries, (
            "observation is bound to contract hash "
            f"{observed_contract_sha256}, which is neither the current contract hash "
            f"({current_contract_sha256}) nor recorded as a preceding_contract_sha256 in any "
            "desired_revisions entry -- a contract edit forgot to record its predecessor"
        )
        for entry in superseding_entries:
            revision_date = datetime.fromisoformat(entry["date"]).date()
            assert revision_date > observed_at.date(), (
                f"desired_revisions entry dated {entry['date']} claims to record the contract "
                f"state preceding this observation, but does not postdate the observation taken "
                f"at {observation['observed_at_utc']}"
            )

    assert "does not claim deployment" in observation["claim_boundary"]


def test_current_deployed_state_is_verified_by_rollout_receipt() -> None:
    """The 2026-08-25 preflight observation only ever proved a PRE-migration snapshot.

    What proves the state deployed TODAY (including the 2026-09-05/09-06 desired_revisions and
    any out-of-band rsync) is scripts/verify_crypto_position_attribution_rollout.py, run hourly by
    the live tick with real SSH access this test does not have. This guard reads that receipt
    rather than re-deriving it.
    """
    contract = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    assert ROLLOUT_VERIFICATION.is_file(), (
        f"no rollout verification receipt at {ROLLOUT_VERIFICATION}; it is written by "
        "scripts/verify_crypto_position_attribution_rollout.py, which the hourly live tick runs"
    )
    verification = json.loads(ROLLOUT_VERIFICATION.read_text(encoding="utf-8"))

    assert verification["content_hash"] == _content_hash(verification)
    assert verification["passes"] is True

    latest_revision_date = max(
        datetime.fromisoformat(entry["date"]).date()
        for entry in contract.get("desired_revisions", [])
    )
    verified_at_raw = verification.get("verified_at_utc")
    assert verified_at_raw is not None, (
        "rollout verification receipt has not recorded a verified_at_utc timestamp yet -- the "
        f"tick has not re-verified since the {latest_revision_date} contract revision; waiting "
        f"for a tick at or after {latest_revision_date}"
    )
    verified_at = datetime.fromisoformat(verified_at_raw)
    assert verified_at.date() >= latest_revision_date, (
        f"rollout verification receipt was last stamped {verified_at_raw}, which does not "
        f"postdate the {latest_revision_date} contract revision -- the tick has not yet "
        f"re-verified current deployed state; waiting for a tick dated on or after "
        f"{latest_revision_date}"
    )

    current_desired = {item["path"]: item["desired_sha256"] for item in contract["required_files"]}
    recorded_remote_files = verification.get("source_binding", {}).get("remote_source_files")
    assert recorded_remote_files is not None, (
        "rollout verification receipt does not yet record remote_source_files -- it has not been "
        "regenerated since scripts/verify_crypto_position_attribution_rollout.py was extended to "
        "capture them"
    )
    assert recorded_remote_files == current_desired, (
        "rollout verification receipt's recorded remote file hashes do not match the contract's "
        "CURRENT desired_sha256 values -- the deployed VPS state has drifted from what the "
        "contract now declares desired"
    )
