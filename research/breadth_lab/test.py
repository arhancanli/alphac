"""The one test: the frozen selection on the years the search never saw. Refuses to run unless the frozen
file's sha256 is the one PROTOCOL.md recorded before the test years were opened.

    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.test
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from research.breadth_lab import book as bk
from research.breadth_lab import crypto as cr
from research.breadth_lab.lab import TARGET_VOL, context, run, stats
from research.breadth_lab.panel import Panel

HERE = Path(__file__).resolve().parent
FROZEN = HERE / "frozen_selection.json"
STOCK_TEST = ("2018-01-01", "2026-06-18")
CRYPTO_TEST = ("2023-01-01", "2026-09-30")


def recorded_sha256() -> str:
    m = re.search(r"frozen_selection\.json sha256 ([0-9a-f]{64})", (HERE / "PROTOCOL.md").read_text())
    if not m:
        raise SystemExit("PROTOCOL.md records no frozen selection: freeze first.")
    return m.group(1)


def scaled(x: pd.Series, periods: int) -> pd.Series:
    vol = x.rolling(126, min_periods=63).std() * np.sqrt(periods)
    return x * (TARGET_VOL / vol.shift(1))


def main() -> None:
    sha = hashlib.sha256(FROZEN.read_bytes()).hexdigest()
    if sha != recorded_sha256():
        raise SystemExit(f"frozen_selection.json is {sha}, not the sha256 PROTOCOL.md recorded: refusing to open the test years.")
    frozen = json.loads(FROZEN.read_text())
    out: dict = {"frozen_selection_sha256": sha}

    selection = [(s, i, int(g)) for s, i, g in frozen["stocks"]["sleeves"]]
    run("test", sorted({s for s, _, _ in selection}))
    c = context(Panel("test"))
    b = bk.book(c, "test", selection)
    net, gross = b["_net"], b["_gross"]
    out["stocks"] = {"sleeves": len(selection), "test_years": STOCK_TEST,
                     "test": stats(net.loc[STOCK_TEST[0]:STOCK_TEST[1]]), "test_before_costs": stats(gross.loc[STOCK_TEST[0]:STOCK_TEST[1]]).get("sharpe"),
                     "search_years_same_code": stats(net.loc[:"2017-12-31"]),
                     "by_year": {str(y): stats(g).get("sharpe") for y, g in net.loc[STOCK_TEST[0]:].groupby(net.loc[STOCK_TEST[0]:].index.year)},
                     "gross_exposure": b["mean_gross_exposure"], "turnover_per_year": b["turnover_per_year"], "cost_per_year": b["cost_per_year"]}

    w = cr.load("test")
    cn, cg, on = cr.sleeves(w, **frozen["crypto"]["params"])
    cbook = cn.mean(axis=1)  # every coin's sleeve while it is on, equal weight
    out["crypto"] = {"params": frozen["crypto"]["params"], "test_years": CRYPTO_TEST,
                     "test": stats(cbook.loc[CRYPTO_TEST[0]:CRYPTO_TEST[1]], periods=365),
                     "test_before_costs": stats(cg.mean(axis=1).loc[CRYPTO_TEST[0]:CRYPTO_TEST[1]], periods=365).get("sharpe"),
                     "coins_with_a_sleeve_in_test": int((cn.loc[CRYPTO_TEST[0]:].notna().sum() >= 60).sum()),
                     "by_year": {str(y): stats(g, periods=365).get("sharpe") for y, g in cbook.loc[CRYPTO_TEST[0]:].groupby(cbook.loc[CRYPTO_TEST[0]:].index.year)}}

    # Both blocks at equal risk on the days both trade (stock days), then the whole at TARGET_VOL.
    s_days = net.dropna()
    crypto_on_stock_days = (1.0 + cbook.fillna(0.0)).cumprod().reindex(s_days.index, method="ffill").pct_change()
    both = pd.concat([scaled(s_days, 252), scaled(crypto_on_stock_days, 252)], axis=1).dropna()
    combo = scaled(both.mean(axis=1), 252)
    window = (max(CRYPTO_TEST[0], STOCK_TEST[0]), min(CRYPTO_TEST[1], STOCK_TEST[1]))
    sw = both.loc[window[0]:window[1]]
    out["combined"] = {"blocks": "stocks and crypto at equal risk", "window": window, "test": stats(combo.loc[window[0]:window[1]]),
                       "block_correlation": round(float(sw.corr().iloc[0, 1]), 3) if len(sw) > 60 else None,
                       "sleeves": len(selection) + out["crypto"]["coins_with_a_sleeve_in_test"]}
    (HERE / "test_result.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
