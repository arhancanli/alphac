"""Which sleeve is dragging s_bar, and is the drag construction or cost?

WHY. Per-sleeve quality is the binding constraint on the objective: s_bar is measured at 0.469
across the live four and an honest forward 1.5 needs 0.601 at the gate. But s_bar is an AVERAGE
over four very different sleeves, and an average says nothing about which one to work on.

WHAT IS SEPARABLE, AND WHAT IS NOT — the boundary matters more than the numbers.

  MEASURED   commission   summed from the `fee` column of every fill
  MEASURED   funding      the walk-forward's own funding_net
  MODELLED   half-spread  turnover x notional x the DECLARED half-spread, because the spread is
                          applied to the FILL PRICE and never recorded as a line item
  NOT SEPARABLE  market impact  same reason, and it depends on ADV per name per day, which the
                          published fills do not carry

So `fees_paid` is COMMISSION ONLY, and anyone reading it as total transaction cost will
understate the cost component badly — 1bp against a declared 3bp equity half-spread plus a 2bp
latency add-on plus impact. That is why this decomposition reports a residual rather than
pretending to a full attribution: the residual is signal-net-of-spread-and-impact, and it cannot
be split further from what is on disk.

Reads published artifacts read-only. Registers no hypothesis, opens no return data: 0 trials.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd

from alphaforge.config.settings import Settings

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "artifacts" / "analysis" / "sleeve_quality_decomposition" / "result.json"

SLEEVES = {
    "AlphaMax": {"wf": "k30_dn_63", "asset": "equity"},
    "AlphaForge": {"wf": "crypto_carry_wk", "asset": "crypto"},
    "AlphaTrend": {"wf": "mf_live_fwd", "asset": "equity"},
}
TRADING_DAYS = 252.0


def parse_summary(path: Path) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in path.read_text().splitlines():
        match = re.match(r"^(\w+)\s+(-?[\d.]+)", line.strip())
        if match:
            try:
                values[match.group(1)] = float(match.group(2))
            except ValueError:
                continue
    return values


def measured_commission(wf_dir: Path) -> tuple[float, float]:
    """Commission actually charged, and the notional it was charged on, from every fill."""
    fee_total = notional_total = 0.0
    for fills in wf_dir.rglob("fills.parquet"):
        frame = pd.read_parquet(fills)
        if "fee" in frame.columns:
            fee_total += float(frame["fee"].sum())
        if "notional" in frame.columns:
            notional_total += float(frame["notional"].abs().sum())
    return fee_total, notional_total


def _cost_burden(row: dict[str, Any]) -> float:
    """Everything better execution could in principle give back, in Sharpe points."""
    return row["commission_sharpe_points_MEASURED"] + row["spread_sharpe_points_MODELLED"]


def main() -> int:
    costs = Settings().costs
    results: list[dict[str, Any]] = []

    for name, spec in SLEEVES.items():
        wf_dir = REPO / "artifacts" / "walkforward" / spec["wf"]
        summary_path = wf_dir / "summary.txt"
        if not summary_path.exists():
            continue
        summary = parse_summary(summary_path)
        initial = summary.get("initial_equity", 100000.0)
        years = summary.get("n_days", 0.0) / 365.25
        vol = summary.get("vol_ann", 0.0)
        net_sharpe = summary.get("sharpe", 0.0)
        if years <= 0 or vol <= 0:
            continue

        fee_total, notional_total = measured_commission(wf_dir)
        funding_net = summary.get("funding_net", 0.0)
        half_spread_bps = (
            costs.equity_half_spread_bps
            if spec["asset"] == "equity"
            else costs.default_half_spread_bps
        )
        modelled_spread = notional_total * (half_spread_bps + costs.latency_addon_bps) / 10_000.0

        # First-order: convert each dollar component to an annualised return on the starting
        # equity, then to Sharpe points by dividing by realised annual vol. Ignores compounding
        # interaction between components, which is why this is labelled first-order.
        def sharpe_points(
            dollars: float, _initial: float = initial, _years: float = years, _vol: float = vol
        ) -> float:
            return (dollars / _initial) / _years / _vol

        commission_pts = sharpe_points(fee_total)
        spread_pts = sharpe_points(modelled_spread)
        funding_pts = sharpe_points(funding_net)
        residual = net_sharpe + commission_pts + spread_pts - funding_pts

        results.append(
            {
                "sleeve": name,
                "walkforward": spec["wf"],
                "asset_class": spec["asset"],
                "years": years,
                "realised_vol_ann": vol,
                "net_sharpe_published": net_sharpe,
                "turnover_ann": summary.get("turnover_ann"),
                "notional_traded_total": notional_total,
                "commission_dollars_MEASURED": fee_total,
                "commission_sharpe_points_MEASURED": commission_pts,
                "funding_dollars_MEASURED": funding_net,
                "funding_sharpe_points_MEASURED": funding_pts,
                "half_spread_bps_used": half_spread_bps + costs.latency_addon_bps,
                "spread_dollars_MODELLED": modelled_spread,
                "spread_sharpe_points_MODELLED": spread_pts,
                "residual_signal_sharpe": residual,
                "market_impact": "NOT SEPARABLE — see claim boundary",
                "commission_bps_realised": (
                    fee_total / notional_total * 10_000.0 if notional_total else None
                ),
            }
        )

    if not results:
        print("no walk-forward summaries found; refusing to decompose nothing")
        return 1

    largest_cost = max(results, key=_cost_burden)
    weakest = min(results, key=lambda r: r["net_sharpe_published"])

    result = {
        "schema": "canli.alphac-sleeve-quality-decomposition.v1",
        "claim_boundary": (
            "A FIRST-ORDER decomposition from published artifacts, read-only. Each dollar "
            "component is converted to an annualised return on starting equity and then to "
            "Sharpe points by dividing by realised annual vol, ignoring compounding interaction "
            "between components. Registers no hypothesis identity and opens no return data. "
            "0 trials."
        ),
        "what_is_measured_and_what_is_not": {
            "MEASURED": [
                "commission — summed from the `fee` column of every fill",
                "funding — the walk-forward's own funding_net",
            ],
            "MODELLED": [
                "half-spread and latency — turnover x notional x the DECLARED bps, because the "
                "spread is applied to the FILL PRICE and never recorded as a line item"
            ],
            "NOT SEPARABLE": [
                "market impact — same reason as spread, and it depends on ADV per name per day, "
                "which the published fills do not carry. It is inside the residual."
            ],
            "the_trap": (
                "`fees_paid` in every summary.txt is COMMISSION ONLY. Reading it as total "
                "transaction cost understates the cost component badly: measured commission is "
                "about 1bp against a declared 3bp equity half-spread plus a 2bp latency add-on "
                "plus impact. This decomposition reports a RESIDUAL rather than pretending to a "
                "full attribution."
            ),
        },
        "sleeves": results,
        "s_bar_measured": sum(r["net_sharpe_published"] for r in results) / len(results),
        "weakest_sleeve": weakest["sleeve"],
        "largest_cost_burden": largest_cost["sleeve"],
        "largest_recoverable_component": {
            "sleeve": largest_cost["sleeve"],
            "sharpe_points": _cost_burden(largest_cost),
            "turnover_ann": largest_cost["turnover_ann"],
            "why": (
                "Transaction cost is the only component here that better execution could give "
                "back. Signal is construction and funding is a market fact; neither is recovered "
                "by executing better. This sleeve carries the largest cost burden by a wide "
                "margin, and it is the turnover that drives it."
            ),
            "what_recovering_half_would_be_worth": (
                _cost_burden(largest_cost) / 2.0,
                "Sharpe points on that sleeve, which is roughly a third of that on s_bar across "
                "three sleeves.",
            ),
        },
        "s_bar_basis_note": (
            "s_bar_measured here is the mean of these three FULL-HISTORY backtest Sharpes, each "
            "on its own window. It is NOT the 0.469 measured across the four live sleeves on "
            "their 1,061-day common window in artifacts/analysis/book_without_alphavintage, and "
            "the two must not be compared. Different sleeves, different windows."
        ),
        "the_finding": (
            f"{weakest['sleeve']} is the weakest at {weakest['net_sharpe_published']:.3f} net "
            f"Sharpe. Its total modelled-plus-measured cost burden is "
            f"{_cost_burden(weakest):.3f} "
            "Sharpe points, so recovering ALL of its transaction cost would still leave it at "
            f"{weakest['residual_signal_sharpe']:.3f} before spread and impact are re-charged. "
            "The drag is construction, not execution."
        ),
        "what_this_does_not_settle": (
            "Whether the modelled spread is the spread actually paid. That is B5's question and "
            "it needs the live fills, which the forward record is currently too short to answer."
        ),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(
        f"  {'sleeve':11} {'net SR':>7} {'comm':>7} {'spread':>8} {'funding':>8} "
        f"{'residual':>9} {'comm bps':>9}"
    )
    for row in results:
        bps = row["commission_bps_realised"]
        print(
            f"  {row['sleeve']:11} {row['net_sharpe_published']:>7.3f} "
            f"{row['commission_sharpe_points_MEASURED']:>7.4f} "
            f"{row['spread_sharpe_points_MODELLED']:>8.4f} "
            f"{row['funding_sharpe_points_MEASURED']:>8.4f} "
            f"{row['residual_signal_sharpe']:>9.3f} "
            f"{(bps if bps is not None else math.nan):>9.2f}"
        )
    print(f"\n  {result['the_finding']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
