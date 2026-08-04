#!/usr/bin/env python3
"""COLLECT — Closed-End Fund discounts (CEFConnect) + activist 13D/G filings (EDGAR).

CANDIDATE 2 (CEF deep-discount satellite) data layer. NEW files only: writes
exclusively under data/research/cef/. Nothing in src/**, configs or the live loop
is touched.

=================================== SOURCES ===================================
1. CEFConnect (Nuveen) public JSON API v3 — the freest reliable machine-readable
   source of CEF price/NAV/discount in existence (verified working 2026-07-19,
   no key, no auth; requires a browser User-Agent):
     a) https://www.cefconnect.com/api/v3/DailyPricing
        Full cross-section of all listed US CEFs (361 funds on first pull) with
        Price / NAV / Discount / category / expense ratio / leverage / market
        cap / distribution rate / NAVPublished date. Stored as a DATED snapshot
        -> the forward-accrual spine.
     b) https://www.cefconnect.com/api/v3/pricinghistory/{TICKER}/{PERIOD}
        Per-fund price+NAV+discount history. MEASURED DEPTH (2026-07-19):
          1Y  -> 243 points = DAILY, last 12 months
          5Y  -> 243 points = ~WEEKLY downsample, ~4.7 years
          10Y -> EMPTY (endpoint returns no data)
        So ~5y of WEEKLY discount history per fund is the free ceiling. Both
        1Y-daily and 5Y-weekly are stored per ticker.
2. SEC EDGAR full-text search API (official, free) —
     https://efts.sec.gov/LATEST/search-index?q="<activist name>"&forms=<13D/G>
   for the whitelisted CEF activists (Saba Capital, Bulldog Investors, Karpus
   Management). Hits carry display_names for BOTH filer and subject company
   (subject usually includes its ticker), file_date, accession — enough to build
   a per-fund activist-catalyst flag without parsing filings. Coverage 2001+.
   SEC fair-access: declared User-Agent with contact email, <=~7 req/s.

============================ HONESTY / DATA CAVEATS ===========================
- SURVIVORSHIP: CEFConnect history exists only for CURRENTLY LISTED funds.
  Funds that were open-ended / tendered / merged / liquidated since 2021 (often
  the activist WINS) are absent. Any backtest on this history is a survivorship-
  biased SCREEN, not a bless-grade walk-forward. The probe discloses this.
- The 5Y series is a ~weekly downsample chosen by the vendor, not end-of-week
  sampling we control. Points are snapped to W-FRI in the probe.
- NAVPublished can lag LastUpdated (weekly-NAV funds): the published discount
  may compare today's price to a slightly stale NAV. Disclosed, not repaired.
- Price history is MARKET PRICE only (not distribution-adjusted). CEFs pay
  ~7-8%/yr distributions; the probe handles this explicitly.
- 13D subject->ticker mapping comes from the display_names ticker token with a
  normalized-name fallback; unmatched subjects are stored, flagged unmatched.

================================== OUTPUTS ====================================
  data/research/cef/MANIFEST.json                     source + caveat doc (rewritten each run)
  data/research/cef/snapshots/dailypricing_YYYY-MM-DD.json   dated full cross-section
  data/research/cef/history/{TICKER}.json             {daily_1y, weekly_5y, meta}
  data/research/cef/activist_13d/{slug}.json          raw FTS hits per activist
  data/research/cef/activist_13d/events.json          flattened (subject, ticker, form, file_date) events

Usage:
  uv run python scripts/collect_cef.py                    # everything
  uv run python scripts/collect_cef.py --parts snapshot,edgar
  uv run python scripts/collect_cef.py --parts history --max-tickers 5   # smoke
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
OUT = _ROOT / "data" / "research" / "cef"

CEF_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
SEC_UA = "AlphaForge Research arhancanli@icloud.com"

CEF_DAILY_URL = "https://www.cefconnect.com/api/v3/DailyPricing"
CEF_HIST_URL = "https://www.cefconnect.com/api/v3/pricinghistory/{ticker}/{period}"
FTS_URL = "https://efts.sec.gov/LATEST/search-index"

# Whitelisted CEF activists (phrase = FTS query + filer-identification substring).
# Principals listed so joint-filer display_names are not misread as subjects.
ACTIVISTS = {
    "saba": {
        "phrase": "Saba Capital",
        "filer_markers": ["saba capital", "weinstein boaz", "boaz weinstein"],
    },
    "bulldog": {
        "phrase": "Bulldog Investors",
        "filer_markers": [
            "bulldog investors", "goldstein phillip", "phillip goldstein",
            "dakos andrew", "andrew dakos", "samuels steven", "steven samuels",
            "special opportunities fund",  # Bulldog's own vehicle files jointly
        ],
    },
    "karpus": {
        "phrase": "Karpus Management",
        "filer_markers": ["karpus", "george karpus"],
    },
}
# Old- and new-style (post-2024 EDGAR rename) 13D/G root forms.
FTS_FORMS = ["SC 13D", "SC 13G", "SCHEDULE 13D", "SCHEDULE 13G"]
FTS_PAGE = 100
FTS_MAX_FROM = 9900  # EDGAR hard cap

SLEEP_CEF = 0.12
SLEEP_SEC = 0.15
RETRIES = 3


def _get_json(url: str, ua: str, timeout: float = 30.0):
    last_err: Exception | None = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:  # noqa: PERF203
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET failed after {RETRIES} tries: {url} ({last_err})")


# ------------------------------- part: snapshot --------------------------------

def collect_snapshot(force: bool) -> list[dict]:
    snap_dir = OUT / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    path = snap_dir / f"dailypricing_{today}.json"
    if path.exists() and not force:
        print(f"[snapshot] {path.name} already exists (use --force to refetch)")
        return json.loads(path.read_text())["funds"]
    data = _get_json(CEF_DAILY_URL, CEF_UA)
    if not isinstance(data, list) or len(data) < 100:
        raise RuntimeError(f"DailyPricing looks wrong: type={type(data)} len={len(data) if hasattr(data, '__len__') else '?'}")
    payload = {"fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "source": CEF_DAILY_URL, "funds": data}
    path.write_text(json.dumps(payload))
    print(f"[snapshot] wrote {path.name}: {len(data)} funds")
    return data


# ------------------------------- part: history ---------------------------------

def collect_history(funds: list[dict], max_tickers: int | None, force: bool) -> None:
    hist_dir = OUT / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    tickers = sorted({str(f["Ticker"]).strip().upper() for f in funds if f.get("Ticker")})
    if max_tickers:
        tickers = tickers[:max_tickers]
    today = dt.date.today().isoformat()
    n_ok = n_skip = n_fail = 0
    for i, t in enumerate(tickers):
        path = hist_dir / f"{t}.json"
        if path.exists() and not force:
            try:
                if json.loads(path.read_text()).get("fetched_date") == today:
                    n_skip += 1
                    continue
            except (json.JSONDecodeError, OSError):
                pass  # refetch corrupt file
        rec: dict = {"ticker": t, "fetched_date": today,
                     "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
        ok = True
        for key, period in (("daily_1y", "1Y"), ("weekly_5y", "5Y")):
            try:
                d = _get_json(CEF_HIST_URL.format(ticker=urllib.parse.quote(t), period=period), CEF_UA)
                inner = (d or {}).get("Data") or {}
                rec[key] = inner.get("PriceHistory") or []
                rec.setdefault("nav_ticker", inner.get("NAVTicker"))
                rec.setdefault("cusip", inner.get("Cusip"))
                rec.setdefault("name", inner.get("Name"))
            except RuntimeError as e:
                print(f"[history] {t} {period}: {e}")
                rec[key] = []
                ok = False
            time.sleep(SLEEP_CEF)
        path.write_text(json.dumps(rec))
        n_ok += 1 if ok else 0
        n_fail += 0 if ok else 1
        if (i + 1) % 50 == 0:
            print(f"[history] {i + 1}/{len(tickers)} done")
    print(f"[history] complete: ok={n_ok} skipped_fresh={n_skip} partial_fail={n_fail} of {len(tickers)}")


# -------------------------------- part: edgar ----------------------------------

_TICKER_RE = re.compile(r"\(([A-Z]{1,5}(?:\.[A-Z]{1,2})?)\)\s+\(CIK")
_CIK_RE = re.compile(r"\(CIK\s+(\d{10})\)")


def _fts_page(phrase: str, form: str, frm: int) -> dict:
    q = urllib.parse.urlencode({"q": f'"{phrase}"', "forms": form, "from": frm})
    return _get_json(f"{FTS_URL}?{q}", SEC_UA)


def collect_edgar() -> None:
    ed_dir = OUT / "activist_13d"
    ed_dir.mkdir(parents=True, exist_ok=True)
    events: list[dict] = []
    for slug, spec in ACTIVISTS.items():
        markers = [m.lower() for m in spec["filer_markers"]]
        hits_by_id: dict[str, dict] = {}
        for form in FTS_FORMS:
            frm = 0
            total = None
            while frm <= FTS_MAX_FROM:
                try:
                    page = _fts_page(spec["phrase"], form, frm)
                except RuntimeError as e:
                    print(f"[edgar] {slug} {form} from={frm}: {e}")
                    break
                hits = page.get("hits", {}).get("hits", [])
                if total is None:
                    total = page.get("hits", {}).get("total", {}).get("value", 0)
                for h in hits:
                    hits_by_id[h.get("_id", json.dumps(h)[:80])] = h
                if not hits or frm + FTS_PAGE >= (total or 0):
                    break
                frm += FTS_PAGE
                time.sleep(SLEEP_SEC)
            time.sleep(SLEEP_SEC)
        raw_path = ed_dir / f"{slug}.json"
        raw_path.write_text(json.dumps({
            "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "query_phrase": spec["phrase"], "forms": FTS_FORMS,
            "n_unique_filings": len(hits_by_id),
            "hits": list(hits_by_id.values()),
        }))
        n_ev = 0
        for h in hits_by_id.values():
            src = h.get("_source", {})
            names = src.get("display_names", []) or []
            subjects = [n for n in names if not any(m in n.lower() for m in markers)]
            for subj in subjects:
                tk = _TICKER_RE.search(subj)
                ck = _CIK_RE.search(subj)
                events.append({
                    "activist": slug,
                    "subject_display": subj,
                    "subject_ticker": tk.group(1) if tk else None,
                    "subject_cik": ck.group(1) if ck else None,
                    "form": (src.get("root_forms") or [None])[0],
                    "file_date": src.get("file_date"),
                    "accession": h.get("_id"),
                })
                n_ev += 1
        print(f"[edgar] {slug}: {len(hits_by_id)} unique filings -> {n_ev} subject events")
    events.sort(key=lambda e: (e["file_date"] or "", e["activist"]))
    (ed_dir / "events.json").write_text(json.dumps({
        "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "n_events": len(events), "events": events,
    }))
    print(f"[edgar] events.json: {len(events)} subject events total")


# --------------------------------- manifest ------------------------------------

def write_manifest() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "MANIFEST.json").write_text(json.dumps({
        "candidate": "CEF deep-discount satellite (Candidate 2)",
        "written_by": "scripts/collect_cef.py",
        "last_run_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sources": {
            "cefconnect_dailypricing": CEF_DAILY_URL,
            "cefconnect_pricinghistory": CEF_HIST_URL,
            "edgar_fulltext": FTS_URL,
        },
        "measured_history_depth": {
            "1Y": "daily, ~243 points", "5Y": "~weekly, ~243 points (~4.7y)", "10Y": "EMPTY",
        },
        "caveats": [
            "history only for CURRENTLY LISTED funds => survivorship-biased; screen-grade only",
            "5Y series is vendor-downsampled ~weekly",
            "NAVPublished may lag price date for weekly-NAV funds",
            "price history is market price, NOT distribution-adjusted",
            "13D subject->ticker via display_names token + name fallback; unmatched flagged",
        ],
        "forward_plan": "run daily (snapshot+edgar) to accrue a PIT discount+catalyst tape free of survivorship",
    }, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", default="snapshot,history,edgar")
    ap.add_argument("--max-tickers", type=int, default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    parts = {p.strip() for p in args.parts.split(",")}

    write_manifest()
    funds: list[dict] = []
    if "snapshot" in parts or "history" in parts:
        funds = collect_snapshot(force=args.force and "snapshot" in parts)
    if "history" in parts:
        collect_history(funds, args.max_tickers, args.force)
    if "edgar" in parts:
        collect_edgar()
    print("[done]", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
