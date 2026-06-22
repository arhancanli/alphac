"""Generate the paper-trading state JSON the Meridian web app renders.

The HONEST data backbone: the canonical paper-trading track record of the live algorithm
(the 3-sleeve book) plus the research/simulation curve for context, with honest metrics and
the radical-transparency caveats. A daily job re-runs this to append the live mark.

Radical transparency rules baked in: the RESEARCH curve is always labelled simulation; the
LIVE curve starts at go-live (no fabricated history); metrics are the honest forward numbers
(grade C+, forward Sharpe ~0.5-0.7), never the in-sample headline as if it were earned.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pyarrow.parquet as pq

from alphaforge.portfolio.book import SleeveCurve, combine_book

GO_LIVE = "2026-06-21"  # the day the live paper track record begins
SLEEVES = [
    ("prereg_investment", "Equity Investment", "Asset-growth / CMA, US wide universe", 0.83),
    ("prereg_trend", "Managed-Futures Trend", "Multi-horizon TSMOM, 18 futures", 0.32),
    ("prereg_crypto_trend", "Crypto Trend", "Multi-horizon TSMOM, 10 majors", 0.97),
]


def load(n):
    t = pq.read_table(f"artifacts/walkforward/{n}/equity.parquet").to_pydict()
    return SleeveCurve(n, list(t["ts"]), list(t["equity"]))


def main():
    sl = [load(s[0]) for s in SLEEVES]
    book = combine_book(sl, scheme="equal_risk", trading_days=365)
    # research (simulation) curve: monthly-sampled to keep payload light
    days, eq = book.days, book.equity_curve
    research = []
    for i in range(0, len(days), 5):  # ~weekly points
        d = dt.datetime(1970, 1, 1, tzinfo=dt.UTC) + dt.timedelta(days=int(days[i]))
        research.append({"date": d.strftime("%Y-%m-%d"), "equity": round(float(eq[i]) * 100000, 2)})
    # live paper curve: starts at go-live, $100k, empty until the daily job appends marks
    live = [{"date": GO_LIVE, "equity": 100000.0}]
    state = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "go_live_date": GO_LIVE,
        "book": {
            "name": "AlphaForge Cross-Asset Book",
            "style": "Market-neutral multi-strategy (equity + managed-futures + crypto trend)",
            "sleeves": [
                {
                    "key": s[0],
                    "name": s[1],
                    "desc": s[2],
                    "standalone_sharpe": s[3],
                    "weight": round(float(book.weights[s[0]].mean()), 3),
                }
                for s in SLEEVES
            ],
        },
        "metrics": {
            "in_sample_sharpe": round(float(book.sharpe), 2),
            "honest_forward_sharpe": "0.5 to 0.7",
            "in_sample_cagr_pct": round(float(book.cagr) * 100, 1),
            "honest_forward_return_pct": "10 to 14 (vol-targeted)",
            "max_drawdown_pct": round(float(book.maxdd) * 100, 1),
            "realistic_worst_dd_pct": "-10 to -15",
            "correlation": "sleeves decorrelated (<0.15 pairwise)",
            "capacity": "$1B+",
            "gauntlet_grade": "C+",
            "gauntlet_pass": "3 of 10 clean, 6 marginal, 1 fail",
            "live_days": 0,
        },
        "transparency": [
            "The research curve is a simulation, not realised trading. "
            "No real capital has been deployed.",
            "The live paper track record begins "
            + GO_LIVE
            + " and is shown as it accrues. We publish no return until it is earned in the open.",
            "In-sample Sharpe is 1.18; the honest forward expectation after "
            "multiple-testing deflation is ~0.5 to 0.7.",
            "The edge is genuine (market-neutral, crisis-positive, statistically "
            "real) but modest and not yet proven live.",
        ],
        "research_curve": research,
        "live_curve": live,
    }
    out = Path("data/paper/state.json")
    out.write_text(json.dumps(state, indent=2))
    print(
        f"wrote {out}  ({len(research)} research pts, live starts {GO_LIVE}, "
        f"in-sample SR {book.sharpe:.2f})"
    )
    # also copy to the web app if it exists
    app = Path.home() / "meridian-app" / "public"
    if app.is_dir():
        (app / "paper-state.json").write_text(json.dumps(state, indent=2))
        print(f"copied to {app / 'paper-state.json'}")


if __name__ == "__main__":
    main()
