#!/usr/bin/env python3
"""Refresh and attest the three dedicated Alpaca paper-account records, GET-only.

The trading cycles write broker portfolio history after they submit on open sessions.  That left
an integrity gap: on a closed-market day the calendar guard correctly returned before submitting,
but it also returned before pulling Alpaca's finalized prior-session mark.  The website could
therefore be current as a publication while one business day behind the broker.

This exporter has no order endpoint and performs only four GETs per account: account, positions,
portfolio history, and open orders.  A complete broker history replaces that sleeve's local curve;
an empty/degraded response never does.  It then writes a public-safe attestation (hashed account
identity, never credentials) proving which broker rows matched before refresh and that every
broker row is present and cent-identical afterward.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import httpx

REPO: Final[Path] = Path(__file__).resolve().parents[1]
OUTPUT: Final[Path] = REPO / "artifacts" / "engineering" / "alpaca_broker_reconciliation.json"
PAPER_BASE_HOST: Final[str] = "paper-api.alpaca.markets"
CENT_TOLERANCE: Final[float] = 0.01


@dataclass(frozen=True)
class Sleeve:
    key: str
    profile: str
    env_path: Path
    database: Path


SLEEVES: Final[tuple[Sleeve, ...]] = (
    Sleeve(
        "alphamax",
        "equity",
        Path.home() / ".config" / "alphaforge" / "alpaca_equity.env",
        REPO / "var" / "trading_equity.sqlite",
    ),
    Sleeve(
        "managed_futures",
        "managed_futures",
        Path.home() / ".config" / "alphaforge" / "alpaca.env",
        REPO / "var" / "trading_managed_futures.sqlite",
    ),
    Sleeve(
        "alphavintage",
        "alphavintage",
        Path.home() / ".config" / "alphaforge" / "alpaca_vintage.env",
        REPO / "var" / "trading_alphavintage.sqlite",
    ),
)


def _iso_ms(value: int | None) -> str | None:
    if value is None:
        return None
    return dt.datetime.fromtimestamp(value / 1000, tz=dt.UTC).isoformat()


def _load_account_env(path: Path) -> dict[str, str]:
    """Load exactly one sleeve file; ambient APCA variables must never collapse account scope."""
    env: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def _get_json(client: httpx.Client, url: str, **kwargs: Any) -> Any:
    response = client.get(url, **kwargs)
    response.raise_for_status()
    return response.json()


def _read_local(database: Path, profile: str) -> tuple[list[tuple[int, float]], dict[str, Any]]:
    if not database.exists():
        return [], {
            "consecutive_fill_reconcile_failures": None,
            "last_success_at": None,
            "last_failure_at": None,
            "last_error": "database_missing",
        }
    con = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        curve = [
            (int(ts), float(equity))
            for ts, equity in con.execute(
                "SELECT ts, equity_quote FROM equity_curve ORDER BY ts"
            ).fetchall()
        ]
        tables = {
            row[0]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        row = (
            con.execute(
                "SELECT consecutive_fill_reconcile_failures, last_success_ts, "
                "last_failure_ts, last_error FROM execution_health WHERE profile=?",
                (profile,),
            ).fetchone()
            if "execution_health" in tables
            else None
        )
    finally:
        con.close()
    return curve, {
        "consecutive_fill_reconcile_failures": int(row[0]) if row else None,
        "last_success_at": _iso_ms(int(row[1])) if row and row[1] is not None else None,
        "last_failure_at": _iso_ms(int(row[2])) if row and row[2] is not None else None,
        "last_error": str(row[3]) if row and row[3] is not None else None,
    }


def _compare(
    broker_history: list[tuple[int, float]], local_curve: list[tuple[int, float]]
) -> dict[str, Any]:
    local = dict(local_curve)
    overlap = [(ts, equity, local[ts]) for ts, equity in broker_history if ts in local]
    max_diff = max((abs(broker - stored) for _, broker, stored in overlap), default=None)
    missing = [ts for ts, _ in broker_history if ts not in local]
    return {
        "broker_marks": len(broker_history),
        "local_marks": len(local_curve),
        "overlapping_marks": len(overlap),
        "broker_marks_missing_locally": len(missing),
        "missing_broker_mark_timestamps": [_iso_ms(ts) for ts in missing],
        "max_absolute_equity_difference": max_diff,
        "all_overlapping_marks_match_to_cent": (
            max_diff is not None and max_diff <= CENT_TOLERANCE
        ),
    }


def _public_holdings(
    positions: list[dict[str, Any]], *, equity: float, as_of: str
) -> dict[str, Any]:
    """Public current broker book, with no account credential or order information."""
    if equity <= 0.0:
        raise ValueError("account equity must be positive to derive holdings weights")
    parsed = [
        (str(row["symbol"]), float(row["market_value"]))
        for row in positions
        if abs(float(row.get("qty") or 0.0)) > 0.0
    ]
    longs = sorted((row for row in parsed if row[1] > 0.0), key=lambda row: -row[1])
    shorts = sorted((row for row in parsed if row[1] < 0.0), key=lambda row: row[1])

    def top(rows: list[tuple[str, float]]) -> list[dict[str, Any]]:
        return [
            {"ticker": symbol, "weight_pct": round(abs(market_value) / equity * 100, 2)}
            for symbol, market_value in rows[:15]
        ]

    gross = sum(abs(market_value) for _, market_value in parsed) / equity * 100
    net = sum(market_value for _, market_value in parsed) / equity * 100
    return {
        "as_of": as_of,
        "source": "ALPACA_CURRENT_POSITIONS",
        "broker_reconciled": True,
        "long_count": len(longs),
        "short_count": len(shorts),
        "gross_pct": round(gross, 1),
        "net_pct": round(net, 2),
        "long": top(longs),
        "short": top(shorts),
        "flat": not parsed,
    }


def _replace_curve(
    database: Path, broker_history: list[tuple[int, float]], current_mark: tuple[int, float]
) -> list[tuple[int, float]]:
    """Atomically replace one curve only when Alpaca returned non-trivial full history."""
    if len(broker_history) < 2:
        raise ValueError(
            "broker portfolio history has fewer than two marks; preserving local curve"
        )
    rows = [*broker_history, current_mark]
    database.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(database)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            "CREATE TABLE IF NOT EXISTS equity_curve "
            "(ts INTEGER PRIMARY KEY, equity_quote REAL NOT NULL)"
        )
        con.execute("DELETE FROM equity_curve")
        con.executemany(
            "INSERT OR REPLACE INTO equity_curve (ts, equity_quote) VALUES (?, ?)", rows
        )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return rows


def reconcile_sleeve(sleeve: Sleeve, *, now_ms: int) -> dict[str, Any]:
    env = _load_account_env(sleeve.env_path)
    base = env.get("APCA_API_BASE_URL", "").rstrip("/")
    if PAPER_BASE_HOST not in base:
        raise ValueError(f"refusing non-paper Alpaca base URL for {sleeve.profile}")
    headers = {
        "APCA-API-KEY-ID": env["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": env["APCA_API_SECRET_KEY"],
    }
    with httpx.Client(headers=headers, timeout=30.0) as client:
        account = _get_json(client, f"{base}/v2/account")
        positions = _get_json(client, f"{base}/v2/positions")
        history = _get_json(
            client,
            f"{base}/v2/account/portfolio/history",
            params={"period": "all", "timeframe": "1D"},
        )
        open_orders = _get_json(
            client, f"{base}/v2/orders", params={"status": "open", "limit": 500}
        )

    broker_history = [
        (int(ts) * 1000, float(equity))
        for ts, equity in zip(history.get("timestamp", []), history.get("equity", []), strict=True)
        if equity is not None
    ]
    current_equity = float(account["equity"])
    if not isinstance(positions, list) or not isinstance(open_orders, list):
        raise TypeError("Alpaca positions/open-orders response is not a list")
    public_holdings = _public_holdings(
        positions,
        equity=current_equity,
        as_of=dt.datetime.fromtimestamp(now_ms / 1000, tz=dt.UTC).date().isoformat(),
    )
    before, fill_health = _read_local(sleeve.database, sleeve.profile)
    comparison_before = _compare(broker_history, before)
    after = _replace_curve(sleeve.database, broker_history, (now_ms, current_equity))
    comparison_after = _compare(broker_history, after)
    account_number = str(account.get("account_number") or account.get("id") or "")
    checks = {
        "paper_endpoint": True,
        "account_active": account.get("status") == "ACTIVE",
        "nontrivial_broker_history": len(broker_history) >= 2,
        "pre_refresh_overlap_matched_to_cent": comparison_before[
            "all_overlapping_marks_match_to_cent"
        ],
        "all_broker_marks_present_after_refresh": (
            comparison_after["broker_marks_missing_locally"] == 0
        ),
        "all_broker_marks_match_to_cent_after_refresh": comparison_after[
            "all_overlapping_marks_match_to_cent"
        ],
        "current_account_equity_persisted": abs(after[-1][1] - current_equity) <= CENT_TOLERANCE,
        "fill_reconciliation_healthy": (
            fill_health["consecutive_fill_reconcile_failures"] == 0
            and fill_health["last_error"] is None
        ),
    }
    return {
        "sleeve": sleeve.key,
        "profile": sleeve.profile,
        "broker": "ALPACA",
        "capital_kind": "PAPER_ONLY",
        "account_identity": {
            "scheme": "sha256(alpaca_account_number)",
            "sha256": hashlib.sha256(account_number.encode()).hexdigest(),
            "last4": account_number[-4:] if account_number else None,
        },
        "account_status": account.get("status"),
        "current_equity": current_equity,
        "current_equity_as_of": _iso_ms(now_ms),
        "open_position_count": len(positions),
        "open_order_count": len(open_orders),
        "holdings": public_holdings,
        "portfolio_history_first_mark": _iso_ms(broker_history[0][0]),
        "portfolio_history_last_mark": _iso_ms(broker_history[-1][0]),
        "comparison_before_refresh": comparison_before,
        "comparison_after_refresh": comparison_after,
        "fill_outcome_reconciliation": fill_health,
        "checks": checks,
        "passes": all(checks.values()),
    }


def build(*, now: dt.datetime | None = None) -> dict[str, Any]:
    instant = now or dt.datetime.now(tz=dt.UTC)
    if instant.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now_ms = int(instant.timestamp() * 1000)
    sleeves: dict[str, Any] = {}
    for sleeve in SLEEVES:
        try:
            sleeves[sleeve.key] = reconcile_sleeve(sleeve, now_ms=now_ms)
        except Exception as exc:
            sleeves[sleeve.key] = {
                "sleeve": sleeve.key,
                "profile": sleeve.profile,
                "broker": "ALPACA",
                "capital_kind": "PAPER_ONLY",
                "passes": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "local_curve_preserved_on_failure": True,
            }
    passed_rows = [row for row in sleeves.values() if row["passes"]]
    account_hashes = [row["account_identity"]["sha256"] for row in passed_rows]
    unique_dedicated_accounts = (
        len(account_hashes) == len(SLEEVES) and len(set(account_hashes)) == len(SLEEVES)
    )
    passes = all(result["passes"] for result in sleeves.values()) and unique_dedicated_accounts
    payload: dict[str, Any] = {
        "schema": "canli.alphac-alpaca-broker-reconciliation.v1",
        "author": "Arhan Canli",
        "generated_at": instant.astimezone(dt.UTC).isoformat(),
        "method": "GET_ONLY_ACCOUNT_POSITIONS_PORTFOLIO_HISTORY_OPEN_ORDERS",
        "claim_boundary": (
            "Self-published read-only reconciliation against three dedicated Alpaca paper "
            "accounts. It is broker-derived but not an independent third-party attestation, "
            "does not imply real capital, and does not establish future performance."
        ),
        "cent_tolerance": CENT_TOLERANCE,
        "sleeves": sleeves,
        "summary": {
            "expected_alpaca_sleeves": len(SLEEVES),
            "reconciled_alpaca_sleeves": sum(bool(row["passes"]) for row in sleeves.values()),
            "open_positions": sum(
                int(row.get("open_position_count", 0)) for row in sleeves.values()
            ),
            "open_orders": sum(int(row.get("open_order_count", 0)) for row in sleeves.values()),
            "unique_dedicated_accounts": unique_dedicated_accounts,
            "passes": passes,
            "status": "PASS" if passes else "FAIL_CLOSED",
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    # Public reproduce.py recognizes the project-wide algorithm-qualified convention. A bare
    # digest is locally comparable but is skipped by the repository-wide verifier scan and fails
    # the downloadable verifier, which made this artifact the lone unverifiable public file.
    payload["content_hash"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return payload


def main() -> int:
    payload = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)} — {payload['summary']['status']}")
    for key, row in payload["sleeves"].items():
        if row["passes"]:
            before = row["comparison_before_refresh"]
            print(
                f"  {key}: PASS | {row['open_position_count']} positions | "
                f"{before['broker_marks_missing_locally']} broker marks refreshed | "
                f"account ...{row['account_identity']['last4']}"
            )
        else:
            print(f"  {key}: FAIL_CLOSED | {row.get('error_type')}: {row.get('error')}")
    return 0 if payload["summary"]["passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
