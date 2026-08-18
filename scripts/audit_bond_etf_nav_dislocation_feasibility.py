#!/usr/bin/env python3
"""Audit bond-ETF NAV-dislocation sources without opening market or return data."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import exchange_calendars as xcals
import httpx
import pandas as pd

OUT_DIR: Final = Path("artifacts/feasibility/bond_etf_nav_dislocation")
CACHE_DIR: Final = Path("data/raw/bond_etf_nav_dislocation")
START: Final = pd.Timestamp("2016-01-01")
END: Final = pd.Timestamp("2025-12-31")
UA: Final = "Canli Capital quantitative research arhancanli@icloud.com"
PRODUCTS: Final = (
    {
        "ticker": "HYG",
        "portfolio_id": 239565,
        "slug": "ishares-iboxx-high-yield-corporate-bond-etf",
    },
    {
        "ticker": "LQD",
        "portfolio_id": 239566,
        "slug": "ishares-iboxx-investment-grade-corporate-bond-etf",
    },
)
TRACE_URL: Final = "https://www.finra.org/industry/trace-historic-academic-data"


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cached_get(client: httpx.Client, url: str, path: Path) -> tuple[bytes, bool]:
    if path.exists():
        return gzip.decompress(path.read_bytes()), True
    response = client.get(url)
    response.raise_for_status()
    raw = response.content
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(raw, compresslevel=6, mtime=0))
    return raw, False


def extract_balanced_object(text: str, key: str) -> dict[str, Any]:
    marker = f'"{key}":'
    marker_index = text.find(marker)
    if marker_index < 0:
        raise ValueError(f"missing embedded key: {key}")
    start = text.find("{", marker_index + len(marker))
    if start < 0:
        raise ValueError(f"missing object for embedded key: {key}")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : index + 1])
    raise ValueError(f"unterminated object for embedded key: {key}")


def parse_premium_discount(raw: bytes, ticker: str) -> pd.DataFrame:
    text = html.unescape(raw.decode("utf-8", errors="replace"))
    payload = extract_balanced_object(text, "premiumDiscountChartData")
    dates = payload.get("asOfDate") or []
    values = payload.get("value") or payload.get("formattedValue") or []
    if len(dates) != len(values):
        raise ValueError(f"{ticker}: premium/discount date/value length mismatch")
    frame = pd.DataFrame(
        {
            "ticker": ticker,
            "as_of_date": pd.to_datetime([str(value) for value in dates], format="%Y%m%d"),
            "issuer_premium_discount_percent": pd.to_numeric(values, errors="coerce"),
        }
    )
    if (
        frame["as_of_date"].duplicated().any()
        or frame["issuer_premium_discount_percent"].isna().any()
    ):
        raise ValueError(f"{ticker}: invalid premium/discount observations")
    return frame.sort_values("as_of_date").reset_index(drop=True)


def parse_holdings_header(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8-sig", errors="replace")
    match = re.search(r'^Fund Holdings as of,"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise ValueError("holdings file lacks an as-of header")
    header_line = next(
        (
            line
            for line in text.splitlines()
            if "CUSIP" in line and "Weight (%)" in line
        ),
        "",
    )
    return {
        "as_of_text": match.group(1),
        "has_cusip": "CUSIP" in header_line,
        "has_weight": "Weight (%)" in header_line,
        "has_quantity": "Quantity" in header_line or "Par Value" in header_line,
        "header_line": header_line,
    }


def run(out_dir: Path, cache_dir: Path) -> dict[str, Any]:
    client = httpx.Client(
        headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"},
        follow_redirects=True,
        timeout=60.0,
    )
    premium_frames: list[pd.DataFrame] = []
    source_rows: list[dict[str, Any]] = []
    try:
        for product in PRODUCTS:
            ticker = str(product["ticker"])
            root = (
                f"https://www.ishares.com/us/products/{product['portfolio_id']}/"
                f"{product['slug']}"
            )
            page_raw, page_cached = cached_get(
                client, root, cache_dir / f"{ticker.lower()}_product_page.html.gz"
            )
            premium = parse_premium_discount(page_raw, ticker)
            premium_frames.append(premium)
            source_rows.append(
                {
                    "ticker": ticker,
                    "source_type": "issuer_product_page",
                    "url": root,
                    "http_content_opened": True,
                    "market_records_opened": 0,
                    "cached": page_cached,
                    "sha256": sha256_bytes(page_raw),
                    "bytes": len(page_raw),
                    "available": True,
                }
            )

            holdings_url = f"{root}/latest-holdings.csv"
            holdings_raw, holdings_cached = cached_get(
                client,
                holdings_url,
                cache_dir / f"{ticker.lower()}_latest_holdings.csv.gz",
            )
            holdings = parse_holdings_header(holdings_raw)
            source_rows.append(
                {
                    "ticker": ticker,
                    "source_type": "latest_holdings_only",
                    "url": holdings_url,
                    "http_content_opened": True,
                    "market_records_opened": 0,
                    "cached": holdings_cached,
                    "sha256": sha256_bytes(holdings_raw),
                    "bytes": len(holdings_raw),
                    "available": True,
                    **holdings,
                }
            )

        trace_raw, trace_cached = cached_get(
            client, TRACE_URL, cache_dir / "finra_trace_historical_info.html.gz"
        )
    finally:
        client.close()

    trace_text = re.sub(
        r"\s+", " ", html.unescape(trace_raw.decode("utf-8", errors="replace"))
    ).lower()
    trace_agreement = "historical data agreement" in trace_text
    trace_fees = "pay applicable fees" in trace_text or "applicable fees" in trace_text
    source_rows.append(
        {
            "ticker": None,
            "source_type": "finra_trace_historical_metadata",
            "url": TRACE_URL,
            "http_content_opened": True,
            "market_records_opened": 0,
            "cached": trace_cached,
            "sha256": sha256_bytes(trace_raw),
            "bytes": len(trace_raw),
            "available": True,
            "agreement_required": trace_agreement,
            "fees_required": trace_fees,
        }
    )

    premium_manifest = pd.concat(premium_frames, ignore_index=True)
    source_manifest = pd.DataFrame(source_rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    premium_path = out_dir / "issuer_premium_discount_manifest.parquet"
    source_path = out_dir / "source_probe_manifest.parquet"
    premium_manifest.to_parquet(premium_path, index=False)
    source_manifest.to_parquet(source_path, index=False)

    sessions = xcals.get_calendar("XNYS").sessions_in_range(START, END)
    expected_sessions = len(sessions)
    coverage: dict[str, Any] = {}
    for product in PRODUCTS:
        ticker = str(product["ticker"])
        dates = premium_manifest.loc[
            premium_manifest["ticker"].eq(ticker), "as_of_date"
        ]
        in_period = dates[(dates >= START) & (dates <= END)]
        unique_dates = int(in_period.nunique())
        coverage[ticker] = {
            "expected_xnys_sessions": expected_sessions,
            "issuer_dates_in_period": unique_dates,
            "coverage": unique_dates / expected_sessions,
            "first_available": dates.min().date().isoformat() if len(dates) else None,
            "last_available": dates.max().date().isoformat() if len(dates) else None,
        }

    premium_gate = all(item["coverage"] >= 0.98 for item in coverage.values())
    holdings_snapshots = dict.fromkeys(("HYG", "LQD"), 1)
    holdings_gate = all(value >= 120 for value in holdings_snapshots.values())
    trace_contract_available = trace_agreement and trace_fees
    gates = {
        "issuer_premium_discount_coverage_at_least_98pct_each": premium_gate,
        "monthly_historical_holdings_120_each": holdings_gate,
        "trace_transaction_route_contractually_available": trace_contract_available,
        "constituent_valuation_timestamps_available": False,
        "synchronized_etf_and_bond_execution_data_available": False,
    }
    decision = "PASS_TO_LICENSED_DATA_PREREGISTRATION" if all(gates.values()) else "DATA_GATED"
    result = {
        "schema": "canli.feasibility.bond-etf-nav-dislocation.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "official_source_metadata_no_market_records_no_returns",
        "decision": decision,
        "return_data_opened": False,
        "market_data_opened": False,
        "market_records_opened": 0,
        "return_hypotheses_spent": 0,
        "protocol": "docs/design/FEASIBILITY_BOND_ETF_NAV_DISLOCATION.md",
        "protocol_sha256": sha256_file(
            Path("docs/design/FEASIBILITY_BOND_ETF_NAV_DISLOCATION.md")
        ),
        "literature_review": "docs/design/LITERATURE_BOND_ETF_NAV_DISLOCATION.md",
        "funds": [str(product["ticker"]) for product in PRODUCTS],
        "research_period": ["2016-01-01", "2025-12-31"],
        "premium_discount_coverage": coverage,
        "historical_holdings_snapshots": holdings_snapshots,
        "required_historical_holdings_snapshots_each": 120,
        "trace_metadata": {
            "agreement_required": trace_agreement,
            "fees_required": trace_fees,
            "transaction_records_requested": 0,
        },
        "gates": gates,
        "artifacts": {
            "issuer_premium_discount_manifest": {
                "path": str(premium_path),
                "sha256": sha256_file(premium_path),
                "rows": len(premium_manifest),
            },
            "source_probe_manifest": {
                "path": str(source_path),
                "sha256": sha256_file(source_path),
                "rows": len(source_manifest),
            },
        },
        "blocking_reasons": [name for name, passed in gates.items() if not passed],
        "claim_boundary": (
            "Issuer NAV gaps cannot distinguish stale bond marks from ETF mispricing. No sign, "
            "threshold, return, Sharpe, drawdown, correlation, capacity, or admission claim exists."
        ),
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(json.dumps(run(args.out_dir, args.cache_dir), indent=2))


if __name__ == "__main__":
    main()
