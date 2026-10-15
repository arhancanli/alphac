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
    ("select_both.log", "stocks-book", "selection rules for the netted book, base or overlapping per signal"),
    ("crypto_search.log", "crypto", "cash-and-carry per coin, on while trailing funding pays"),
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
    (HERE / "ledger.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    print(f"{len(lines)} ledger lines")


if __name__ == "__main__":
    main()
