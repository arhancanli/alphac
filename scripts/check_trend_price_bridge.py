"""Receipt-bound current-vintage bridge diagnostic; no strategy returns or lake writes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from alphaforge.validation.trend_observation import fingerprint, session_window
from alphaforge.validation.trend_price_bridge import (
    Action,
    ActionSnapshot,
    PriceState,
    advance_close,
)

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "evidence/alphatrend-action-capture-20260912"
OUT = ROOT / "evidence/alphatrend-price-bridge-20260912"
HISTORY = ROOT / "evidence/alphatrend-history-bridge-20260912"
FACTORS = ROOT / "evidence/alphatrend-adjustment-factors-20260912"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def ms(value):
    return int(pd.Timestamp(value, tz="UTC").value // 1_000_000)


def write(name, value):
    with (OUT / name).open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def snapshot(symbol):
    actions = []
    receipts = []
    for kind in ["splits", "dividends"]:
        stem = symbol + "_" + kind
        request = json.loads((CAP / (stem + "_request.json")).read_text())
        receipt = json.loads((CAP / (stem + "_receipt.json")).read_text())
        raw = CAP / (stem + ".bin")
        assert sha(raw) == receipt["sha256"] and receipt["http_status"] == 200
        body = json.loads(raw.read_bytes())
        assert body["status"] == "OK" and not body.get("next_url")
        assert isinstance(body["results"], list)
        field = "execution_date" if kind == "splits" else "ex_dividend_date"
        assert request["path"] == "/v3/reference/" + kind
        assert request["params"] == {
            "ticker": symbol,
            field + ".gte": "2026-05-01",
            field + ".lte": "2026-09-11",
            "limit": 1000,
        }
        receipts.append(receipt)
        for row in body["results"]:
            assert row["ticker"] == symbol
            if kind == "dividends":
                assert row["currency"] == "USD" and row["dividend_type"] in {"CD", "SC"}
                value = row["cash_amount"]
            else:
                assert row["split_from"] > 0 and row["split_to"] > 0
                value = row["split_to"] / row["split_from"]
            actions.append(
                Action(
                    row["id"],
                    symbol,
                    ms(row[field]),
                    "split" if kind == "splits" else "dividend",
                    value,
                )
            )
    return ActionSnapshot(
        symbol,
        ms("2026-05-01"),
        ms("2026-09-12"),
        max(int(pd.Timestamp(r["received_at_local"]).value // 1_000_000) for r in receipts),
        fingerprint(receipts),
        True,
        tuple(actions),
    )


def trajectory(symbol, frame, anchor, snap):
    state = anchor
    results = []
    for row in frame.sort_values("session_ms").itertuples():
        if row.session_ms <= anchor.session_ms:
            continue
        state = advance_close(
            state,
            session_ms=int(row.session_ms),
            raw_close=float(row.close),
            snapshot=snap,
            decision_ms=session_window(int(row.session_ms))[0] + 1,
            mode="DIAGNOSTIC_CURRENT_VINTAGE",
        )
        results.append(
            {
                "symbol": symbol,
                "session_ms": state.session_ms,
                "raw_close": state.raw_close,
                "signal_close": state.signal_close,
            }
        )
    return results


def main():
    OUT.mkdir(exist_ok=False)
    files = [
        *sorted(CAP.glob("*.json")),
        *sorted(CAP.glob("*.bin")),
        HISTORY / "raw_history.parquet",
        HISTORY / "overlap.parquet",
        FACTORS / "overlap.parquet",
        FACTORS / "raw_history.parquet",
        Path(__file__),
        ROOT / "src/alphaforge/validation/trend_price_bridge.py",
    ]
    bindings = {str(p): sha(p) for p in files}
    write(
        "protocol.json",
        {
            "mode": "DIAGNOSTIC_CURRENT_VINTAGE",
            "bridge_version": "forward_close_reinvestment_v1",
            "new_hypotheses": 0,
            "union_hypotheses": 238,
            "strategy_return_measurements": 0,
            "bindings": bindings,
        },
    )
    raw = pd.read_parquet(HISTORY / "raw_history.parquet")
    overlap = pd.read_parquet(HISTORY / "overlap.parquet")
    extension = []
    for symbol, part in raw.groupby("symbol"):
        last = overlap[overlap.symbol == symbol].sort_values("session_ms").iloc[-1]
        anchor = PriceState(
            symbol, int(last.session_ms), float(last.close_sip), float(last.close_lake)
        )
        extension.extend(trajectory(symbol, part, anchor, snapshot(symbol)))
    extended = pd.DataFrame(extension)
    assert len(extended) == 238 and extended.groupby("symbol").size().eq(14).all()
    extended.to_parquet(OUT / "diagnostic_extension.parquet", index=False)
    treasury = pd.read_parquet(FACTORS / "overlap.parquet")
    treasury_raw = pd.read_parquet(FACTORS / "raw_history.parquet")
    comparisons = []
    summaries = []
    for symbol, part in treasury.groupby("symbol"):
        part = part.sort_values("session_ms")
        first = part.iloc[0]
        anchor = PriceState(
            symbol, int(first.session_ms), float(first.close_raw), float(first.close_lake)
        )
        rebuilt = pd.DataFrame(
            trajectory(
                symbol, treasury_raw[treasury_raw.symbol == symbol], anchor, snapshot(symbol)
            )
        )
        joined = rebuilt.merge(
            part[["session_ms", "close_lake"]], on="session_ms", validate="one_to_one"
        )
        joined["level_difference_bps"] = (joined.signal_close / joined.close_lake - 1) * 10000
        comparisons.append(joined)
        summaries.append(
            {
                "symbol": symbol,
                "sessions": len(joined),
                "max_absolute_level_difference_bps": float(joined.level_difference_bps.abs().max()),
                "exact_yahoo_parity": bool(joined.signal_close.equals(joined.close_lake)),
            }
        )
    pd.concat(comparisons).to_parquet(OUT / "treasury_comparison.parquet", index=False)
    result = {
        "extended_rows": len(extended),
        "symbols": 17,
        "sessions": 14,
        "treasury_parity": summaries,
        "runtime_ready": False,
        "historical_publication_time_proven": False,
        "remaining": [
            "Yahoo adjustment semantics and numerical parity",
            "Point-in-time input provenance",
            "OHLC and open-label mapping",
            "Clock and producer binding",
            "Account and execution state",
        ],
        "new_hypotheses": 0,
        "union_hypotheses": 238,
    }
    for path, digest in bindings.items():
        assert sha(Path(path)) == digest
    write("result.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
