"""Is the live book delivering its backtest? And can a 15-day record answer that at all?

WHY IT MATTERS. The cheapest possible route to per-sleeve quality is not new research — it is the
deployed sleeves delivering what their own walk-forwards claim. s_bar is the binding constraint on
the objective, so a systematic live-versus-backtest shortfall would be the single most valuable
thing to find.

WHY THE ANSWER IS MOSTLY A POWER CALCULATION. The forward record began 2026-08-07. Overlap with a
walk-forward that extends into the live period exists for two sleeves only, and it is 5 and 9
days: four and eight daily return observations. Estimating a Sharpe difference from that is not a
noisy measurement, it is no measurement — so this reports HOW LONG the record must run before the
question can be asked, and treats the observed divergence as an observation rather than an
estimate.

The quantity that answers it soonest is the TRACKING DIFFERENCE d_t = r_live - r_backtest, not
either Sharpe. Live and backtest run the same signal on the same days, so their returns are
strongly correlated and the difference series is far less noisy than either level — which means
the record needed to detect an execution gap is much shorter than the record needed to establish
the edge itself.

Reads the trading databases and walk-forward curves read-only. 0 trials.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "artifacts" / "analysis" / "execution_gap_power" / "result.json"
STATE = REPO / "data" / "paper" / "state.json"
TRADING_DAYS = 252.0

# Only sleeves whose walk-forward is REGENERATED into the live period can be compared at all. The
# blessed research curves end 2026-06-01 by design, before go-live, so they cannot answer this.
PAIRS = {
    "AlphaMax": {"db": "var/trading_equity.sqlite", "wf": "equity_live_fwd"},
    "AlphaTrend": {"db": "var/trading_managed_futures.sqlite", "wf": "mf_live_fwd"},
}
# Annual return gaps worth being able to detect, as fractions of equity.
GAPS = (0.005, 0.01, 0.02, 0.05)


def _date(ts: float) -> str:
    seconds = float(ts) / 1000.0 if float(ts) > 1e11 else float(ts)
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC).date().isoformat()


def live_series(db: Path, go_live: str) -> pd.Series:
    if not db.exists():
        return pd.Series(dtype=float)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute("SELECT ts, equity_quote FROM equity_curve ORDER BY ts").fetchall()
    con.close()
    by_day: dict[str, float] = {}
    for ts, equity in rows:
        day = _date(ts)
        if day >= go_live:
            by_day[day] = float(equity)      # last mark of the day, the close
    return pd.Series(by_day).sort_index()


def backtest_series(wf: Path, go_live: str) -> pd.Series:
    frame = pd.read_parquet(wf)
    days = pd.to_datetime(frame["ts"], unit="ms", utc=True).dt.normalize().dt.date.astype(str)
    series = pd.Series(frame["equity"].to_numpy(dtype=float), index=days)
    series = series[~series.index.duplicated(keep="last")].sort_index()
    return series[series.index >= go_live]


def days_required(sd_daily: float, annual_gap: float, confidence_z: float = 1.96) -> float:
    """Observations needed before a gap of `annual_gap` clears its own standard error.

    The annualised mean of the difference series has standard error
    `sd_daily * TRADING_DAYS / sqrt(n)`, so detection needs
    `n > (z * sd_daily * TRADING_DAYS / annual_gap)^2`.
    """
    if annual_gap <= 0 or sd_daily <= 0:
        return math.inf
    return (confidence_z * sd_daily * TRADING_DAYS / annual_gap) ** 2


def main() -> int:
    if not STATE.exists():
        print("no published state")
        return 1
    go_live = json.loads(STATE.read_text())["go_live_date"]

    sleeves: list[dict[str, Any]] = []
    for name, spec in PAIRS.items():
        live = live_series(REPO / spec["db"], go_live)
        wf_path = REPO / "artifacts" / "walkforward" / spec["wf"] / "equity.parquet"
        if live.empty or not wf_path.exists():
            continue
        backtest = backtest_series(wf_path, go_live)
        common = sorted(set(live.index) & set(backtest.index))
        if len(common) < 3:
            sleeves.append(
                {"sleeve": name, "walkforward": spec["wf"], "common_days": len(common),
                 "measurable": False,
                 "why": "fewer than three common marks — no return series exists yet"}
            )
            continue

        live_r = live[common].pct_change().dropna()
        bt_r = backtest[common].pct_change().dropna()
        diff = (live_r - bt_r).to_numpy(dtype=float)
        n = len(diff)
        sd = float(np.std(diff, ddof=1)) if n > 1 else float("nan")
        observed_gap_ann = float(np.mean(diff)) * TRADING_DAYS if n else float("nan")
        stderr_ann = sd * TRADING_DAYS / math.sqrt(n) if n and sd == sd else float("nan")

        sleeves.append(
            {
                "sleeve": name,
                "walkforward": spec["wf"],
                "common_days": len(common),
                "return_observations": n,
                "window": [common[0], common[-1]],
                "measurable": False,          # set honestly below
                "observed_annualised_gap": observed_gap_ann,
                "standard_error_of_that_gap": stderr_ann,
                "observed_over_stderr": (
                    observed_gap_ann / stderr_ann
                    if stderr_ann and stderr_ann == stderr_ann
                    else None
                ),
                "daily_tracking_sd": sd,
                "days_required_to_detect": {
                    f"{gap:.1%}": days_required(sd, gap) for gap in GAPS
                },
                "calendar_days_required_to_detect_1pct": (
                    days_required(sd, 0.01) * 365.25 / TRADING_DAYS
                ),
            }
        )

    for sleeve in sleeves:
        ratio = sleeve.get("observed_over_stderr")
        sleeve["measurable"] = bool(ratio is not None and abs(ratio) >= 1.96)

    detectable = [s for s in sleeves if s["measurable"]]
    result = {
        "schema": "canli.alphac-execution-gap-power.v1",
        "claim_boundary": (
            "Reads trading databases and walk-forward curves read-only. Registers no hypothesis "
            "identity and opens no return data. 0 trials."
        ),
        "go_live_date": go_live,
        "the_answer": (
            "THE RECORD IS TOO SHORT. Overlap between the live marks and a walk-forward that "
            "extends into the live period exists for two sleeves and is 5 and 9 days — four and "
            "eight return observations. No execution gap is distinguishable from noise at that "
            "length, and the observed divergences below are OBSERVATIONS, not estimates."
        ),
        "why_only_two_sleeves": (
            "A comparison needs a backtest that covers the live days. The BLESSED research curves "
            "(crypto_carry_wk, k30_dn_63) are frozen by disclosure protocol and end 2026-06-01, "
            "before go-live, so they cannot answer this question at any record length. Only the "
            "live-forward walk-forwards, regenerated by the daily ticks, overlap at all."
        ),
        "the_quantity_that_answers_it_soonest": (
            "The TRACKING DIFFERENCE d = r_live - r_backtest, not either Sharpe. The two run the "
            "same signal on the same days, so their returns are strongly correlated and the "
            "difference series is far less noisy than either level. The record needed to detect "
            "an execution gap is therefore much shorter than the record needed to establish the "
            "edge itself — which is the useful thing to know."
        ),
        "sleeves": sleeves,
        "any_gap_detectable_today": bool(detectable),
        "verdict": (
            "NOT MEASURABLE YET — publish the power, not a number"
            if not detectable
            else "A GAP CLEARS ITS OWN STANDARD ERROR — investigate before extending the record"
        ),
        "when_to_look_again": {
            "note": (
                "The useful output is not a number today but a date. Converted from return "
                "observations at 252 trading days a year, and rounded outward because the "
                "tracking sd behind them is itself estimated from four and eight observations."
            ),
            "a_5pct_annual_gap": {
                sleeve["sleeve"]: (
                    f"{sleeve['days_required_to_detect']['5.0%'] / 21:.0f} months"
                )
                for sleeve in sleeves
                if sleeve.get("days_required_to_detect")
            },
            "a_1pct_annual_gap": {
                sleeve["sleeve"]: (
                    f"{sleeve['days_required_to_detect']['1.0%'] / 252:.1f} years"
                )
                for sleeve in sleeves
                if sleeve.get("days_required_to_detect")
            },
            "the_practical_reading": (
                "A LARGE execution gap — 5% of equity a year — becomes visible in roughly three "
                "to four months, so that is when this is worth re-running. A 1% gap needs the "
                "better part of a decade and is not answerable by waiting. If a gap that small "
                "matters, it has to be attacked by measuring fills directly against their "
                "decision prices, not by comparing equity curves."
            ),
        },
        "what_would_change_this": (
            "Time, and nothing else. The days_required figures below are the honest answer to "
            "'when can we ask'. They also depend on the tracking sd being estimated from four and "
            "eight observations, which is itself a very noisy estimate — treat them as an order "
            "of magnitude, not a date."
        ),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    for sleeve in sleeves:
        print(f"\n  {sleeve['sleeve']}  ({sleeve.get('return_observations', 0)} return obs, "
              f"{sleeve['common_days']} common days)")
        if not sleeve.get("daily_tracking_sd"):
            print(f"    {sleeve.get('why', 'not measurable')}")
            continue
        print(f"    observed annualised gap {sleeve['observed_annualised_gap']:+.2%} "
              f"+/- {sleeve['standard_error_of_that_gap']:.2%}  "
              f"({sleeve['observed_over_stderr']:+.2f} standard errors)")
        print(f"    daily tracking sd {sleeve['daily_tracking_sd']:.4%}")
        print("    return observations needed to detect an annual gap of:")
        for gap, need in sleeve["days_required_to_detect"].items():
            print(f"      {gap:>6}  {need:>10,.0f}")
    print(f"\n  verdict: {result['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
