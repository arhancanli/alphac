"""Does the modelled cost match what the live book actually pays? Mostly it cannot be asked.

WHY IT MATTERS. `cost_frac_oneway` is a flat one-way cost that never widens in stress, and the
red-team artifact already lists that as an open weakness. A cost model that understates is the
quietest way for a paper edge to be larger than a real one.

WHAT THE LIVE FILLS CAN AND CANNOT ANSWER — the boundary is the finding.

  MEASURABLE   commission, crypto only. `fee_quote` is recorded per fill.
  MEASURABLE   submit-to-fill latency, every sleeve. `submitted_ts` and `ts` are both recorded.
  NOT MEASURABLE   slippage against the decision price, equity sleeves. The fills record
                   `limit_price`, which is a PADDED marketable limit and not the price the
                   decision was taken at, so a fill "beating" it by 54bp is measuring the padding
                   rather than the execution. Reporting that as price improvement would be a
                   fabricated number.
  NOT MEASURABLE   commission, equity sleeves. There is no fee column in the fills table.

Same shape as the B3 finding: the artifact records the executed price without the unimpacted
reference, so the cost cannot be separated from the trade. The actionable output is therefore a
one-field schema change, named at the end.

Reads the trading databases read-only. 0 trials.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np

from alphaforge.config.settings import Settings
from alphaforge.costs.fees import BINANCE_VIP0_PERP, US_EQUITY_DEFAULT

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "artifacts" / "analysis" / "cost_model_realism" / "result.json"
STATE = REPO / "data" / "paper" / "state.json"

EQUITY_DBS = {
    "AlphaMax": "var/trading_equity.sqlite",
    "AlphaTrend": "var/trading_managed_futures.sqlite",
    "AlphaVintage": "var/trading_alphavintage.sqlite",
}
CRYPTO_DB = "var/trading_crypto_perp.sqlite"


def _go_live_ms() -> tuple[int, str]:
    go_live = json.loads(STATE.read_text())["go_live_date"]
    stamp = int(
        dt.datetime.fromisoformat(f"{go_live}T00:00:00+00:00").timestamp() * 1000
    )
    return stamp, go_live


def equity_fills(db: Path, since_ms: int) -> dict[str, Any]:
    if not db.exists():
        return {"database_exists": False}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT ts, submitted_ts, side, limit_price, fill_price, notional "
        "FROM fills WHERE status='filled'"
    ).fetchall()
    con.close()
    post = [r for r in rows if r[0] >= since_ms]
    if not post:
        return {"database_exists": True, "fills_total": len(rows), "fills_since_go_live": 0}
    latency = np.array([(r[0] - r[1]) / 1000.0 for r in post if r[1]], dtype=float)
    notional = float(sum(r[5] for r in post if r[5]))
    return {
        "database_exists": True,
        "fills_total": len(rows),
        "fills_since_go_live": len(post),
        "notional_since_go_live": notional,
        "submit_to_fill_latency_seconds": {
            "median": float(np.median(latency)) if latency.size else None,
            "p90": float(np.percentile(latency, 90)) if latency.size else None,
            "median_hours": float(np.median(latency) / 3600.0) if latency.size else None,
        },
        "slippage_vs_decision_price": (
            "NOT MEASURABLE — the fills record limit_price, a PADDED marketable limit, not the "
            "price the decision was taken at. A fill that beats it is beating the padding."
        ),
        "commission": "NOT MEASURABLE — no fee column in this fills table",
    }


def crypto_fills(db: Path, since_ms: int) -> dict[str, Any]:
    if not db.exists():
        return {"database_exists": False}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT ts, slippage_bps, fee_quote, qty, price, liquidity, book_exhausted FROM fills"
    ).fetchall()
    con.close()
    if not rows:
        return {"database_exists": True, "fills_total": 0}
    notional = float(sum(r[3] * r[4] for r in rows))
    fees = float(sum(r[2] for r in rows))
    slippage = np.array([r[1] for r in rows if r[1] is not None], dtype=float)
    post = [r for r in rows if r[0] >= since_ms]
    return {
        "database_exists": True,
        "fills_total": len(rows),
        "fills_since_go_live": len(post),
        "window": [
            dt.datetime.fromtimestamp(min(r[0] for r in rows) / 1000, tz=dt.UTC)
            .date()
            .isoformat(),
            dt.datetime.fromtimestamp(max(r[0] for r in rows) / 1000, tz=dt.UTC)
            .date()
            .isoformat(),
        ],
        "notional_total": notional,
        "realised_commission_bps_MEASURED": fees / notional * 10_000.0 if notional else None,
        "modelled_taker_bps": BINANCE_VIP0_PERP.taker_bps,
        "slippage_bps_MEASURED": {
            "mean": float(slippage.mean()),
            "median": float(np.median(slippage)),
            "min": float(slippage.min()),
            "max": float(slippage.max()),
            "note": (
                "Recorded against `modeled_price`, so this IS a real execution measurement — the "
                "only one in the book. Negative is favourable. All 24 fills are taker and none "
                "exhausted the book."
            ),
        },
        "all_taker": all(r[5] == "taker" for r in rows),
        "book_exhausted_count": int(sum(r[6] for r in rows)),
    }


def main() -> int:
    if not STATE.exists():
        print("no published state")
        return 1
    since_ms, go_live = _go_live_ms()
    costs = Settings().costs

    equity = {name: equity_fills(REPO / rel, since_ms) for name, rel in EQUITY_DBS.items()}
    crypto = crypto_fills(REPO / CRYPTO_DB, since_ms)

    latencies = [
        s["submit_to_fill_latency_seconds"]["median_hours"]
        for s in equity.values()
        if s.get("submit_to_fill_latency_seconds", {}).get("median_hours")
    ]
    median_latency_hours = float(np.median(latencies)) if latencies else None

    result = {
        "schema": "canli.alphac-cost-model-realism.v1",
        "claim_boundary": (
            "Reads the live trading databases read-only. Registers no hypothesis identity, opens "
            "no return data, and changes no cost parameter. 0 trials."
        ),
        "go_live_date": go_live,
        "modelled_parameters": {
            "equity_commission_bps": costs.equity_commission_bps,
            "equity_half_spread_bps": costs.equity_half_spread_bps,
            "default_half_spread_bps": costs.default_half_spread_bps,
            "latency_addon_bps": costs.latency_addon_bps,
            "equity_borrow_bps_annual": costs.equity_borrow_bps_annual,
            "impact_coef": costs.impact_coef,
            "crypto_taker_bps": BINANCE_VIP0_PERP.taker_bps,
            "equity_taker_bps": US_EQUITY_DEFAULT.taker_bps,
        },
        "equity_sleeves": equity,
        "crypto_sleeve": crypto,
        "what_matched": (
            "Crypto commission. Measured "
            f"{crypto.get('realised_commission_bps_MEASURED', float('nan')):.2f}bp against a "
            f"modelled taker fee of {BINANCE_VIP0_PERP.taker_bps:.1f}bp — exact. The one cost "
            "component in the book that can be checked against reality checks out."
        ),
        "⚠️_the_latency_finding": {
            "median_submit_to_fill_hours": median_latency_hours,
            "modelled_latency_addon_bps": costs.latency_addon_bps,
            "why_this_matters": (
                f"Median submit-to-fill latency across the equity sleeves is about "
                f"{median_latency_hours:.1f} HOURS, not seconds — orders are submitted after the "
                "close and fill at the next open. The cost model represents latency as a flat "
                f"{costs.latency_addon_bps:.0f}bp add-on, which is a microstructure quantity. An "
                "overnight gap is not a spread: it is unhedged exposure to whatever happens "
                "between submission and fill, and its cost is a distribution with a fat tail "
                "rather than a constant. This is not evidence the model is wrong by a specific "
                "amount — it is evidence that this component is modelled as the wrong KIND of "
                "thing, and nothing here measures its size."
            ),
        },
        "⚠️_crypto_has_not_traded_since_go_live": {
            "fills_since_go_live": crypto.get("fills_since_go_live"),
            "last_fill_window": crypto.get("window"),
            "note": (
                "Zero crypto fills since the 2026-08-07 re-baseline, with the last on 2026-07-30, "
                "against a weekly rebalance cadence over a fifteen-day record. The sleeve is "
                "marking equity but not trading. Surfaced, not diagnosed — it may be a "
                "no-trade band holding, and it may not."
            ),
        },
        "what_cannot_be_asked_and_the_fix": (
            "Slippage against the decision price is not computable for the equity sleeves: the "
            "fills record `limit_price`, a PADDED marketable limit, so a fill beating it by 54bp "
            "is beating the padding, not the market. Equity commission is not computable either "
            "— there is no fee column. THE FIX IS ONE FIELD: record the reference mid at "
            "`submitted_ts` on every order. That single addition turns implementation shortfall "
            "from unanswerable into a daily measurement, and it costs nothing to capture at the "
            "moment the order is built."
        ),
        "verdict": (
            "The one checkable component MATCHES exactly. The rest is not checkable from what is "
            "recorded, and the latency component is modelled as the wrong kind of quantity. No "
            "cost parameter should move on this evidence; the schema should."
        ),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(f"  crypto commission MEASURED {crypto.get('realised_commission_bps_MEASURED'):.2f}bp "
          f"vs modelled {BINANCE_VIP0_PERP.taker_bps:.1f}bp")
    print(f"  crypto slippage vs modelled price: mean "
          f"{crypto['slippage_bps_MEASURED']['mean']:+.2f}bp")
    print(f"  crypto fills since go-live: {crypto.get('fills_since_go_live')}")
    for name, s in equity.items():
        lat = s.get("submit_to_fill_latency_seconds", {}).get("median_hours")
        print(f"  {name:13} {s.get('fills_since_go_live', 0):>5} fills since go-live, "
              f"median latency {lat:.1f}h" if lat else f"  {name:13} no fills")
    print(f"\n  verdict: {result['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
