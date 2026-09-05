#!/usr/bin/env python3
"""Seal the evidence-backed root cause of the operating-margin replay divergence."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Final

import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parent.parent
IDENTITY: Final[str] = "e5f48adc25065ce9"
RUN_NAME: Final[str] = "single_operating_margin"
PRESERVED: Final[Path] = REPO / "artifacts" / "walkforward" / RUN_NAME
REPLAY: Final[Path] = (
    REPO / "artifacts" / "probe" / "fundamental_single_replays" / IDENTITY
)
DIVIDEND_AUDIT: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_dividend_price_consistency.json"
)
OUTPUT: Final[Path] = REPLAY / "replay_root_cause.json"
PUBLIC_NAME: Final[str] = "fundamental_single_operating_margin_replay_root_cause.json"
HOSTS: Final[tuple[Path, Path]] = (
    REPO.parent / "meridian" / "public" / "glassbox" / PUBLIC_NAME,
    REPO.parent / "meridian-app" / "public" / "glassbox" / PUBLIC_NAME,
)
DIVIDEND_ENGINE_COMMIT: Final[str] = "c0eeceadbb47727a036dc37e8a33e3627fbc6fe9"
FIRST_MEASURED_AT: Final[str] = "2026-08-05T09:08:20.067000+00:00"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _commit_time(commit: str) -> dt.datetime:
    value = subprocess.check_output(
        ["git", "show", "-s", "--format=%cI", commit], cwd=REPO, text=True
    ).strip()
    return dt.datetime.fromisoformat(value).astimezone(dt.UTC)


def _aggregate_replay_actions() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for leg in sorted((REPLAY / "legs").glob("leg_*")):
        path = leg / "corporate_actions.parquet"
        if path.is_file():
            frame = pd.read_parquet(path)
            frame["leg"] = leg.name
            frames.append(frame)
    if not frames:
        raise FileNotFoundError("replay has no corporate-action evidence")
    return pd.concat(frames, ignore_index=True)


def build_finding() -> dict[str, Any]:
    failure_path = REPLAY / "replay_failure.json"
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    audit = json.loads(DIVIDEND_AUDIT.read_text(encoding="utf-8"))
    if (
        failure.get("decision") != "EXACT_REPRODUCTION_FAILED"
        or failure.get("exact_first_measurement_reproduced") is not False
    ):
        raise ValueError("replay divergence receipt changed")
    if audit.get("decision") != "DIVIDEND_PRICE_CONSISTENCY_FAILED":
        raise ValueError("dividend corpus no longer fails its price-consistency audit")

    original_leg = PRESERVED / "legs" / "leg_00"
    replay_leg = REPLAY / "legs" / "leg_00"
    orders_equal = pd.read_parquet(original_leg / "orders.parquet").equals(
        pd.read_parquet(replay_leg / "orders.parquet")
    )
    fills_equal = pd.read_parquet(original_leg / "fills.parquet").equals(
        pd.read_parquet(replay_leg / "fills.parquet")
    )
    if not orders_equal or not fills_equal:
        raise ValueError("leg-0 trading decisions changed before the corporate-action divergence")
    original_equity = pd.read_parquet(original_leg / "equity.parquet")
    replay_equity = pd.read_parquet(replay_leg / "equity.parquet")
    mismatch = original_equity["equity"] != replay_equity["equity"]
    first = int(mismatch.to_numpy().nonzero()[0][0])
    actions = _aggregate_replay_actions()
    first_ts = int(original_equity.iloc[first]["ts"])
    first_actions = actions[
        (actions["action_ts"] == first_ts) & (actions["cashflow_quote"] != 0.0)
    ]
    if len(first_actions) != 1:
        raise ValueError("first equity divergence no longer maps to exactly one cash action")
    first_action = first_actions.iloc[0]
    delta = float(replay_equity.iloc[first]["equity"] - original_equity.iloc[first]["equity"])
    if abs(delta - float(first_action["cashflow_quote"])) > 1e-9:
        raise ValueError("first equity divergence does not equal the first dividend cashflow")

    cash_actions = actions[actions["cashflow_quote"] != 0.0].copy()
    largest = cash_actions.loc[cash_actions["cashflow_quote"].abs().idxmax()]
    if (
        largest["instrument_id"] != "XUSE:CASH:CMCTUSD"
        or float(largest["cash_amount"]) != 112_500.0
        or float(largest["cashflow_quote"]) != 7_312_500.0
    ):
        raise ValueError("CMCT is no longer the replay's dominant malformed cash action")
    net_cash = float(cash_actions["cashflow_quote"].sum())
    gross_cash = float(cash_actions["cashflow_quote"].abs().sum())
    contribution = float(largest["cashflow_quote"] / net_cash)

    measured_at = dt.datetime.fromisoformat(FIRST_MEASURED_AT).astimezone(dt.UTC)
    engine_commit_at = _commit_time(DIVIDEND_ENGINE_COMMIT)
    if engine_commit_at <= measured_at:
        raise ValueError("tracked dividend-engine commit no longer postdates first measurement")

    payload: dict[str, Any] = {
        "schema": "canli.alphac-operating-margin-replay-root-cause.v1",
        "evidence_date": "2026-08-23",
        "author": "Arhan Canli",
        "hypothesis_key": IDENTITY,
        "run_name": RUN_NAME,
        "status": "ROOT_CAUSE_ESTABLISHED_REPLAY_REMAINS_INVALID",
        "decision": "CURRENT_REPLAY_CONTAMINATED_BY_UNVERIFIED_DIVIDEND_UNITS",
        "hypotheses_spent": 0,
        "causal_chain": [
            {
                "stage": "historical_measurement",
                "finding": (
                    "The immutable first measurement predates the first tracked engine commit "
                    "that applies cash dividends to equity holdings."
                ),
                "first_measured_at": measured_at.isoformat(),
                "dividend_engine_commit": DIVIDEND_ENGINE_COMMIT,
                "dividend_engine_committed_at": engine_commit_at.isoformat(),
            },
            {
                "stage": "first_divergence",
                "orders_byte_equal": orders_equal,
                "fills_byte_equal": fills_equal,
                "equity_timestamp": first_ts,
                "equity_delta": delta,
                "source_action": {
                    "instrument_id": str(first_action["instrument_id"]),
                    "action_type": str(first_action["action_type"]),
                    "position_qty_before": float(first_action["position_qty_before"]),
                    "cash_amount": float(first_action["cash_amount"]),
                    "cashflow_quote": float(first_action["cashflow_quote"]),
                },
                "finding": (
                    "Leg-0 decisions and fills are unchanged; the first equity mismatch equals "
                    "the first newly applied dividend cashflow exactly."
                ),
            },
            {
                "stage": "dominant_contamination",
                "replay_cash_action_rows": len(cash_actions),
                "replay_net_corporate_action_cashflow": net_cash,
                "replay_gross_corporate_action_cashflow": gross_cash,
                "dominant_row": {
                    "leg": str(largest["leg"]),
                    "action_ts": int(largest["action_ts"]),
                    "instrument_id": str(largest["instrument_id"]),
                    "position_qty_before": float(largest["position_qty_before"]),
                    "cash_amount": float(largest["cash_amount"]),
                    "cashflow_quote": float(largest["cashflow_quote"]),
                    "fraction_of_net_replay_cashflow": contribution,
                },
                "finding": (
                    "The vendor-originated CMCT value mints $7.3125m from 65 shares and dominates "
                    "the replay. It is not executable as a plain per-share cash dividend."
                ),
            },
            {
                "stage": "systemic_source_audit",
                "dividend_rows": audit["summary"]["dividend_rows"],
                "rows_above_full_pre_ex_close": audit["summary"][
                    "rows_above_full_pre_ex_close"
                ],
                "affected_instruments": audit["summary"]["affected_instruments"],
                "finding": (
                    "The malformed-unit/lifecycle class is systemic, so one-row imputation or "
                    "ticker-specific deletion would not resolve executable data quality."
                ),
            },
            {
                "stage": "engine_prevention",
                "finding": (
                    "The engine now fails closed when an exposed plain cash dividend exceeds the "
                    "observable pre-ex share value; it never guesses a scale or drops the row."
                ),
            },
        ],
        "evidence": {
            "replay_failure_path": str(failure_path.relative_to(REPO)),
            "replay_failure_sha256": _sha256(failure_path),
            "dividend_consistency_audit_path": str(DIVIDEND_AUDIT.relative_to(REPO)),
            "dividend_consistency_audit_sha256": _sha256(DIVIDEND_AUDIT),
            "dividend_consistency_content_hash": audit["content_hash"],
            "preserved_leg_0_orders_sha256": _sha256(original_leg / "orders.parquet"),
            "replay_leg_0_orders_sha256": _sha256(replay_leg / "orders.parquet"),
            "preserved_leg_0_fills_sha256": _sha256(original_leg / "fills.parquet"),
            "replay_leg_0_fills_sha256": _sha256(replay_leg / "fills.parquet"),
            "raw_actions_archive_sha256": _sha256(REPO / "data/sharadar_raw/ACTIONS.zip"),
            "engine_path": "src/alphaforge/backtest/engine.py",
            "engine_sha256": _sha256(REPO / "src/alphaforge/backtest/engine.py"),
        },
        "required_next_action": (
            "Quarantine every source row that fails the price-consistency boundary and resolve "
            "each affected family through independently documented vendor/lifecycle semantics. "
            "Do not rerun or promote this identity from the contaminated replay."
        ),
        "claim_boundary": (
            "This establishes why the attempted replay diverged and why its apparent positive "
            "performance is invalid. It does not validate the historical curve, create a new "
            "trial, admit a sleeve, or claim future performance."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build_finding()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(rendered, encoding="utf-8")
    for host in HOSTS:
        host.parent.mkdir(parents=True, exist_ok=True)
        host.write_text(rendered, encoding="utf-8")
    print(json.dumps({"status": payload["status"], "content_hash": payload["content_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
