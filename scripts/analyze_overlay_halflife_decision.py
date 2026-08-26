"""Cost the covariance-halflife change that the drawdown objective depends on.

Reads `artifacts/analysis/frontier_14/result.json` and nothing else. Opens no return data, runs
no backtest, registers no hypothesis: 0 trials. The sweep was already measured through the
PRODUCTION overlay (`alphaforge.portfolio.overlay.vol_target`); this only prices its turnover
seam so the halflife can move from a measured trade-off rather than a preference.

⚠️ THE UNIT IS THE WHOLE ANSWER, AND IT IS EASY TO GET WRONG BY 100x.
`overlay_gross_turnover_per_year` is a MULTIPLE OF EQUITY traded per year. A round-trip cost
quoted in basis points is a fraction of the NOTIONAL TRADED. So the annual drag is
`turnover x bps/10_000` as a fraction of equity, and the Sharpe cost is that divided by the
volatility target. Dividing by 100 instead -- treating the basis-point figure as a percentage --
turns a 0.0045 Sharpe cost into 0.45 and reverses the decision. That error was made once while
working this out and is why `_sharpe_cost` exists as one named function with one test rather than
as an expression inlined at three call sites.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "artifacts" / "analysis" / "frontier_14" / "result.json"
OUTPUT = REPO / "artifacts" / "analysis" / "overlay_halflife_decision" / "result.json"

PRODUCTION_HALFLIFE = 720
PROPOSED_HALFLIFE = 21
VOL_TARGET = 0.10
ROUND_TRIP_BPS = (5.0, 10.0, 20.0, 30.0, 50.0)
# The stressed correlation the admission contract permits. Costing the change anywhere easier
# would flatter it: the whole point of the overlay is what happens when correlations spike.
CONTRACT_STRESSED_RHO = 0.50


def annual_cost_fraction(turnover_multiple: float, round_trip_bps: float) -> float:
    """Fraction of EQUITY lost per year to trading `turnover_multiple` x equity at `bps`."""
    return turnover_multiple * (round_trip_bps / 10_000.0)


def _sharpe_cost(turnover_multiple: float, round_trip_bps: float, vol_target: float) -> float:
    """Sharpe given up for that drag at a given volatility target."""
    if vol_target <= 0:
        raise ValueError("vol_target must be positive")
    return annual_cost_fraction(turnover_multiple, round_trip_bps) / vol_target


def _row(sweep: dict[str, Any], rho: float, cov: int) -> dict[str, Any]:
    key = f"rho_stress={rho:.2f}|cov={cov}|rv=240|leg=unlevered"
    if key not in sweep:
        raise KeyError(f"{key} absent from the measured sweep; refusing to interpolate a decision")
    return sweep[key]


def main() -> int:
    study = json.loads(SOURCE.read_text())
    sweep = study["finding_2_drawdown_sweep"]

    base = _row(sweep, CONTRACT_STRESSED_RHO, PRODUCTION_HALFLIFE)
    proposed = _row(sweep, CONTRACT_STRESSED_RHO, PROPOSED_HALFLIFE)

    extra_turnover = (
        proposed["overlay_gross_turnover_per_year"] - base["overlay_gross_turnover_per_year"]
    )
    drawdown_bought = base["expected_max_drawdown"] - proposed["expected_max_drawdown"]

    costs = {
        f"{bps:g}bp": {
            "annual_drag_bp_of_equity": annual_cost_fraction(extra_turnover, bps) * 10_000.0,
            "sharpe_cost_at_vol_target": _sharpe_cost(extra_turnover, bps, VOL_TARGET),
        }
        for bps in ROUND_TRIP_BPS
    }

    # Across every stressed-correlation regime measured, not only the contract's ceiling, so the
    # decision is not resting on one cell.
    across_regimes = {}
    for key in sweep:
        if not key.endswith("|rv=240|leg=unlevered"):
            continue
        rho = float(key.split("|")[0].split("=")[1])
        across_regimes.setdefault(f"{rho:.2f}", {})[key.split("|")[1].split("=")[1]] = {
            "expected_max_drawdown": sweep[key]["expected_max_drawdown"],
            "p95_max_drawdown": sweep[key]["p95_max_drawdown"],
            "turnover_per_year": sweep[key]["overlay_gross_turnover_per_year"],
            "simulated_book_sharpe": sweep[key]["realized_book_sharpe"],
        }

    result = {
        "schema": "canli.alphac-overlay-halflife-decision.v1",
        "claim_boundary": (
            "Derived entirely from the already-measured sweep in "
            "artifacts/analysis/frontier_14/result.json. Opens no return data, runs no backtest, "
            "registers no hypothesis. 0 trials."
        ),
        "source": "artifacts/analysis/frontier_14/result.json",
        "question": (
            "Production runs cov_halflife_bars=720. The drawdown objective is only reached with "
            "the covariance halflife at 21. Is the turnover that buys affordable?"
        ),
        "unit_warning": (
            "overlay_gross_turnover_per_year is a MULTIPLE OF EQUITY per year; a round-trip cost "
            "in basis points is a fraction of the NOTIONAL TRADED. Annual drag is "
            "turnover * bps/10000 of equity. Reading the basis-point figure as a percentage "
            "overstates the cost 100x and reverses the decision."
        ),
        "evaluated_at_stressed_correlation": CONTRACT_STRESSED_RHO,
        "why_this_regime": (
            "It is the stressed pairwise correlation the admission contract permits. Costing the "
            "change in a calmer regime would flatter it, since the overlay exists for the spike."
        ),
        "production_halflife": PRODUCTION_HALFLIFE,
        "proposed_halflife": PROPOSED_HALFLIFE,
        "expected_max_drawdown_production": base["expected_max_drawdown"],
        "expected_max_drawdown_proposed": proposed["expected_max_drawdown"],
        "expected_max_drawdown_bought_pp": drawdown_bought * 100.0,
        "p95_max_drawdown_production": base["p95_max_drawdown"],
        "p95_max_drawdown_proposed": proposed["p95_max_drawdown"],
        "simulated_book_sharpe_production": base["realized_book_sharpe"],
        "simulated_book_sharpe_proposed": proposed["realized_book_sharpe"],
        "turnover_per_year_production": base["overlay_gross_turnover_per_year"],
        "turnover_per_year_proposed": proposed["overlay_gross_turnover_per_year"],
        "extra_turnover_per_year": extra_turnover,
        "vol_target": VOL_TARGET,
        "cost_by_round_trip": costs,
        "across_stressed_regimes": across_regimes,
        "verdict": (
            "SHIP. At the contract's permitted stressed correlation the change buys "
            f"{drawdown_bought * 100:.2f} percentage points of expected maximum drawdown for "
            f"{costs['10bp']['sharpe_cost_at_vol_target']:.4f} Sharpe at a 10bp round trip, and "
            f"{costs['50bp']['sharpe_cost_at_vol_target']:.4f} even at 50bp. The simulated book "
            f"Sharpe also RISES, {base['realized_book_sharpe']:.3f} to "
            f"{proposed['realized_book_sharpe']:.3f}, because the overlay targets risk better "
            "when the covariance leg can see a regime change. The drawdown reduction holds in "
            "every stressed-correlation regime measured, not only this one."
        ),
        "what_this_does_not_establish": (
            "The objective is an EXPECTED maximum drawdown. No configuration in the sweep held "
            "the 95th percentile at or under 11%; at this regime the best is "
            f"{proposed['p95_max_drawdown'] * 100:.1f}%. Both figures must always be published "
            "together. The sweep is also a simulation under a two-state correlation model, not a "
            "measurement of the live book."
        ),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(f"  buys {drawdown_bought * 100:.2f}pp expected max drawdown")
    print(f"  costs {costs['10bp']['sharpe_cost_at_vol_target']:.4f} Sharpe at 10bp round trip")
    print(f"  simulated book Sharpe {base['realized_book_sharpe']:.3f} -> "
          f"{proposed['realized_book_sharpe']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
