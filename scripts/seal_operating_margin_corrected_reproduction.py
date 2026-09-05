#!/usr/bin/env python3
"""Seal the completed corrected-data reproduction without changing its immutable files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

REPO: Final[Path] = Path(__file__).resolve().parents[1]
AUTHORIZATION: Final[Path] = (
    REPO / "artifacts/audit/operating_margin_corrected_replay_authorization.json"
)
HISTORICAL: Final[Path] = REPO / "artifacts/walkforward/single_operating_margin/walkforward.json"
REPRODUCTION_DIR: Final[Path] = (
    REPO
    / "artifacts/probe/fundamental_single_replays/e5f48adc25065ce9/"
    "corrected_corporate_actions_f812e1576bf430ee"
)
RESULT: Final[Path] = REPRODUCTION_DIR / "result.json"
WALKFORWARD: Final[Path] = REPRODUCTION_DIR / "walkforward.json"
EQUITY: Final[Path] = REPRODUCTION_DIR / "equity.parquet"
ENVIRONMENT: Final[Path] = REPRODUCTION_DIR / "replay_environment.json"
OUTPUT: Final[Path] = (
    REPO / "artifacts/audit/operating_margin_corrected_reproduction.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _load_sealed(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    declared = payload.pop("content_hash", None)
    actual = _content_hash(payload)
    payload["content_hash"] = declared
    if declared != actual:
        raise ValueError(f"content hash mismatch: {path.relative_to(REPO)}")
    return payload


def build() -> dict[str, Any]:
    authorization = _load_sealed(AUTHORIZATION)
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    replay = json.loads(WALKFORWARD.read_text(encoding="utf-8"))
    historical = json.loads(HISTORICAL.read_text(encoding="utf-8"))
    corrected = replay["summary"]
    original = historical["summary"]
    if result["verdict"] != "KILL" or result["corrected_measurement"] != corrected:
        raise ValueError("corrected reproduction verdict/summary does not reconcile")
    if corrected["sharpe"] > 0 or corrected["final_equity"] >= corrected["initial_equity"]:
        raise ValueError("KILL verdict is inconsistent with corrected measurement")
    if replay["config"].get("verified_split_events_count") != 2:
        raise ValueError("reproduction is not bound to exactly two verified split events")
    if result["ledger_state_before_and_after"] != {
        "active_rows": 226,
        "union_identities": 228,
    } or result["hypotheses_spent"] != 0:
        raise ValueError("zero-trial ledger invariant changed")

    payload: dict[str, Any] = {
        "schema": "canli.alphac-operating-margin-corrected-reproduction-seal.v1",
        "author": "Arhan Canli",
        "decision": "CORRECTED_OPERATING_MARGIN_REPRODUCED_KILL_PRESERVED",
        "hypotheses_spent": 0,
        "verdict": "KILL",
        "immutable_measurement": {
            "annualized_sharpe": original["sharpe"],
            "maximum_drawdown": original["max_dd"],
            "final_equity": original["final_equity"],
        },
        "corrected_measurement": {
            "annualized_sharpe": corrected["sharpe"],
            "maximum_drawdown": corrected["max_dd"],
            "final_equity": corrected["final_equity"],
            "total_return": corrected["total_return"],
            "cagr": corrected["cagr"],
            "n_periods": corrected["n_periods"],
        },
        "difference": {
            "annualized_sharpe": corrected["sharpe"] - original["sharpe"],
            "maximum_drawdown": corrected["max_dd"] - original["max_dd"],
            "final_equity": corrected["final_equity"] - original["final_equity"],
        },
        "lineage": {
            "authorization_path": str(AUTHORIZATION.relative_to(REPO)),
            "authorization_sha256": _sha256(AUTHORIZATION),
            "authorization_content_hash": authorization["content_hash"],
            "result_path": str(RESULT.relative_to(REPO)),
            "result_sha256": _sha256(RESULT),
            "walkforward_path": str(WALKFORWARD.relative_to(REPO)),
            "walkforward_sha256": _sha256(WALKFORWARD),
            "equity_path": str(EQUITY.relative_to(REPO)),
            "equity_sha256": _sha256(EQUITY),
            "environment_path": str(ENVIRONMENT.relative_to(REPO)),
            "environment_sha256": _sha256(ENVIRONMENT),
            "historical_path": str(HISTORICAL.relative_to(REPO)),
            "historical_sha256": _sha256(HISTORICAL),
        },
        "claim_boundary": (
            "The corporate-action correction materially changes the measured curve but does not "
            "rescue the factor: corrected Sharpe, CAGR, and total return remain negative. This is "
            "a zero-trial reproduction, not a new hypothesis, sleeve admission, or forward claim."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build()
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": payload["decision"], "content_hash": payload["content_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
