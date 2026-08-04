#!/usr/bin/env python3
"""FEASIBILITY probe (NOT a build): can Polymarket macro odds LEAD a tradeable asset?

Lead-3 sweep scope. Reads PolyEdge's FREE historical odds (~/polyedge/data/price_history.jsonl,
daily CLOB mid = implied probability) for a handful of long-lived MACRO markets (Fed hike/cut,
recession) and aligns them against AlphaForge's own daily ETF bars (data/lake_mf: TLT/IEF/SHY/GLD/
SPY). It answers ONE cheap question by eyeball: does the day-over-day CHANGE in the crowd-implied
probability LEAD the next-day asset move, or merely MIRROR / LAG it?

Leakage discipline (this is the whole point):
  * signal on date d  = prob_d - prob_{d-1}  (a change fully realised by the day-d snapshot)
  * target           = asset return close_{d+1}/close_d - 1   (STRICTLY next day, no same-bar)
  * we ALSO report the contemporaneous corr and the REVERSE lead (asset_d -> prob_{d+1}) so a
    "PM is just a lagging mirror of the rates market" null is visible, not hidden.

NOTHING here is a deploy signal. No DSR, no walk-forward -- this is a go/no-go eyeball only.
Read-only against both repos; writes notes to artifacts/sweep/pmsignal_scope/.

  uv run python scripts/probe_pmsignal_feasibility.py
"""
# ruff: noqa: E501
from __future__ import annotations

import glob
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

POLY = Path.home() / "polyedge" / "data"
LAKE = Path.home() / "alphaforge" / "data" / "lake_mf" / "ohlcv_1d"
OUT = Path.home() / "alphaforge" / "artifacts" / "sweep" / "pmsignal_scope"
OUT.mkdir(parents=True, exist_ok=True)

# (market_id, human label, sign vs bonds): +1 => higher prob should push TLT UP (rate CUT),
# -1 => higher prob should push TLT DOWN (rate HIKE). Used only to orient the eyeball, never to fit.
MACRO = [
    ("516706", "Fed rate hike in 2025?", -1),
    ("501190", "Fed rate hike in 2024?", -1),
    ("253299", "Fed rate cut by May 1 2024?", +1),
    ("504465", "Fed emergency rate cut in 2024?", +1),
    ("240410", "US recession by Q3 2022?", +1),  # recession fear -> flight to Treasuries
]

# Rate-sensitive tradeables already in AlphaForge's MF book.
ASSETS = ["TLT", "IEF", "SHY", "GLD", "SPY"]

COST_BPS = 5.0  # round-trip-ish per flip, generous for a daily ETF eyeball


def load_prob(market_id: str) -> pd.Series | None:
    """Daily implied-probability series for one market_id from price_history.jsonl."""
    with open(POLY / "price_history.jsonl") as f:
        for line in f:
            d = json.loads(line)
            if str(d.get("market_id")) == market_id:
                t = d.get("t") or []
                p = d.get("p") or []
                if len(t) < 5:
                    return None
                idx = pd.to_datetime(np.asarray(t), unit="s", utc=True).normalize()
                s = pd.Series(np.asarray(p, dtype=float), index=idx, name="prob")
                s = s[~s.index.duplicated(keep="last")].sort_index()
                return s
    return None


def load_asset(ticker: str) -> pd.Series:
    """Daily adjusted close for one ETF from the MF lake, indexed by UTC-midnight date."""
    files = sorted(glob.glob(str(LAKE / f"instrument_id=XUSE:CASH:{ticker}USD" / "year=*" / "data.parquet")))
    frames = [pq.ParquetFile(fp).read(columns=["ts_open", "close"]).to_pandas() for fp in files]
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["ts_open"], utc=True).dt.normalize()
    df = df.drop_duplicates("date", keep="last").set_index("date").sort_index()
    return df["close"].astype(float)


def corr(a: np.ndarray, b: np.ndarray) -> tuple[float, int]:
    m = np.isfinite(a) & np.isfinite(b)
    a, b = a[m], b[m]
    if len(a) < 8 or a.std() == 0 or b.std() == 0:
        return float("nan"), int(len(a))
    return float(np.corrcoef(a, b)[0, 1]), int(len(a))


def t_of_r(r: float, n: int) -> float:
    if not math.isfinite(r) or n < 4 or abs(r) >= 1:
        return float("nan")
    return r * math.sqrt((n - 2) / (1 - r * r))


def main() -> int:
    report: list[dict] = []
    lines: list[str] = []

    def emit(s: str = "") -> None:
        print(s)
        lines.append(s)

    emit("PM-AS-SIGNAL FEASIBILITY EYEBALL  (Polymarket macro odds -> AlphaForge ETFs)")
    emit("=" * 92)
    emit("signal_d = prob_d - prob_{d-1};  target = STRICT next-day asset return (no same-bar).")
    emit(f"cost applied to the toy flip PnL: {COST_BPS} bps.  This is go/no-go only -- NOT a backtest.")
    emit("")

    assets = {t: load_asset(t) for t in ASSETS}
    for tk, s in assets.items():
        emit(f"  loaded {tk}: {len(s)} daily bars  {s.index.min().date()} -> {s.index.max().date()}")
    emit("")

    for mid, label, orient in MACRO:
        prob = load_prob(mid)
        if prob is None:
            emit(f"[{mid}] {label}: NO usable probability series (empty/short) -- skip")
            emit("")
            continue
        emit(f"[{mid}] {label}   sign_vs_TLT={'+' if orient > 0 else '-'}")
        emit(f"    prob series: {len(prob)} daily pts  {prob.index.min().date()} -> {prob.index.max().date()}  "
             f"(prob range {prob.min():.2f}..{prob.max():.2f})")
        dprob = prob.diff()

        for tk in ASSETS:
            px = assets[tk]
            df = pd.DataFrame({"dprob": dprob, "px": px}).dropna(subset=["px"])
            # align to the union calendar the prob lives on; forward-nothing, inner join on dates present in both
            j = pd.DataFrame({"dprob": dprob}).join(pd.DataFrame({"px": px}), how="inner")
            j["ret"] = j["px"].pct_change()
            j["ret_next"] = j["ret"].shift(-1)          # target: strictly next day
            j["dprob_next"] = j["dprob"].shift(-1)       # for reverse-lead test
            j = j.dropna(subset=["dprob"])

            lead_r, n_lead = corr(j["dprob"].to_numpy(), j["ret_next"].to_numpy())    # PM leads asset?
            coin_r, n_coin = corr(j["dprob"].to_numpy(), j["ret"].to_numpy())         # coincident mirror?
            rev_r, n_rev = corr(j["ret"].to_numpy(), j["dprob_next"].to_numpy())      # asset leads PM?

            # toy next-day directional PnL from the PM signal (oriented), net of cost on every flip
            sig = np.sign(j["dprob"].to_numpy()) * orient
            fwd = j["ret_next"].to_numpy()
            m = np.isfinite(sig) & np.isfinite(fwd) & (sig != 0)
            pnl_gross = float(np.nansum(sig[m] * fwd[m]))
            flips = int(np.sum(np.abs(np.diff(np.nan_to_num(sig[m]))) > 0)) if m.sum() > 1 else 0
            pnl_net = pnl_gross - flips * (COST_BPS / 1e4)
            npos = int(m.sum())
            sharpe_like = float("nan")
            if npos > 8:
                pv = sig[m] * fwd[m]
                if pv.std() > 0:
                    sharpe_like = float(pv.mean() / pv.std() * math.sqrt(252))

            emit(f"      {tk:>4}  lead r={lead_r:+.3f} (t={t_of_r(lead_r, n_lead):+.1f}, n={n_lead})   "
                 f"coincident r={coin_r:+.3f}   reverse(asset->PM) r={rev_r:+.3f}   "
                 f"toy net PnL={pnl_net:+.3f} over {npos}d ({flips} flips) sh~{sharpe_like:+.2f}")
            report.append(dict(market_id=mid, label=label, asset=tk, orient=orient,
                               lead_r=lead_r, lead_t=t_of_r(lead_r, n_lead), n_lead=n_lead,
                               coincident_r=coin_r, reverse_r=rev_r,
                               toy_net_pnl=pnl_net, flips=flips, n_days=npos, sharpe_like=sharpe_like))
        emit("")

    (OUT / "feasibility_results.json").write_text(json.dumps(report, indent=2))
    (OUT / "feasibility_run.txt").write_text("\n".join(lines))
    emit(f"wrote {OUT / 'feasibility_results.json'}")
    emit(f"wrote {OUT / 'feasibility_run.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
