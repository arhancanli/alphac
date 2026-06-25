#!/usr/bin/env python3
"""Experiment #3 — maker / post-only execution EV SCREEN for the live crypto carry sleeve.

NON-INVASIVE. This does NOT touch the backtest engine, the fill model, or the golden master.
It answers ONE question before we spend the engineering + integrity cost of building a real
MakerFill model: *is maker-first execution worth it, and under what fill conditions?* — by
mapping the Sharpe uplift over the only two things we cannot yet observe (the realized
post-only FILL RATE and the ADVERSE-SELECTION penalty on the orders that don't fill).

Inputs are all real artifacts / committed code, nothing assumed about the strategy:
  - turnover_ann, vol_ann, sharpe  <- the live carry sleeve WF (artifacts/cpanel/L7_carry_cap_1M)
  - maker_bps / taker_bps          <- the COMMITTED fee schedule (BINANCE_VIP0_PERP)
  - half_spread_bps                <- the deployed cost config (CostsCfg.default_half_spread_bps)

Model (per one-way side):
  edge_if_filled = (taker_bps - maker_bps) + half_spread_bps      # save the fee delta + avoid
                                                                   # crossing the spread (taker pays it)
  A maker-FIRST order fills passively with prob p; the (1-p) that don't fill must CHASE at
  taker AND eat an adverse-selection penalty `a` (you only fail to fill when price ran away):
      E[saving_per_side] = p * edge_if_filled - (1 - p) * a        # vs the taker baseline
  annual_saving_frac = turnover_ann * E[saving_per_side] * 1e-4
  sharpe_uplift      = annual_saving_frac / vol_ann
  break-even fill    = a / (edge_if_filled + a)

The honest punchline the screen exists to deliver: at 33x annual turnover the lever is LARGE
(so it both helps a lot at good fills AND hurts at bad fills) — which means maker exec must be
shipped WITH live maker-fill-rate logging and conservative non-fill modeling, NEVER as an
assumed-fill advantage baked into a backtest (that manufactures fake alpha). The break-even
fill rate is the number to beat in the live paper logs before the engine work is justified.
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_CARRY_WF = Path(__file__).resolve().parent.parent / "artifacts" / "cpanel" / "L7_carry_cap_1M" / "walkforward.json"
_FILL_RATES = [0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
_ADV_SEL_BPS = [2.0, 4.0, 6.0, 8.0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="exp3_maker_exec_screen")
    ap.add_argument("--carry-wf", default=str(_CARRY_WF))
    a = ap.parse_args(argv)

    from alphaforge.config.settings import load_settings
    from alphaforge.core.time import now_ms
    from alphaforge.costs.fees import BINANCE_VIP0_PERP

    wf = json.loads(Path(a.carry_wf).read_text())["summary"]
    turnover_ann = float(wf["turnover_ann"])
    vol_ann = float(wf["vol_ann"])
    base_sharpe = float(wf["sharpe"])

    maker_bps = float(BINANCE_VIP0_PERP.maker_bps)
    taker_bps = float(BINANCE_VIP0_PERP.taker_bps)
    half_spread_bps = float(load_settings(None).costs.default_half_spread_bps)
    edge_if_filled = (taker_bps - maker_bps) + half_spread_bps  # bps saved per side when the post-only fills

    def uplift(p, adv):
        saving_bps = p * edge_if_filled - (1.0 - p) * adv
        sharpe_uplift = turnover_ann * saving_bps * 1e-4 / vol_ann
        return saving_bps, sharpe_uplift

    surface = []
    for adv in _ADV_SEL_BPS:
        row = {"adverse_selection_bps": adv, "breakeven_fill_rate": round(adv / (edge_if_filled + adv), 3), "by_fill_rate": {}}
        for p in _FILL_RATES:
            s_bps, up = uplift(p, adv)
            row["by_fill_rate"][f"{p:.1f}"] = {"saving_bps_per_side": round(s_bps, 2),
                                               "sharpe_uplift": round(up, 4),
                                               "new_sharpe": round(base_sharpe + up, 3)}
        surface.append(row)

    central_bps, central_up = uplift(0.6, 5.0)   # conservative central: 60% fill, 5bps adverse selection
    ceil_bps, ceil_up = uplift(1.0, 0.0)         # optimistic ceiling: every order fills, no chase

    now = now_ms()
    run_ts = datetime.fromtimestamp(now / 1000, UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path("artifacts/exp3") / run_ts
    out.mkdir(parents=True, exist_ok=True)
    metrics = {
        "run_ts": run_ts,
        "label": "MAKER-EXEC EV SCREEN — estimate conditional on (fill_rate, adverse_selection); NOT a backtest result. Gates whether the MakerFill engine work + golden re-bless is justified.",
        "inputs": {"sleeve": "live crypto carry (L7_carry_cap_1M)", "turnover_ann": round(turnover_ann, 2),
                   "vol_ann": round(vol_ann, 4), "base_sharpe": round(base_sharpe, 3),
                   "maker_bps": maker_bps, "taker_bps": taker_bps, "half_spread_bps": half_spread_bps,
                   "edge_if_filled_bps_per_side": round(edge_if_filled, 2)},
        "central_estimate_60pct_fill_5bps_advsel": {"saving_bps_per_side": round(central_bps, 2),
                                                    "sharpe_uplift": round(central_up, 4),
                                                    "new_sharpe": round(base_sharpe + central_up, 3)},
        "optimistic_ceiling_100pct_fill_0_advsel": {"saving_bps_per_side": round(ceil_bps, 2),
                                                    "sharpe_uplift": round(ceil_up, 4),
                                                    "new_sharpe": round(base_sharpe + ceil_up, 3)},
        "uplift_surface": surface,
        "decision_rule": "build the MakerFill engine + LOGGED golden re-bless ONLY with live maker-fill-rate logging in place; ship it iff the live paper post-only fill rate beats the break-even at the measured adverse selection. NEVER bake an assumed-fill advantage into a backtest.",
    }
    (out / "exp3_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps({"edge_if_filled_bps": edge_if_filled,
                      "central_60pct_5bps": metrics["central_estimate_60pct_fill_5bps_advsel"],
                      "ceiling_100pct": metrics["optimistic_ceiling_100pct_fill_0_advsel"],
                      "breakeven_fill_rates": {f"{r['adverse_selection_bps']}bps_advsel": r["breakeven_fill_rate"] for r in surface}},
                     indent=2))
    print(f"-> {out}/exp3_metrics.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
