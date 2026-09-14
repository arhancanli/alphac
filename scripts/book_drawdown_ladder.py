#!/usr/bin/env python3
"""Run the declared book-level drawdown ladder over the combined book's published daily marks.

WHY. `config/drawdown_control_contract.json` declares the brake that makes the owner's 11 percent
maximum-drawdown bound a mechanism (half gross at 5.5 percent, flat at 11 percent, absorbing
until an owner review), and `analyze_drawdown_control.py` measured it on simulated paths. This is
the live half: every publish, replay the combined book's daily equity marks (`live_curve` in
`data/paper/state.json`, the same series the forward record is built from) through the ladder
and write the multiplier in force.

The state is DERIVED, never stored: a fresh process recomputes the ladder from the whole marked
history every time, so there is no process-local state to lose (the 2026-09-05 crypto ladder
lesson) and the artifact is reproducible from public data. A halt is absorbing. It ends only
when the owner writes a dated entry into `config/book_ladder_rearms.json`; from the first mark on
or after that date the ladder restarts with the high-water mark reset to that mark, exactly as the
live class does on a manual rearm.

The replay is a scalar transcription of `DrawdownLadder.update` with the boot mark counted (so a
loss on the first day is a drawdown); `tests/unit/test_book_drawdown_ladder.py` asserts it equals
the vectorized twin `simulate_book_ladder` on the same series whenever no rearm intervenes.

Two outputs: the public artifact (`artifacts/engineering/book_drawdown_ladder.json`, published
to both hosts) and a small consumer file (`var/book_ladder/current.json`) that the trading cycles
read before sizing. Whether any cycle READS it is a live-configuration change recorded in
`config/live_change_contract.json`; this script only computes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
STATE_PATH = REPO / "data" / "paper" / "state.json"
CONTRACT_PATH = REPO / "config" / "drawdown_control_contract.json"
REARMS_PATH = REPO / "config" / "book_ladder_rearms.json"
ARTIFACT_PATH = REPO / "artifacts" / "engineering" / "book_drawdown_ladder.json"
CURRENT_PATH = REPO / "var" / "book_ladder" / "current.json"
SCHEMA = "canli.alphac-book-drawdown-ladder.v1"
AUTHOR = "Arhan Canli"

NORMAL = "NORMAL"
HALF_GROSS = "HALF_GROSS"
FLAT_HALTED = "FLAT_HALTED"
MULTIPLIER = {NORMAL: 1.0, HALF_GROSS: 0.5, FLAT_HALTED: 0.0}


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "content_hash"}
    return _sha256_bytes(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def ladder_from_curve(
    curve: list[dict[str, Any]],
    *,
    dd_half_frac: float,
    dd_flat_frac: float,
    release_frac: float,
    rearm_dates: list[str],
) -> dict[str, Any]:
    """Replay the daily marks through the absorbing ladder, restarting at each owner rearm.

    ``curve`` is the published list of ``{"date", "equity"}`` marks in date order. The first mark
    is the boot mark (multiplier 1, high-water mark = its equity). Each later mark first
    receives the multiplier in force at the previous close (that is what sizing applied to the
    day), then updates the ladder. A rearm dated D takes effect at the first mark on or after D
    that follows a halt: that mark becomes a fresh boot mark. A rearm that follows no halt is
    listed as unused, never applied.
    """
    if not 0.0 < dd_half_frac < dd_flat_frac < 1.0:
        raise ValueError("require 0 < dd_half_frac < dd_flat_frac < 1")
    if len(curve) < 1:
        raise ValueError("the live curve has no marks")
    dates = [str(row["date"]) for row in curve]
    equity = [float(row["equity"]) for row in curve]
    if any(not (e > 0.0) or e != e or e in (float("inf"),) for e in equity):
        raise ValueError("the live curve contains a non-positive or non-finite equity mark")
    if dates != sorted(dates) or len(set(dates)) != len(dates):
        raise ValueError("the live curve is not strictly date-ordered")
    release = release_frac * dd_half_frac
    pending = sorted(set(rearm_dates))

    hwm = equity[0]
    state = NORMAL
    halted_on: str | None = None
    halts: list[dict[str, Any]] = []
    rearms_applied: list[dict[str, str]] = []
    daily: list[dict[str, Any]] = []
    days_reduced = 0
    all_time_peak = equity[0]
    max_dd_all_time = 0.0

    for i in range(1, len(curve)):
        date, e = dates[i], equity[i]
        applied = MULTIPLIER[state]
        if applied < 1.0:
            days_reduced += 1
        all_time_peak = max(all_time_peak, e)
        max_dd_all_time = max(max_dd_all_time, 1.0 - e / all_time_peak)

        if state == FLAT_HALTED:
            # Absorbing: the high-water mark is frozen; only an owner rearm dated after the
            # halt and on or before this mark ends it, and this mark becomes the new boot mark.
            rearm = next(
                (d for d in pending if halted_on is not None and d > halted_on and d <= date), None
            )
            if rearm is not None:
                pending.remove(rearm)
                rearms_applied.append({"rearm_date": rearm, "boot_mark": date})
                halts[-1]["rearmed_on"] = date
                hwm = e
                state = NORMAL
                halted_on = None
            dd = 1.0 - e / hwm
        else:
            hwm = max(hwm, e)
            dd = 1.0 - e / hwm
            if dd >= dd_flat_frac:
                state = FLAT_HALTED
                halted_on = date
                halts.append({"halted_on": date, "equity_at_halt": e, "drawdown_at_halt": dd})
            elif state == NORMAL:
                if dd >= dd_half_frac:
                    state = HALF_GROSS
            elif dd < release:
                state = NORMAL
        daily.append(
            {
                "date": date,
                "multiplier_applied_to_this_day": applied,
                "state_after_close": state,
                "high_water_mark": hwm,
                "drawdown": dd,
            }
        )

    return {
        "as_of": dates[-1],
        "marks": len(curve),
        "state": state,
        "gross_multiplier": MULTIPLIER[state],
        "high_water_mark": hwm,
        "equity": equity[-1],
        "drawdown": 1.0 - equity[-1] / hwm,
        "max_drawdown_all_time_peak": max_dd_all_time,
        "days_at_reduced_gross": days_reduced,
        "halts": halts,
        "rearms_applied": rearms_applied,
        "rearms_unused": pending,
        "daily": daily,
    }


def build(
    *,
    state_path: Path = STATE_PATH,
    contract_path: Path = CONTRACT_PATH,
    rearms_path: Path = REARMS_PATH,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    state_bytes = state_path.read_bytes()
    state = json.loads(state_bytes)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    ladder = contract["ladder"]
    register = json.loads(rearms_path.read_text(encoding="utf-8")) if rearms_path.exists() else {}
    rearms = list(register.get("rearms", []))
    for row in rearms:
        dt.date.fromisoformat(str(row["rearm_date"]))  # a malformed register fails closed
    result = ladder_from_curve(
        state["live_curve"],
        dd_half_frac=float(ladder["dd_half_frac"]),
        dd_flat_frac=float(ladder["dd_flat_frac"]),
        release_frac=float(ladder["release_frac_of_half"]),
        rearm_dates=[str(r["rearm_date"]) for r in rearms],
    )
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "author": AUTHOR,
        "generated_at": (now or dt.datetime.now(dt.UTC)).isoformat(),
        "capital_kind": "PAPER_ONLY",
        "claim_boundary": (
            "The declared book-level drawdown ladder replayed over the combined book's published "
            "daily paper marks. It reports the multiplier the contract would have in force today. "
            "Whether any live cycle applies it is recorded in config/live_change_contract.json "
            "and config/drawdown_control_contract.json activation; a multiplier of 1.0 means the "
            "brake is not engaged, not that it is absent. A brake bounds each drawdown episode up "
            "to a one-day overshoot; it does not make losses impossible."
        ),
        "bindings": {
            "contract": {
                "path": _relative(contract_path),
                "sha256": _sha256_bytes(contract_path.read_bytes()),
                "status": contract.get("status"),
            },
            "live_curve_source": {
                "path": _relative(state_path),
                "sha256": _sha256_bytes(state_bytes),
                "generated_at": state.get("generated_at"),
            },
            "rearms_register": {"path": _relative(rearms_path), "entries": len(rearms)},
        },
        "ladder": {
            "dd_half_frac": float(ladder["dd_half_frac"]),
            "dd_flat_frac": float(ladder["dd_flat_frac"]),
            "release_frac_of_half": float(ladder["release_frac_of_half"]),
            "flat_state": "ABSORBING_UNTIL_OWNER_REARM",
        },
        "activation": contract.get("activation", {}),
        **result,
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def current_file(payload: dict[str, Any]) -> dict[str, Any]:
    """The small file the trading cycles read: only what sizing needs, bound to the artifact."""
    return {
        "schema": "canli.alphac-book-ladder-current.v1",
        "generated_at": payload["generated_at"],
        "as_of": payload["as_of"],
        "state": payload["state"],
        "gross_multiplier": payload["gross_multiplier"],
        "drawdown": payload["drawdown"],
        "artifact_content_hash": payload["content_hash"],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--artifact", type=Path, default=ARTIFACT_PATH)
    ap.add_argument("--current", type=Path, default=CURRENT_PATH)
    args = ap.parse_args(argv)
    payload = build()
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    args.artifact.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.current.parent.mkdir(parents=True, exist_ok=True)
    args.current.write_text(
        json.dumps(current_file(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"book ladder {payload['as_of']}: {payload['state']} x{payload['gross_multiplier']:.2f} "
        f"(drawdown {payload['drawdown']:.4f}, hwm {payload['high_water_mark']:.2f}, "
        f"{payload['marks']} marks, {len(payload['halts'])} halt(s))"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
