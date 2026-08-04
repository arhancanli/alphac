#!/usr/bin/env python3
"""PROBE — TRACK B / STEP 2a: LETF AUM history from SEC N-PORT (free, PIT-documented).

Builds the most honest FREE monthly AUM series for the 14 3x/-3x LETFs in the six
families the forced-rebalance study needs:

    QQQ:  TQQQ(+3) SQQQ(-3)          [ProShares Trust  CIK 1174610]
    SPY:  UPRO(+3) SPXU(-3)          [ProShares]
          SPXL(+3) SPXS(-3)          [Direxion Shares ETF Trust CIK 1424958]
    SOXX: SOXL(+3) SOXS(-3)          [Direxion]
    IWM:  TNA(+3)  TZA(-3)           [Direxion]
    TLT:  TMF(+3)  TMV(-3)           [Direxion]
    XLF:  FAS(+3)  FAZ(-3)           [Direxion]

Method (per the step-1 feasibility verdict):
  1. Resolve each fund's EDGAR series ID from the trust's scd=series page.
  2. List all public NPORT-P filings per series (quarterly cadence, ~60-day lag).
  3. Range-fetch only the first ~80KB of each primary_doc.xml (Part A/B fields sit
     before the holdings block) and parse: repPdDate, netAssets, totAssets, the three
     monthly class returns (rtn1=oldest .. rtn3=reporting month) and the three monthly
     net flows (sales + reinvestment - redemption).
  4. Reconstruct the two intra-quarter month-end AUMs backwards from the filed anchor:
         A_{m-1} = (A_m - netflow_m) / (1 + rtn_m)
     and also A_{m-3} (previous quarter end) as a CROSS-CHECK against the previous
     filing's filed anchor -> that reconstruction error IS the honest error bar.
  5. Emit a tidy parquet with a PIT column: every month-end value carries the FILING
     date it became public (60-day-lag strict PIT) — the flow study documents that the
     *live* quantity (daily AUM on issuer pages) is real-time public but unarchived,
     so month-end-anchored usage is a reconstruction of knowable data, and runs the
     strict filing-lag variant as robustness.

Outputs (all NEW paths, nothing existing touched):
    data/research/intraday_probe/letf/nport_aum/letf_monthly_aum.parquet
    data/research/intraday_probe/letf/nport_aum/letf_aum_report.json

Ledger: data-collection utility, NO gauntlet run -> zero appends to var/experiments.jsonl.

Usage:  uv run python scripts/probe_letf_aum_nport.py
"""
# ruff: noqa: E501
from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

import httpx
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
OUT = _ROOT / "data" / "research" / "intraday_probe" / "letf" / "nport_aum"
OUT.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "AlphaForge Research arhancanli@icloud.com"}
SEC = "https://www.sec.gov"

TRUSTS = {
    "proshares": "0001174610",
    "direxion": "0001424958",
}

# normalized (lowercase, (r) stripped, ' shares'/' etf' suffix stripped) series name -> ticker
NAME_TO_TICKER = {
    "proshares ultrapro qqq": "TQQQ",
    "proshares ultrapro short qqq": "SQQQ",
    "proshares ultrapro s&p500": "UPRO",
    "proshares ultrapro s&p 500": "UPRO",
    "proshares ultrapro short s&p500": "SPXU",
    "proshares ultrapro short s&p 500": "SPXU",
    "direxion daily s&p 500 bull 3x": "SPXL",
    "direxion daily s&p 500 bear 3x": "SPXS",
    "direxion daily semiconductor bull 3x": "SOXL",
    "direxion daily semiconductor bear 3x": "SOXS",
    "direxion daily small cap bull 3x": "TNA",
    "direxion daily small cap bear 3x": "TZA",
    "direxion daily 20+ year treasury bull 3x": "TMF",
    "direxion daily 20+ year treasury bear 3x": "TMV",
    "direxion daily financial bull 3x": "FAS",
    "direxion daily financial bear 3x": "FAZ",
}

TICKER_META = {  # ticker -> (family underlying, leverage L)
    "TQQQ": ("QQQ", 3), "SQQQ": ("QQQ", -3),
    "UPRO": ("SPY", 3), "SPXU": ("SPY", -3), "SPXL": ("SPY", 3), "SPXS": ("SPY", -3),
    "SOXL": ("SOXX", 3), "SOXS": ("SOXX", -3),
    "TNA": ("IWM", 3), "TZA": ("IWM", -3),
    "TMF": ("TLT", 3), "TMV": ("TLT", -3),
    "FAS": ("XLF", 3), "FAZ": ("XLF", -3),
}


def _get(cli: httpx.Client, url: str, params: dict | None = None, rng: str | None = None) -> httpx.Response:
    hdr = dict(UA)
    if rng:
        hdr["Range"] = rng
    for attempt in range(5):
        r = cli.get(url, params=params, headers=hdr)
        if r.status_code in (200, 206):
            return r
        if r.status_code in (403, 429, 503):
            time.sleep(2.0 * (attempt + 1))
            continue
        r.raise_for_status()
    r.raise_for_status()
    return r


def _norm_name(s: str) -> str:
    s = html.unescape(s).lower()
    s = s.replace("(r)", "").replace("®", "")
    s = re.sub(r"\s+", " ", s).strip()
    for suf in (" shares", " etf"):
        if s.endswith(suf):
            s = s[: -len(suf)].strip()
    return s


def resolve_series(cli: httpx.Client) -> dict[str, dict]:
    """ticker -> {series_id, trust_cik, series_name}."""
    found: dict[str, dict] = {}
    for trust, cik in TRUSTS.items():
        r = _get(cli, f"{SEC}/cgi-bin/browse-edgar",
                 {"action": "getcompany", "CIK": cik, "scd": "series", "hidefilings": "1"})
        pairs = re.findall(r'CIK=(S\d{9})&amp;scd=series&amp;view=mutual-fund">([^<]+)</a>', r.text)
        for sid, raw in pairs:
            tick = NAME_TO_TICKER.get(_norm_name(raw))
            if tick and tick not in found:
                found[tick] = {"series_id": sid, "trust_cik": cik, "series_name": html.unescape(raw), "trust": trust}
        time.sleep(0.3)
    missing = sorted(set(TICKER_META) - set(found))
    if missing:
        raise SystemExit(f"BLOCKER: could not resolve EDGAR series for {missing}")
    return found


def list_filings(cli: httpx.Client, series_id: str) -> list[dict]:
    r = _get(cli, f"{SEC}/cgi-bin/browse-edgar",
             {"action": "getcompany", "CIK": series_id, "type": "NPORT-P", "count": "100", "output": "atom"})
    accs = re.findall(r"<accession-number>([\d-]+)</accession-number>", r.text)
    dates = re.findall(r"<filing-date>([\d-]+)</filing-date>", r.text)
    types = re.findall(r"<filing-type>([^<]+)</filing-type>", r.text)
    n = min(len(accs), len(dates), len(types))
    return [{"acc": accs[i], "filing_date": dates[i], "type": types[i]} for i in range(n)]


_F = r"[-+]?\d*\.?\d+"


def parse_primary(cli: httpx.Client, trust_cik: str, acc: str) -> dict | None:
    acc_nd = acc.replace("-", "")
    url = f"{SEC}/Archives/edgar/data/{int(trust_cik)}/{acc_nd}/primary_doc.xml"
    try:
        r = _get(cli, url, rng="bytes=0-80000")
    except httpx.HTTPStatusError:
        return None
    x = r.text
    out: dict = {}
    m = re.search(r"<repPdDate>([\d-]+)</repPdDate>", x)
    if not m:
        return None
    out["rep_pd_date"] = m.group(1)
    for tag in ("netAssets", "totAssets"):
        m = re.search(rf"<{tag}>({_F})</{tag}>", x)
        out[tag] = float(m.group(1)) if m else float("nan")
    m = re.search(r"<monthlyTotReturn\b([^>]*)/>", x)
    rtns = {}
    if m:
        for k, v in re.findall(rf'(rtn\d)="({_F})"', m.group(1)):
            rtns[k] = float(v) / 100.0
    out["rtn"] = [rtns.get(f"rtn{i}") for i in (1, 2, 3)]
    flows = []
    for i in (1, 2, 3):
        m = re.search(rf"<mon{i}Flow\b([^>]*)/>", x)
        if m:
            a = dict(re.findall(rf'(\w+)="({_F})"', m.group(1)))
            flows.append(float(a.get("sales", 0)) + float(a.get("reinvestment", 0)) - float(a.get("redemption", 0)))
        else:
            flows.append(None)
    out["netflow"] = flows
    return out


def month_end(d: pd.Timestamp, back: int) -> pd.Timestamp:
    """month-end `back` months before month-end d (d must already be a month-end)."""
    return d if back == 0 else d - pd.offsets.MonthEnd(back)


def main() -> int:
    rows: list[dict] = []
    xchecks: list[dict] = []
    with httpx.Client(timeout=30) as cli:
        series = resolve_series(cli)
        print(f"resolved {len(series)} series IDs")
        for tick, meta in sorted(series.items()):
            filings = list_filings(cli, meta["series_id"])
            # prefer latest filing per accession-period; amendments (NPORT-P/A) filed later win
            print(f"{tick:5s} {meta['series_id']}  filings={len(filings)}", end=" ", flush=True)
            per_period: dict[str, dict] = {}
            for f in filings:
                time.sleep(0.15)
                p = parse_primary(cli, meta["trust_cik"], f["acc"])
                if p is None or not p.get("rep_pd_date"):
                    continue
                key = p["rep_pd_date"]
                keep = per_period.get(key)
                if keep is None or f["filing_date"] > keep["filing_date"]:
                    per_period[key] = {**p, **f}
            print(f"periods={len(per_period)}")
            fam, lev = TICKER_META[tick]
            for pdte, p in sorted(per_period.items()):
                d3 = pd.Timestamp(pdte) + pd.offsets.MonthEnd(0)
                a3 = p["netAssets"]
                rows.append({"ticker": tick, "family": fam, "leverage": lev, "month_end": d3,
                             "net_assets": a3, "tot_assets": p["totAssets"], "method": "filed",
                             "filing_date": p["filing_date"], "acc": p["acc"]})
                # reconstruct backwards: A_{m-1} = (A_m - flow_m) / (1+r_m)
                a = a3
                ok = True
                recon = []
                for i, back in ((2, 1), (1, 2), (0, 3)):  # rtn index, months back
                    r_m, f_m = p["rtn"][i], p["netflow"][i]
                    if r_m is None or f_m is None or a != a or abs(1.0 + r_m) < 1e-6:
                        ok = False
                        break
                    a = (a - f_m) / (1.0 + r_m)
                    recon.append((month_end(d3, back), a))
                if ok:
                    for dte, val in recon[:2]:  # two intra-quarter months
                        rows.append({"ticker": tick, "family": fam, "leverage": lev, "month_end": dte,
                                     "net_assets": val, "tot_assets": float("nan"), "method": "reconstructed",
                                     "filing_date": p["filing_date"], "acc": p["acc"]})
                    xchecks.append({"ticker": tick, "quarter_end": str(recon[2][0].date()), "recon_prev_anchor": recon[2][1]})

    df = pd.DataFrame(rows)
    # cross-check: reconstructed previous-quarter anchor vs the actually-filed anchor
    filed = df[df["method"] == "filed"].set_index(["ticker", "month_end"])["net_assets"]
    errs = []
    for xc in xchecks:
        key = (xc["ticker"], pd.Timestamp(xc["quarter_end"]))
        if key in filed.index and filed[key] > 0:
            errs.append(abs(xc["recon_prev_anchor"] / filed[key] - 1.0))
    err_s = pd.Series(errs, dtype=float)

    # de-duplicate: filed anchor beats reconstruction for the same month
    df = (df.sort_values(["ticker", "month_end", "method"])  # 'filed' < 'reconstructed'
            .drop_duplicates(["ticker", "month_end"], keep="first")
            .reset_index(drop=True))
    df.to_parquet(OUT / "letf_monthly_aum.parquet", index=False)

    span = df.groupby("ticker")["month_end"].agg(["min", "max", "count"])
    latest = df.sort_values("month_end").groupby("ticker").tail(1).set_index("ticker")["net_assets"] / 1e9
    report = {
        "probe": "TRACK_B_STEP_2a_letf_nport_aum",
        "date": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "series_resolved": {t: series[t]["series_id"] for t in sorted(series)},
        "rows": int(len(df)),
        "months_per_ticker": {t: int(span.loc[t, "count"]) for t in span.index},
        "span": {t: f"{span.loc[t, 'min'].date()}..{span.loc[t, 'max'].date()}" for t in span.index},
        "latest_net_assets_busd": {t: round(float(v), 2) for t, v in latest.items()},
        "reconstruction_xcheck": {
            "n": int(len(err_s)),
            "median_abs_rel_err": round(float(err_s.median()), 4) if len(err_s) else None,
            "p90_abs_rel_err": round(float(err_s.quantile(0.9)), 4) if len(err_s) else None,
            "max_abs_rel_err": round(float(err_s.max()), 4) if len(err_s) else None,
            "meaning": "reconstructed previous-quarter-end AUM vs the independently FILED anchor — the honest error bar on intra-quarter reconstructed months",
        },
        "pit_note": "each month-end value carries filing_date (public ~60d after quarter end); the flow probe uses month-end-anchored AUM propagated daily (real-time-knowable quantity, archive-missing) and runs strict filing-lag as robustness",
        "ledger": "data collection only, no gauntlet run, zero appends to var/experiments.jsonl",
    }
    (OUT / "letf_aum_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
