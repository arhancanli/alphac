"""The cost-charged curve is the broker curve less exactly the charges, and no charge can vanish.

WHY. The equity paper-live NAV charged nothing; the repair charges every fill and the short book
through research's own cost model and publishes the result beside the broker NAV. These tests
recompute every charge independently from the same fills and bars (commission and spread as
bps of notional, impact by the square-root law, borrow on the reconstructed short book), so a
component the derivation dropped or double-counted fails by name; check that the published
charged curve sits at or below the broker curve and differs from it by the cumulative charges
rebased; check that the publish gate iterates the new curve; and check that the contract's rows
carry only declared statuses and the model's parameters are research's own, never typed.

Pure: a synthetic fill table and daily-bar lake in a temporary tree.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from alphaforge.config.settings import load_settings
from alphaforge.validation.publish_gate import check_published_state

REPO = Path(__file__).resolve().parents[2]


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DERIVE = _load("derive_cost_charged_live_curves")
PTS = _load("paper_trading_state")

DAY_MS = 86_400_000
FIRST = pd.Timestamp("2026-01-05", tz="UTC")


def _ms(day: int, hour: int = 15) -> int:
    return int((FIRST + pd.Timedelta(days=day, hours=hour)).timestamp() * 1000)


def _bars(root: Path, symbol: str, days: int, price: float, volume: float) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    closes = price * np.exp(np.cumsum(rng.normal(0.0, 0.01, days)))
    frame = pd.DataFrame(
        {
            "ts_open": [FIRST + pd.Timedelta(days=d) for d in range(days)],
            "close": closes,
            "quote_volume": np.full(days, volume),
        }
    )
    out = root / f"instrument_id=XUSE:CASH:{symbol}USD" / "year=2026"
    out.mkdir(parents=True)
    frame.to_parquet(out / "data.parquet", index=False)
    return frame


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    repo = tmp_path / "engine"
    (repo / "var").mkdir(parents=True)
    lake = repo / "lake"
    bars = _bars(lake, "AAA", 120, 10.0, 1_000_000.0)
    db = repo / "var" / "trading_equity.sqlite"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE fills (client_order_id TEXT PRIMARY KEY, broker_order_id TEXT, ts INTEGER, "
        "submitted_ts INTEGER, instrument_id TEXT, side TEXT, status TEXT, submitted_qty REAL, "
        "filled_qty REAL, limit_price REAL, fill_price REAL, notional REAL)"
    )
    con.execute("CREATE TABLE equity_curve (ts INTEGER PRIMARY KEY, equity_quote REAL)")
    fills = [
        ("o1", _ms(60), "AAA", "buy", 100.0, 10.0),  # long 100
        ("o2", _ms(61), "AAA", "sell", 300.0, 10.0),  # short 200 from day 61
        ("o3", _ms(62), "BBB", "buy", 50.0, 20.0),  # no bars: unpriced for impact
        ("o4", _ms(63), "AAA", "buy", 8_000.0, 10.0),  # 8% of ADV: floored at the tripwire
        ("o5", _ms(64), "AAA", "buy", 1.0, 10.0),  # expired: not a fill
    ]
    for oid, ts, sym, side, qty, px in fills:
        status = "expired" if oid == "o5" else "filled"
        con.execute(
            "INSERT INTO fills VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                oid,
                oid,
                ts,
                ts - 1000,
                sym,
                side,
                status,
                qty,
                qty if status == "filled" else 0.0,
                px,
                px,
                qty * px,
            ),
        )
    for day in range(58, 70):
        con.execute(
            "INSERT INTO equity_curve VALUES (?, ?)", (_ms(day, 20), 1_000_000.0 + 100.0 * day)
        )
    con.commit()
    con.close()
    monkeypatch.setattr(DERIVE, "REPO", repo)
    monkeypatch.setattr(DERIVE, "LAKES", (lake,))
    return {"repo": repo, "bars": bars, "db": db}


def _expected(tree: dict[str, Any]) -> dict[str, float]:
    """Independent recomputation of every charge from the same fills and bars."""
    cfg = load_settings("equity").costs
    bars = tree["bars"].copy()
    bars["date"] = bars["ts_open"].dt.strftime("%Y-%m-%d")
    bars = bars.set_index("date")
    bars["ret"] = np.log(bars["close"]).diff()

    def stats(date: str) -> tuple[float, float]:
        prior = bars.loc[bars.index < date]
        adv = float(prior["quote_volume"].tail(30).median())
        sigma = float(prior["ret"].dropna().ewm(halflife=240).std().iloc[-1])
        return adv, sigma

    commission = spread = impact = 0.0
    for day, notional, symbol in (
        (60, 1000.0, "AAA"),
        (61, 3000.0, "AAA"),
        (62, 1000.0, "BBB"),
        (63, 80_000.0, "AAA"),
    ):
        commission += notional * cfg.equity_commission_bps * 1e-4
        spread += notional * cfg.equity_half_spread_bps * 1e-4
        if symbol == "AAA":
            adv, sigma = stats((FIRST + pd.Timedelta(days=day)).strftime("%Y-%m-%d"))
            charged = min(notional, 0.05 * adv)
            impact += notional * cfg.impact_coef * sigma * math.sqrt(charged / adv)
    # short 200 shares from day 61 through day 62 inclusive; flat again from day 63's buy
    borrow = 0.0
    for day in (61, 62):
        mark = float(bars["close"].iloc[day])
        borrow += 200.0 * mark * cfg.equity_borrow_bps_annual * 1e-4 / 365.0
    return {"commission": commission, "spread": spread, "impact": impact, "borrow": borrow}


def test_every_charge_reconciles_to_an_independent_recomputation(tree: dict[str, Any]) -> None:
    sleeve = DERIVE.charge_sleeve("alphamax", "equity")
    expected = _expected(tree)
    for component, value in expected.items():
        # totals are published rounded to the cent
        assert sleeve["totals_usd"][component] == pytest.approx(value, abs=0.0051), component
    assert sleeve["fills_total"] == 4
    assert sleeve["fills_unpriced_for_impact"] == 1
    assert sleeve["unpriced_fills"][0]["symbol"] == "BBB"
    assert sleeve["fills_impact_floored_at_tripwire"] == 1
    assert sleeve["short_calendar_days_charged"] == 2
    series = sleeve["charges_by_date"]
    running = 0.0
    for date in sorted(series):
        row = series[date]
        assert row["total"] == pytest.approx(
            row["commission"] + row["spread"] + row["impact"] + row["borrow"], abs=1e-9
        )
        running += row["total"]
        assert row["cumulative"] == pytest.approx(running, abs=1e-6)
    assert (
        sleeve["model"]["equity_commission_bps"]
        == load_settings("equity").costs.equity_commission_bps
    )


def test_the_charged_curve_is_the_broker_curve_less_the_charges_rebased(
    tree: dict[str, Any],
) -> None:
    sleeve = DERIVE.charge_sleeve("alphamax", "equity")
    go_live = (FIRST + pd.Timedelta(days=58)).strftime("%Y-%m-%d")
    raw = PTS.read_live_db(tree["db"], go_live=go_live)
    charged = PTS.read_live_db(tree["db"], go_live=go_live, charges=sleeve["charges_by_date"])
    assert [p["date"] for p in raw] == [p["date"] for p in charged]
    assert charged[0]["equity"] == raw[0]["equity"] == 100000.0
    base = PTS._raw_first_mark(tree["db"], go_live)
    for r, c in zip(raw, charged, strict=True):
        assert c["equity"] <= r["equity"] + 1e-9
        cumulative = PTS._cumulative_charge_through(sleeve["charges_by_date"], c["date"])
        assert r["equity"] - c["equity"] == pytest.approx(100000.0 * cumulative / base, abs=0.011)
    assert charged[-1]["equity"] < raw[-1]["equity"]


def test_the_publish_gate_iterates_the_cost_charged_curve() -> None:
    state = {
        "algorithms": [
            {
                "name": "AlphaMax",
                "live_curve": [
                    {"date": "2026-01-01", "equity": 100000.0},
                    {"date": "2026-01-02", "equity": 100100.0},
                ],
                "cost_charged_curve": [
                    {"date": "2026-01-01", "equity": 100000.0},
                    {"date": "2026-01-02", "equity": 0.0},
                ],
            }
        ]
    }
    report = check_published_state(state)
    assert any(v.where == "AlphaMax.cost_charged_curve" for v in report.violations)


def test_the_contract_declares_only_known_statuses_and_research_parameters() -> None:
    contract = json.loads((REPO / "config" / "cost_realism_contract.json").read_text())
    statuses = set(contract["statuses"])
    for section in ("equity_paper_live", "crypto_paper_live"):
        for name, row in contract[section]["rows"].items():
            assert row["status"] in statuses, name
            if row["status"] == "NOT_CHARGED":
                assert row["reason"], name
    equity_rows = contract["equity_paper_live"]["rows"]
    assert equity_rows["commission"]["status"] == "CHARGED_BY_MODEL"
    assert equity_rows["short_borrow"]["status"] == "CHARGED_BY_MODEL"
    assert equity_rows["latency_slippage"]["status"] == "NOT_CHARGED"
    # the change is declared, as an accounting change that does not restart the epoch
    live_change = json.loads((REPO / "config" / "live_change_contract.json").read_text())
    entry = next(
        e for e in live_change["change_log"] if e["change"].startswith("cost realism v1.0")
    )
    assert entry["contaminates_forward_record"] is False
    assert "config/cost_realism_contract.json" in entry["evidence"]
