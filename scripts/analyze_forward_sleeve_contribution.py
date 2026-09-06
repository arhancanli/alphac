#!/usr/bin/env python3
"""Attribute the published forward book to its realized sleeve curves.

This is descriptive monitoring, not an estimator and not a weight optimizer. It uses
the append-only weight schedule that constructs the public ALPHAC curve and therefore
cannot silently substitute today's weights for historical allocations.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data/paper/state.json"
OUTPUT_PATH = ROOT / "artifacts/engineering/forward_sleeve_contribution.json"
STATE_KEYS = {
    "alphaforge": "crypto",
    "alphamax": "equity",
    "managed_futures": "managed_futures",
    "alphavintage": "macro_surprise",
}


def _load_paper_state_module() -> Any:
    path = ROOT / "scripts/paper_trading_state.py"
    spec = importlib.util.spec_from_file_location("paper_trading_state_for_attribution", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PAPER_STATE = _load_paper_state_module()
WEIGHT_SCHEDULE = _PAPER_STATE.WEIGHT_SCHEDULE
_daily_returns = _PAPER_STATE._daily_returns
_weights_on = _PAPER_STATE._weights_on


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def attribute(
    state: dict[str, Any], schedule: list[tuple[str, dict[str, float]]]
) -> dict[str, Any]:
    algorithms = {item["key"]: item for item in state["algorithms"]}
    missing = sorted(({"alphac"} | set(STATE_KEYS)) - set(algorithms))
    if missing:
        raise ValueError(f"published state is missing algorithms: {missing}")

    book_returns = _daily_returns(algorithms["alphac"]["live_curve"])
    sleeve_returns = {
        public_key: _daily_returns(algorithms[state_key]["live_curve"])
        for state_key, public_key in STATE_KEYS.items()
    }
    dates = sorted(book_returns)
    if len(dates) < 2:
        raise ValueError("at least two published flagship marks are required")

    schedule_keys = {
        "crypto": "crypto",
        "equity": "equity",
        "mf": "managed_futures",
        "vintage": "macro_surprise",
    }
    totals = dict.fromkeys(sleeve_returns, 0.0)
    daily: list[dict[str, Any]] = []
    residual_total = 0.0
    for date in dates[1:]:
        weights = _weights_on(date, schedule)
        contributions = {
            public_key: weights.get(schedule_key, 0.0)
            * sleeve_returns[public_key].get(date, 0.0)
            for schedule_key, public_key in schedule_keys.items()
        }
        for key, value in contributions.items():
            totals[key] += value
        residual = book_returns[date] - sum(contributions.values())
        residual_total += residual
        daily.append(
            {
                "date": date,
                "book_return": book_returns[date],
                "sleeve_contributions": contributions,
                "strategic_overlay_and_rounding_residual": residual,
            }
        )

    book_additive = sum(row["book_return"] for row in daily)
    largest_loss_driver = min(totals, key=totals.get)
    loss_share = (
        abs(totals[largest_loss_driver]) / abs(book_additive) if book_additive < 0 else None
    )
    return {
        "record": {
            "first_mark": dates[0],
            "last_mark": dates[-1],
            "daily_return_observations": len(daily),
            "book_additive_return": book_additive,
        },
        "sleeve_additive_contributions": totals,
        "strategic_overlay_and_rounding_residual": residual_total,
        "largest_loss_driver": {
            "sleeve": largest_loss_driver,
            "additive_contribution": totals[largest_loss_driver],
            "absolute_share_of_negative_book_return": loss_share,
            "dominates_current_loss": bool(loss_share is not None and loss_share >= 0.5),
        },
        "daily": daily,
    }


def build_document(state: dict[str, Any], state_bytes: bytes) -> dict[str, Any]:
    result = attribute(state, WEIGHT_SCHEDULE)
    document: dict[str, Any] = {
        "schema": "canli.alphac-forward-sleeve-contribution.v1",
        "author": "Arhan Canli",
        "claim_boundary": (
            "Descriptive arithmetic attribution of the published paper curve only. It is not a "
            "Sharpe estimate, evidence of expected sleeve performance, permission to reweight, "
            "or a return trial. The strategic-overlay residual is not alpha."
        ),
        "decision": "MONITOR_ONLY_NO_WEIGHT_CHANGE",
        "source_bindings": {
            "paper_state": {
                "path": "data/paper/state.json",
                "sha256": _sha256(state_bytes),
            },
            "committed_weight_schedule": {
                "path": "scripts/paper_trading_state.py",
                "schedule": WEIGHT_SCHEDULE,
            },
        },
        **result,
    }
    document["content_hash"] = f"sha256:{_sha256(_canonical(document))}"
    return document


def main() -> None:
    state_bytes = STATE_PATH.read_bytes()
    state = json.loads(state_bytes)
    document = build_document(state, state_bytes)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
