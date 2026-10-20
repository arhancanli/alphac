"""The search ledger: one line per variant the lab computed, with its search-year result, rebuilt from the
run logs so nothing tried is missing. Written to research/breadth_lab/ledger.jsonl (tracked).

    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.ledger
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from research.breadth_lab.panel import CACHE

HERE = Path(__file__).resolve().parent
RUNS = [
    ("lab_round1.log", "stocks", "price signals inside industries; hedge and leverage from net returns (superseded definition)"),
    ("lab_round2.log", "stocks", "price and fundamental signals inside industries; hedge and leverage from before-cost returns"),
    ("lab_smoothed.log", "stocks", "the same signals held as overlapping portfolios (mean of the last 3 monthly or 4 weekly rebalances)"),
    ("select1.log", "stocks-book", "selection rules for the netted book, base signals"),
    ("select_smoothed.log", "stocks-book", "selection rules for the netted book, overlapping-portfolio signals"),
    ("band_search.log", "stocks-book", "no-trade band on the netted book (rule signals_pre_0.3, overlapping-portfolio signals)"),
    ("crypto_search.log", "crypto", "cash-and-carry per coin, on while trailing funding pays"),
    # Round 2 (PROTOCOL amendment 3), search years only.
    ("r2_futures_search.log", "futures", "round 2: trend at 21/63/126/252 days, carry and cross-sectional momentum per CME market (a first run with a book-scaling bug on the same six variants was discarded unread past the bug)"),
    ("r2_futures_search2.log", "futures", "round 2: slower trend variants (monthly, blended 126+252, sign of the 12-month return) beside the first six"),
    ("r2_crypto_xs_search.log", "crypto-xs", "round 2: ten signals ranked across perpetuals inside four liquidity tiers"),
    ("r2_signals_price.log", "stocks", "round 2: six new price signals inside industries, overlapping portfolios"),
    ("r2_signals_fund.log", "stocks", "round 2: fifteen new fundamental signals from the full SF1 file inside industries, overlapping portfolios"),
    ("r2_industries.log", "stocks-industries", "round 2: industry rotation, whole industries ranked against each other"),
    ("r2_books_a.log", "stocks-book", "round 2: netted books with the new signals, with and without factor momentum (band 1.5)"),
    ("r2_books_b.log", "stocks-book", "round 2: further netted-book variants"),
    # Round 3 (PROTOCOL amendments 4 and 5), search years only.
    ("r3_run.log", "stocks-pods", "round 3: 52 signals x 4 cell schemes, pods, per-sleeve flexible admission (amendment 4); brake figures from a central layer that re-levered braked books (bug)"),
    ("r3_select_fixed.log", "stocks-pods", "round 3 rerun after the brake fix: the book is sized from the plain book, capped at 5x"),
    ("r3b_families.log", "stocks-pods", "round 3 variant B (amendment 5, after seeing round 3): family admission; brake figures from the bugged central layer"),
    ("r3b_families_fixed.log", "stocks-pods", "round 3 variant B rerun after the brake fix"),
    ("r3b_before_costs.log", "stocks-pods", "round 3 variant B split selection measured before costs (diagnostic, nothing chosen)"),
    ("r3c_netted.log", "stocks-pods", "round 3 variant B split selection traded as one netted account, no band and the round-1 band 1.5 (amendment 6)"),
]


def main() -> None:
    lines = []
    for log, block, what in RUNS:
        path = CACHE / "logs" / log
        if not path.exists():
            continue
        for row in path.read_text().splitlines():
            m = re.match(r"^([a-z0-9_.]+) (\{.*\})$", row)
            if m:
                lines.append({"block": block, "run": log.removesuffix(".log"), "definition": what, "variant": m.group(1), "search_result": json.loads(m.group(2))})
            elif row.startswith("{"):
                lines.append({"block": block, "run": log.removesuffix(".log"), "definition": what, "variant": None, "search_result": json.loads(row)})
    lines.append({"block": "stocks", "run": "smoke_test", "definition": "first engine run on mom_12_1 and rev_1m (same numbers as lab_round1)", "variant": None, "search_result": None})
    (HERE / "ledger.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    print(f"{len(lines)} ledger lines")


if __name__ == "__main__":
    main()
