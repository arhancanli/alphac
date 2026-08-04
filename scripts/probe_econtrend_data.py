#!/usr/bin/env python3
"""PROBE — POINT-IN-TIME (VINTAGE) MACRO DATASET builder + reader (econ-trend Track A / Step 1).

Builds data/lake_macro_vintage/ : a macro dataset in which EVERY stored value carries the
date on which an investor could FIRST have known it. This is the data substrate for a
future economic-trend sleeve on the 17-ETF managed-futures universe (data/lake_mf).

THE HAZARD THIS FILE EXISTS TO KILL: macro series are revised. Feeding today's revised
history into a backtest manufactures fake alpha. Two defenses, by series type:

  TIER 1 — unrevised, daily, market-based (zero vintage risk):
    Treasury yields (DGS2/DGS10/DGS3MO), breakevens (T10YIE/T5YIE), effective fed funds
    (DFF), trade-weighted dollar (DTWEXBGS 2006+, DTWEXM 1973-2019), WTI spot
    (DCOILWTICO), credit spread (BAA10Y 1986+; HY OAS 2023+ only — license-capped
    keyless). Source: FRED keyless CSV endpoint
    (fredgraph.csv — same no-key precedent as scripts/fx_carry_screen.py).
    publication_date = obs_date + 1 business day (publication reality).
    Commodity/gold spot themes additionally reuse the OWNED lake_mf ETF closes
    (GLD/SLV/USO/DBC/DBA/UNG) which are themselves unrevised market prices.

  TIER 2 — genuinely revised macro (payrolls, CPI, core CPI, industrial production,
    unemployment, housing starts, real consumption):
    REAL-TIME FIRST-RELEASE VINTAGES from the Philadelphia Fed Real-Time Data Set for
    Macroeconomists (RTDSM) — keyless xlsx downloads, the academic standard.
    Per the RTDSM general documentation (gen_doc_nonNIPA.pdf): each vintage records
    exactly the values publicly known ON the vintage date; monthly vintages are dated
    the 15th of the vintage month; quarterly vintages the 15th of the quarter's MIDDLE
    month ("65Q4 (a vintage date of November 1965)").
    => publication_date := vintage date of the FIRST vintage containing the observation.
    This is conservative (payrolls are really out ~the 1st week) and can never leak.

  EXCLUDED (disclosed): real retail sales — no RTDSM variable exists for it and there is
    no keyless first-release source (no FRED/ALFRED API key in this environment).
    RCONM (real personal consumption, monthly vintages) is stored as the honest
    consumer-demand substitute. Copper spot — no unrevised keyless daily source; the
    owned DBC/DBA ETF closes are the commodity-complex fallback.

Reader API (import this module):
    as_of(series, date)          -> latest value whose publication_date <= date (float)
    as_of_full(series, date)     -> (obs_period, value, publication_date) of that value
    history_asof(series, date)   -> PIT history: all (obs, value) rows published <= date
                                    (tier 2: first-release values — do NOT difference
                                    these for growth rates; use vintage_asof)
    vintage_asof(series, date)   -> tier 2 only: the full latest VINTAGE column available
                                    at date (the right object for PIT growth rates)
    list_series()                -> contract table as a DataFrame

Usage:
    uv run --with openpyxl python scripts/probe_econtrend_data.py build   # (re)build lake
    uv run python scripts/probe_econtrend_data.py verify                  # PIT spot-checks

NOTHING in src/ or existing scripts/configs is touched. New files only:
this script + data/lake_macro_vintage/**. No WF gauntlet is run here, so per the
zoo_screen protocol there is no experiments.jsonl append (data build, disclosed).
"""
# ruff: noqa: E501
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
LAKE = _ROOT / "data" / "lake_macro_vintage"
LAKE_MF = _ROOT / "data" / "lake_mf"
T1_DIR = LAKE / "tier1_daily"
T2_DIR = LAKE / "tier2_vintage"
RAW_DIR = LAKE / "raw" / "rtdsm"
REF_DIR = LAKE / "revised_reference"  # NOT point-in-time — honesty checks only

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd=1950-01-01"
RTDSM_XLSX = (
    "https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/"
    "real-time-data/data-files/xlsx/{fname}"
)

# ---------------------------------------------------------------------------
# Series registry (the data contract in code form)
# ---------------------------------------------------------------------------
# TIER 1: keyless FRED daily, unrevised market-based. pub = obs + 1 business day.
TIER1 = {
    "DGS2": "2Y Treasury constant-maturity yield (%; daily; unrevised market)",
    "DGS10": "10Y Treasury constant-maturity yield (%; daily; unrevised market)",
    "DGS3MO": "3M Treasury yield (%; daily; unrevised market)",
    "T10YIE": "10Y breakeven inflation (%; daily; 2003+; unrevised market)",
    "T5YIE": "5Y breakeven inflation (%; daily; 2003+; unrevised market)",
    "DFF": "Effective fed funds rate (%; daily; unrevised)",
    "DTWEXBGS": "Trade-weighted broad USD index (daily; 2006+; goods+services)",
    "DTWEXM": "Trade-weighted major-currencies USD index (daily; 1973-2019, discontinued)",
    "DCOILWTICO": "WTI crude spot (USD/bbl; daily; unrevised market)",
    "BAA10Y": "Moody's Baa corporate yield minus 10Y Treasury (%; daily; 1986+; unrevised market) — primary credit-spread series",
    "BAMLH0A0HYM2": "ICE BofA US High Yield OAS (%; daily; unrevised market) — keyless endpoint is LICENSE-CAPPED to trailing ~3y (2023+); forward-going only",
}

# TIER 2: Philly Fed RTDSM vintage files. (rtdsm_variable, xlsx stem, vintage freq)
TIER2 = {
    "EMPLOY": ("employ", "employMvMd.xlsx", "M", "Nonfarm payroll employment, level (thousands, SA); monthly vintages 1964M12+"),
    "PCPI": ("pcpi", "pcpiMvMd.xlsx", "M", "CPI headline, index level (SA); monthly vintages 1998M11+"),
    "PCPIX": ("pcpix", "pcpixMvMd.xlsx", "M", "CPI core (ex food & energy), index level (SA); monthly vintages 1998M11+"),
    "IPT": ("ipt", "iptMvMd.xlsx", "M", "Industrial production: total, index (SA); monthly vintages 1962M11+"),
    "RUC": ("ruc", "rucQvMd.xlsx", "Q", "Unemployment rate (%, SA); monthly obs but QUARTERLY vintages (coarse timeliness — documented)"),
    "HSTARTS": ("hstarts", "hstartsMvMd.xlsx", "M", "Housing starts (millions, SAAR); monthly vintages"),
    "RCONM": ("rconm", "rconmMvMd.xlsx", "M", "Real personal consumption expenditures, monthly (retail-sales substitute); monthly vintages"),
}

# Current fully-revised series for honesty spot-checks ONLY (never fed to strategies).
REVISED_REF = {
    "PAYEMS": "EMPLOY",
    "CPIAUCSL": "PCPI",
    "CPILFESL": "PCPIX",
    "INDPRO": "IPT",
    "UNRATE": "RUC",
    "HOUST": "HSTARTS",
}


def _get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "alphaforge-probe/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return r.read()


def _rtdsm_hash_url(variable: str, fname: str) -> str:
    """RTDSM media links carry a required ?hash= param; scrape it from the variable page."""
    page = _get(f"https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/{variable}").decode("utf-8", "ignore")
    m = re.search(rf'href="(/-/media/[^"]*{re.escape(fname)}[^"]*)"', page, re.IGNORECASE)
    if not m:
        raise RuntimeError(f"RTDSM link for {fname} not found on {variable} page")
    return "https://www.philadelphiafed.org" + m.group(1).replace("&amp;", "&")


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _next_bday(d: pd.Series) -> pd.Series:
    """obs date -> next business day (weekend-aware; holidays only ever ADD lag risk on
    the honest side is impossible here, so we take the next NYSE-agnostic weekday +0;
    a same-week holiday would mean actual availability is EARLIER than assumed never
    later, because FRED posts these series same evening; +1BD is already a buffer)."""
    return pd.to_datetime(np.busday_offset(d.dt.date.to_numpy().astype("datetime64[D]"), 1, roll="forward"))


def build_tier1() -> list[dict]:
    T1_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for sid, desc in TIER1.items():
        raw = _get(FRED_CSV.format(sid=sid))
        df = pd.read_csv(io.BytesIO(raw))
        df.columns = ["obs_date", "value"]
        df["obs_date"] = pd.to_datetime(df["obs_date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["value"]).reset_index(drop=True)
        df["publication_date"] = _next_bday(df["obs_date"])
        out = T1_DIR / f"{sid}.parquet"
        df.to_parquet(out, index=False)
        rows.append({"series": sid, "tier": 1, "n_obs": len(df),
                     "first_obs": str(df["obs_date"].min().date()),
                     "last_obs": str(df["obs_date"].max().date()), "desc": desc})
        print(f"  tier1 {sid:14s} {len(df):6d} obs  {df['obs_date'].min().date()} .. {df['obs_date'].max().date()}")
    return rows


def _parse_obs_date(s: str) -> pd.Timestamp:
    y, m = s.strip().split(":")
    return pd.Timestamp(int(y), int(m), 1)


def _parse_vintage(col: str, var_prefix: str, freq: str) -> pd.Timestamp:
    """EMPLOY65M1 -> 1965-01-15 ; RUC65Q4 -> 1965-11-15 (15th of quarter's MIDDLE month,
    per RTDSM gen doc: '65Q4 (a vintage date of November 1965)')."""
    tail = col[len(var_prefix):]
    if freq == "M":
        m = re.fullmatch(r"(\d{2})M(\d{1,2})", tail)
        if not m:
            raise ValueError(f"bad vintage col {col}")
        yy, mm = int(m.group(1)), int(m.group(2))
    else:
        m = re.fullmatch(r"(\d{2})Q(\d)", tail)
        if not m:
            raise ValueError(f"bad vintage col {col}")
        yy, mm = int(m.group(1)), {1: 2, 2: 5, 3: 8, 4: 11}[int(m.group(2))]
    year = 1900 + yy if yy > 40 else 2000 + yy
    return pd.Timestamp(year, mm, 15)


def build_tier2() -> list[dict]:
    T2_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, (variable, fname, vfreq, desc) in TIER2.items():
        raw_path = RAW_DIR / fname
        if not raw_path.exists():
            url = _rtdsm_hash_url(variable, fname)
            raw_path.write_bytes(_get(url, timeout=120))
        try:
            xl = pd.ExcelFile(raw_path)
        except TypeError:
            # some RTDSM workbooks (hstartsMvMd) carry a malformed docProps/core.xml
            # modified-date that trips openpyxl; strip doc properties in memory (data
            # sheets untouched) and parse the sanitized copy.
            import zipfile
            buf = io.BytesIO()
            with zipfile.ZipFile(raw_path) as zin, zipfile.ZipFile(buf, "w") as zout:
                for item in zin.infolist():
                    if item.filename != "docProps/core.xml":
                        zout.writestr(item, zin.read(item.filename))
            buf.seek(0)
            xl = pd.ExcelFile(buf)
        df = xl.parse(xl.sheet_names[0])
        date_col = df.columns[0]
        prefix = df.columns[1].rstrip("0123456789MQ")
        # some headers like EMPLOY65M1: prefix strip of trailing digits/M/Q can eat too much
        # (e.g. 'EMPLOYM' ends in M). Derive prefix robustly: longest common alpha prefix.
        prefix = re.match(r"[A-Za-z]+?(?=\d{2}[MQ]\d)", df.columns[1]).group(0)
        obs = df[date_col].astype(str).map(_parse_obs_date)
        vcols = [c for c in df.columns[1:] if re.fullmatch(rf"{re.escape(prefix)}\d{{2}}[MQ]\d{{1,2}}", str(c))]
        vdates = {c: _parse_vintage(str(c), prefix, vfreq) for c in vcols}
        vcols = sorted(vcols, key=lambda c: vdates[c])

        # long vintage matrix
        wide = df[vcols].apply(pd.to_numeric, errors="coerce")
        wide.index = obs
        long = wide.stack().rename("value").reset_index()
        long.columns = ["obs_period", "vintage_col", "value"]
        long["vintage_date"] = long["vintage_col"].map(vdates)
        long = long.drop(columns=["vintage_col"]).sort_values(["obs_period", "vintage_date"])
        long.to_parquet(T2_DIR / f"{name}_vintage_long.parquet", index=False)

        # first release: earliest vintage containing each obs
        vdate_arr = np.array([vdates[c].to_datetime64() for c in vcols])
        vals = wide.to_numpy(float)
        first_idx = np.argmax(~np.isnan(vals), axis=1)
        has_any = ~np.isnan(vals).all(axis=1)
        fr = pd.DataFrame({
            "obs_period": obs.to_numpy(),
            "value_first_release": vals[np.arange(len(obs)), first_idx],
            "publication_date": vdate_arr[first_idx],
        })[has_any].reset_index(drop=True)
        # true first release = value appeared in near-real-time (within 4 months of the
        # obs month; RUC quarterly vintages get 5). Earlier rows are RTDSM deep-history
        # backfill: still honestly dated (known at that vintage) but NOT a first print.
        win = 5 if vfreq == "Q" else 4
        gap_m = (fr["publication_date"].dt.year - fr["obs_period"].dt.year) * 12 + (
            fr["publication_date"].dt.month - fr["obs_period"].dt.month)
        fr["is_true_first_release"] = gap_m <= win
        fr.to_parquet(T2_DIR / f"{name}_first_release.parquet", index=False)

        n_true = int(fr["is_true_first_release"].sum())
        rows.append({"series": name, "tier": 2, "n_obs": len(fr), "n_true_first_release": n_true,
                     "first_vintage": str(min(vdates.values()).date()),
                     "last_vintage": str(max(vdates.values()).date()), "desc": desc})
        print(f"  tier2 {name:8s} obs={len(fr):5d} true_first_releases={n_true:4d} vintages {min(vdates.values()).date()} .. {max(vdates.values()).date()}")
    return rows


def build_revised_reference() -> None:
    REF_DIR.mkdir(parents=True, exist_ok=True)
    for sid in REVISED_REF:
        df = pd.read_csv(io.BytesIO(_get(FRED_CSV.format(sid=sid))))
        df.columns = ["obs_date", "value"]
        df["obs_date"] = pd.to_datetime(df["obs_date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df.dropna(subset=["value"]).to_parquet(REF_DIR / f"{sid}_current.parquet", index=False)
        print(f"  ref   {sid:10s} snapshot of TODAY'S revised series (NOT PIT; checks only)")


def build() -> int:
    LAKE.mkdir(parents=True, exist_ok=True)
    print("== TIER 1: FRED keyless daily (unrevised market-based) ==")
    t1 = build_tier1()
    print("== TIER 2: Philly Fed RTDSM first-release vintages ==")
    t2 = build_tier2()
    print("== revised-reference snapshots (honesty checks only) ==")
    build_revised_reference()
    inventory = sorted(str(p.relative_to(LAKE)) for p in LAKE.rglob("*.parquet"))
    meta = {
        "built_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "tier1_rule": "publication_date = obs_date + 1 business day",
        "tier2_rule": "publication_date = vintage date of FIRST RTDSM vintage containing the obs (monthly vintage = 15th of vintage month; quarterly = 15th of quarter's middle month). RTDSM guarantees values were publicly known ON the vintage date.",
        "series": t1 + t2,
        "excluded": {
            "real_retail_sales": "no RTDSM variable; no ALFRED key in env; RCONM stored as consumer-demand substitute",
            "copper_spot": "no keyless unrevised daily source (FRED copper is monthly IMF, revised); DBC/DBA ETF closes in lake_mf are the commodity fallback",
        },
        "files": {f: hashlib.sha256((LAKE / f).read_bytes()).hexdigest()[:16] for f in inventory},
    }
    (LAKE / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"\nlake written: {LAKE}  ({len(inventory)} parquet files)")
    return 0


# ---------------------------------------------------------------------------
# Reader API (PIT)
# ---------------------------------------------------------------------------
_CACHE: dict[str, pd.DataFrame] = {}


def _load(key: str, path: Path) -> pd.DataFrame:
    if key not in _CACHE:
        _CACHE[key] = pd.read_parquet(path)
    return _CACHE[key]


def _table(series: str) -> pd.DataFrame:
    """Uniform (obs, value, publication_date) table for a series."""
    if series in TIER1:
        df = _load(f"t1:{series}", T1_DIR / f"{series}.parquet")
        return df.rename(columns={"obs_date": "obs_period", "value": "value_first_release"})
    if series in TIER2:
        return _load(f"t2fr:{series}", T2_DIR / f"{series}_first_release.parquet")
    raise KeyError(f"unknown series {series!r}; known: {sorted(TIER1) + sorted(TIER2)}")


def as_of_full(series: str, date) -> tuple[pd.Timestamp, float, pd.Timestamp] | None:
    """(obs_period, value, publication_date) of the latest value published <= date."""
    date = pd.Timestamp(date)
    df = _table(series)
    known = df[df["publication_date"] <= date]
    if known.empty:
        return None
    row = known.loc[known["obs_period"].idxmax()]
    return (pd.Timestamp(row["obs_period"]), float(row["value_first_release"]), pd.Timestamp(row["publication_date"]))


def as_of(series: str, date) -> float | None:
    """Latest value of `series` whose PUBLICATION date <= date (the contract's reader)."""
    r = as_of_full(series, date)
    return None if r is None else r[1]


def history_asof(series: str, date) -> pd.DataFrame:
    """All (obs_period, value, publication_date) rows published <= date.
    Tier 2 rows are FIRST-RELEASE values: fine for 'latest print' features; for growth
    rates over time use vintage_asof (a single internally-consistent vintage)."""
    date = pd.Timestamp(date)
    df = _table(series)
    return df[df["publication_date"] <= date].reset_index(drop=True)


def vintage_asof(series: str, date) -> pd.Series | None:
    """Tier 2: the full latest vintage available at `date` (index=obs_period).
    This is the correct PIT object for computing growth rates (m/m, yoy) because a
    single vintage is internally consistent (same benchmark/seasonals)."""
    if series not in TIER2:
        raise KeyError(f"vintage_asof is tier-2 only; {series!r} is not tier 2")
    date = pd.Timestamp(date)
    long = _load(f"t2v:{series}", T2_DIR / f"{series}_vintage_long.parquet")
    avail = long[long["vintage_date"] <= date]
    if avail.empty:
        return None
    v = avail[avail["vintage_date"] == avail["vintage_date"].max()]
    return v.set_index("obs_period")["value"].sort_index()


def list_series() -> pd.DataFrame:
    meta = json.loads((LAKE / "meta.json").read_text())
    return pd.DataFrame(meta["series"])


# ---------------------------------------------------------------------------
# Verify: proof-of-honesty spot-checks
# ---------------------------------------------------------------------------

def _ref(sid: str) -> pd.Series:
    df = _load(f"ref:{sid}", REF_DIR / f"{sid}_current.parquet")
    return df.set_index("obs_date")["value"]


def verify() -> int:
    print("=========== PIT VINTAGE LAKE — HONESTY SPOT-CHECKS ===========")
    ok = True

    # --- Episode 1: COVID payrolls, April 2020 ---
    fr = _table("EMPLOY")
    row = fr[fr["obs_period"] == "2020-04-01"].iloc[0]
    cur = _ref("PAYEMS").get(pd.Timestamp("2020-04-01"))
    print("\n[1] EMPLOY (nonfarm payrolls) 2020-04 — the COVID print")
    print(f"    first release (pub {row['publication_date'].date()}): {row['value_first_release']:,.0f}k")
    print(f"    today's revised PAYEMS                     : {cur:,.0f}k")
    print(f"    revision                                    : {cur - row['value_first_release']:+,.0f}k")
    if abs(cur - row["value_first_release"]) < 100:
        ok = False
        print("    !! FAIL: vintage equals revised — plumbing suspect")
    # PIT reader behavior around the release
    v_before = as_of_full("EMPLOY", "2020-05-14")
    v_after = as_of_full("EMPLOY", "2020-05-15")
    print(f"    as_of 2020-05-14 -> obs {v_before[0].date()} = {v_before[1]:,.0f}k (Apr print NOT yet usable)")
    print(f"    as_of 2020-05-15 -> obs {v_after[0].date()} = {v_after[1]:,.0f}k")
    if v_before[0] >= pd.Timestamp("2020-04-01"):
        ok = False
        print("    !! FAIL: April 2020 print visible before its vintage date")

    # --- Episode 2: CPI Dec-2022 (Feb-2023 seasonal-factor revision flipped m/m sign) ---
    print("\n[2] PCPI (headline CPI) 2022-12 m/m — seasonal-revision episode")
    v = vintage_asof("PCPI", "2023-01-20")  # vintage 2023-01-15: first containing Dec-22
    mm_fr = (v.loc["2022-12-01"] / v.loc["2022-11-01"] - 1) * 100
    cur_cpi = _ref("CPIAUCSL")
    mm_now = (cur_cpi["2022-12-01"] / cur_cpi["2022-11-01"] - 1) * 100
    frow = fr = _table("PCPI")
    frow = fr[fr["obs_period"] == "2022-12-01"].iloc[0]
    print(f"    first-release vintage (pub {frow['publication_date'].date()}): level {frow['value_first_release']:.3f}, m/m {mm_fr:+.2f}%")
    print(f"    today's revised CPIAUCSL                    : level {cur_cpi['2022-12-01']:.3f}, m/m {mm_now:+.2f}%")
    print(f"    m/m revision                                 : {mm_now - mm_fr:+.2f}pp")
    if abs(mm_now - mm_fr) < 1e-9:
        ok = False
        print("    !! FAIL: no revision visible — plumbing suspect")

    # --- Episode 3: IPT base-year rebasing (levels not comparable across vintages) ---
    print("\n[3] IPT (industrial production) 2010-06 — benchmark/base-year revisions")
    fr = _table("IPT")
    row = fr[fr["obs_period"] == "2010-06-01"].iloc[0]
    cur = _ref("INDPRO").get(pd.Timestamp("2010-06-01"))
    print(f"    first release (pub {row['publication_date'].date()}): {row['value_first_release']:.2f} (2007=100 era)")
    print(f"    today's revised INDPRO                      : {cur:.2f} (2017=100 base)")
    print("    -> levels differ by construction; growth must be computed WITHIN one vintage (vintage_asof)")

    # --- tier-1 lag sanity ---
    print("\n[4] Tier-1 publication lag (DGS10)")
    t1 = _table("DGS10")
    bad = (t1["publication_date"] <= t1["obs_period"]).sum()
    print(f"    rows with pub <= obs: {bad} (must be 0); e.g. obs {t1['obs_period'].iloc[-1].date()} -> usable {t1['publication_date'].iloc[-1].date()}")
    if bad:
        ok = False

    # --- global no-leak invariant across all tier-2 series ---
    print("\n[5] Global invariant: every tier-2 true-first-release pub date >= obs month end")
    for name in TIER2:
        df = _table(name)
        tfr = df[df["is_true_first_release"]]
        leaks = (tfr["publication_date"] <= tfr["obs_period"] + pd.offsets.MonthEnd(0)).sum()
        gap = (tfr["publication_date"] - tfr["obs_period"]).dt.days
        print(f"    {name:8s} leaks={leaks}  median pub lag from obs-month start = {gap.median():.0f}d")
        if leaks:
            ok = False

    print("\nresult:", "ALL CHECKS PASS — the lake is point-in-time" if ok else "!! FAILURES — do not use")
    return 0 if ok else 1


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if cmd == "build":
        raise SystemExit(build())
    if cmd == "verify":
        raise SystemExit(verify())
    print(__doc__)
    raise SystemExit(2)
