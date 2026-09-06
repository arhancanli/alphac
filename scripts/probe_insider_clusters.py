#!/usr/bin/env python3
"""One-shot OOS probe for the pre-registered clustered-insider-purchase sleeve.

No grid exists in this file. The signal, timing, holding period, costs, hedge and gates are read
from docs/design/PREREG_INSIDER_CLUSTERS.md and asserted before prices are loaded. The full OOS
curve is persisted whether the verdict is ADD or KILL and the one hypothesis enters the shared
experiment ledger exactly once.
"""

from __future__ import annotations

import glob
import hashlib
import json
import math
import sys
from collections import deque
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
_SCRIPTS = _ROOT / "scripts"
for _path in (_SRC, _SCRIPTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from lib.px_adjust import adjusted_log_returns, load_actions  # noqa: E402

from alphaforge.analytics.curve_store import read_curve, write_curve  # noqa: E402
from alphaforge.validation.dsr import dsr_from_returns  # noqa: E402
from alphaforge.validation.experiments import hypothesis_hash  # noqa: E402
from alphaforge.validation.prereg import assert_matches  # noqa: E402
from alphaforge.validation.probe_ledger import record_probe_trial, selection_context  # noqa: E402

PREREG: Final[Path] = Path("docs/design/PREREG_INSIDER_CLUSTERS.md")
EVENT_GLOB: Final[str] = "data/lake_insider/year=*/quarter=*/events.parquet"
EQUITY_PRICE_ROOT: Final[Path] = Path("data/lake_sharadar/ohlcv_1d")
SPY_PRICE_ROOT: Final[Path] = Path("data/lake_mf/ohlcv_1d")
CORPORATE_ACTION_ROOT: Final[Path] = Path("data/lake_sharadar/corporate_actions")
OUT: Final[Path] = Path("artifacts/probe/insider_purchase_clusters")
INPUT_MANIFEST: Final[Path] = OUT / "input_data_manifest.json"
RUNNER: Final[Path] = Path(__file__).resolve()
PYPROJECT: Final[Path] = Path("pyproject.toml")
UV_LOCK: Final[Path] = Path("uv.lock")
ADMISSION_CONTRACT: Final[Path] = Path("config/sleeve_admission_contract.json")
OOS_START: Final[pd.Timestamp] = pd.Timestamp("2016-01-01")
CLUSTER_DAYS: Final[int] = 30
MIN_INSIDERS: Final[int] = 2
MIN_VALUE: Final[float] = 100_000.0
HOLD_SESSIONS: Final[int] = 63
FILING_DELAY_SESSIONS: Final[int] = 2
PRICE_FLOOR: Final[float] = 5.0
ADV_FLOOR: Final[float] = 5_000_000.0
ISSUER_COST: Final[float] = 0.0006
SPY_COST: Final[float] = 0.0001
ANN: Final[int] = 252
SPY: Final[str] = "SPY"
SLEEVE_CURVES: Final[dict[str, str]] = {
    "AlphaForge": "artifacts/walkforward/crypto_carry_wk/equity.parquet",
    "AlphaMax": "artifacts/walkforward/k30_dn_63/equity.parquet",
    "AlphaTrend": "artifacts/walkforward/managed_futures/equity.parquet",
    "AlphaVintage": "artifacts/probe/cpi_surprise_size/equity.parquet",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def trial_configuration() -> dict[str, object]:
    return {
        "mechanism": "clustered_form4_open_market_purchases",
        "cluster_days": CLUSTER_DAYS,
        "min_insiders": MIN_INSIDERS,
        "min_value": MIN_VALUE,
        "hold_sessions": HOLD_SESSIONS,
        "filing_delay_sessions": FILING_DELAY_SESSIONS,
        "hedge": "trailing_252d_spy_beta_clamped_0_3",
        "positioning": "equal_notional_gross_1",
        "return_aggregation": "weighted_simple_returns",
        "costs": {"issuer_oneway": ISSUER_COST, "spy_oneway": SPY_COST},
        "oos_start": str(OOS_START.date()),
    }


def market_frame_sha256(frame: pd.DataFrame) -> str:
    """Hash exact loaded market semantics, including timestamps and missingness."""
    ordered = frame[["open", "close", "volume"]].astype(float)
    values = ordered.to_numpy(dtype="<f8", copy=True)
    missing = np.isnan(values)
    values[missing] = 0.0
    digest = hashlib.sha256()
    digest.update(b"open\0close\0volume\n")
    digest.update(pd.DatetimeIndex(ordered.index).asi8.astype("<i8").tobytes())
    digest.update(missing.astype(np.uint8).tobytes())
    digest.update(values.tobytes())
    return digest.hexdigest()


def action_data_manifest(symbols: set[str]) -> dict[str, object]:
    actions = load_actions(symbols, ca_dir=CORPORATE_ACTION_ROOT, strict=True)
    if actions.empty:
        canonical = b"[]"
        start = end = None
    else:
        actions = actions.sort_values(
            ["symbol", "ex_date", "action_type", "ratio", "cash_amount"],
            na_position="first",
        ).reset_index(drop=True)
        canonical = actions.to_json(
            orient="records", date_format="iso", date_unit="ns", double_precision=15
        ).encode()
        start = str(actions["ex_date"].min().date())
        end = str(actions["ex_date"].max().date())
    return {
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "rows": len(actions),
        "start": start,
        "end": end,
        "symbols_with_actions": int(actions["symbol"].nunique()) if len(actions) else 0,
    }


def build_input_manifest(
    event_paths: list[Path],
    market_sources: dict[str, object],
    action_sources: dict[str, object],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "canli.insider-cluster-input-manifest.v1",
        "preregistration_path": str(PREREG),
        "preregistration_sha256": file_sha256(PREREG),
        "event_partitions": [
            {"path": str(path), "bytes": path.stat().st_size, "sha256": file_sha256(path)}
            for path in event_paths
        ],
        "market_data": market_sources,
        "corporate_actions": action_sources,
        "diversification_curves": {
            name: {"path": path, "sha256": file_sha256(Path(path))}
            for name, path in SLEEVE_CURVES.items()
        },
    }
    payload["content_hash"] = content_hash(payload)
    return payload


def reproduction_environment() -> dict[str, object]:
    return {
        "command": "uv run python scripts/probe_insider_clusters.py",
        "python": sys.version,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "pyproject_path": str(PYPROJECT),
        "pyproject_sha256": file_sha256(PYPROJECT),
        "uv_lock_path": str(UV_LOCK),
        "uv_lock_sha256": file_sha256(UV_LOCK),
        "runner_path": str(RUNNER.relative_to(_ROOT)),
        "runner_sha256": file_sha256(RUNNER),
    }


def admission_review(gates: dict[str, bool]) -> dict[str, object]:
    contract = json.loads(ADMISSION_CONTRACT.read_text())
    if contract.get("schema") != "canli.alphac-sleeve-admission-contract.v6":
        raise RuntimeError("unexpected sleeve admission contract schema")
    required = int(contract.get("evidence_checks_per_candidate", 0))
    if required != 85:
        raise RuntimeError("v6 sleeve admission contract must retain exactly 85 checks")
    return {
        "contract_schema": contract["schema"],
        "contract_path": str(ADMISSION_CONTRACT),
        "contract_sha256": file_sha256(ADMISSION_CONTRACT),
        "checks_required_for_technical_eligibility": required,
        "preregistered_research_checks": len(gates),
        "preregistered_research_checks_passed": sum(gates.values()),
        "status": "RESEARCH_SUBSET_FAILED",
        "technically_eligible": False,
        "claim_boundary": (
            "This corrected historical probe failed its preregistered research gates. Binding "
            "it to v6 does not retroactively change those gates or establish eligibility."
        ),
    }


def reconcile_ledger_measurement(record: Any, returns: pd.Series) -> dict[str, object]:
    """Distinguish an exact first-measurement replay from a later OOS extension."""
    observations = int(returns.notna().sum())
    sample_sharpe = sharpe(returns)
    population_sharpe = (
        sample_sharpe * math.sqrt(observations / (observations - 1))
        if observations > 1
        else 0.0
    )
    exact = observations == record.n_obs and math.isclose(
        population_sharpe,
        record.sharpe_ann,
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    return {
        "hypothesis_key": hypothesis_hash(record.config),
        "config_hash": record.config_hash,
        "immutable_first_measurement": {
            "observations": record.n_obs,
            "annualized_sharpe_population_std": record.sharpe_ann,
            "recorded_at_unix_ms": record.now_ms,
        },
        "current_replay": {
            "observations": observations,
            "annualized_sharpe_sample_std": sample_sharpe,
            "annualized_sharpe_population_std": population_sharpe,
        },
        "observation_delta": observations - record.n_obs,
        "exact_first_measurement_reproduced": exact,
        "relation": "EXACT_REPRODUCTION" if exact else "OOS_EXTENSION_NOT_EXACT_REPRODUCTION",
        "packet_completion_eligible": exact,
        "claim_boundary": (
            "A later replay on an advanced data lake may audit the unchanged implementation, "
            "but it cannot substitute for the exact curve behind the immutable first measurement."
        ),
    }


def load_events() -> pd.DataFrame:
    paths = sorted(glob.glob(EVENT_GLOB))
    if not paths:
        raise SystemExit("no insider lake; run scripts/ingest_insider_transactions.py")
    events = pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)
    events["filing_date"] = pd.to_datetime(events["filing_date"]).dt.normalize()
    events["transaction_date"] = pd.to_datetime(events["transaction_date"]).dt.normalize()
    # Negative lags are impossible as-of records. Exclude rather than reinterpret.
    events = events[events["filing_date"] >= events["transaction_date"]]
    return events[events["filing_date"] >= OOS_START].copy()


def build_cluster_dates(events: pd.DataFrame) -> pd.DataFrame:
    """Rolling 30-calendar-day clusters, one deterministic row per issuer/date."""
    rows: list[dict[str, object]] = []
    for issuer_cik, group in events.groupby("issuer_cik", sort=False):
        group = group.sort_values(["filing_date", "accession_number", "owner_cik"])
        window: deque[int] = deque()
        for idx in group.index:
            current = group.at[idx, "filing_date"]
            while window and group.at[window[0], "filing_date"] < current - pd.Timedelta(days=29):
                window.popleft()
            window.append(idx)
            snapshot = group.loc[list(window)]
            owners = int(snapshot["owner_cik"].nunique())
            value = float(snapshot["purchase_value_usd"].sum())
            if owners < MIN_INSIDERS or value < MIN_VALUE:
                continue
            latest = snapshot.iloc[-1]
            rows.append(
                {
                    "issuer_cik": str(issuer_cik),
                    "filing_date": current,
                    "ticker": str(latest["ticker"]).strip().upper(),
                    "distinct_insiders": owners,
                    "purchase_value_usd": value,
                }
            )
    if not rows:
        return pd.DataFrame(columns=["issuer_cik", "filing_date", "ticker"])
    return pd.DataFrame(rows).drop_duplicates(["issuer_cik", "filing_date"], keep="last")


def _symbol_dir(symbol: str) -> Path:
    root = SPY_PRICE_ROOT if symbol == SPY else EQUITY_PRICE_ROOT
    return root / f"instrument_id=XUSE:CASH:{symbol}USD"


def load_symbol(symbol: str) -> pd.DataFrame | None:
    paths = sorted(glob.glob(glob.escape(str(_symbol_dir(symbol))) + "/*/*.parquet"))
    if not paths:
        return None
    pieces: list[pd.DataFrame] = []
    for path in paths:
        try:
            pieces.append(pd.read_parquet(path, columns=["ts_open", "open", "close", "volume"]))
        except Exception as error:
            raise RuntimeError(f"unreadable price partition for {symbol}: {path}") from error
    if not pieces:
        return None
    frame = pd.concat(pieces, ignore_index=True).drop_duplicates("ts_open", keep="last")
    # The lake can contain either integer epochs or timezone-aware timestamp scalars. Normalize
    # both to tz-naive UTC session dates so official SEC filing dates compare deterministically.
    frame.index = pd.to_datetime(frame.pop("ts_open"), unit="ms", utc=True).dt.tz_localize(None)
    frame.index = frame.index.normalize()
    return frame.sort_index()[~frame.sort_index().index.duplicated(keep="last")]


def load_panels(
    symbols: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    opens: dict[str, pd.Series] = {}
    closes: dict[str, pd.Series] = {}
    dollar_volume: dict[str, pd.Series] = {}
    source_symbols: dict[str, dict[str, object]] = {}
    for number, symbol in enumerate(sorted(symbols | {SPY}), start=1):
        frame = load_symbol(symbol)
        if frame is None:
            continue
        opens[symbol] = frame["open"].astype(float)
        closes[symbol] = frame["close"].astype(float)
        dollar_volume[symbol] = (frame["close"] * frame["volume"]).astype(float)
        source_symbols[symbol] = {
            "sha256": market_frame_sha256(frame),
            "rows": len(frame),
            "start": str(frame.index.min().date()),
            "end": str(frame.index.max().date()),
        }
        if number % 500 == 0:
            print(f"loaded {number:,}/{len(symbols) + 1:,} symbol paths", flush=True)
    return (
        pd.DataFrame(opens).sort_index(),
        pd.DataFrame(closes).sort_index(),
        pd.DataFrame(dollar_volume).sort_index(),
        {
            "requested_symbols": len(symbols | {SPY}),
            "loaded_symbols": len(source_symbols),
            "missing_symbols": sorted((symbols | {SPY}) - set(source_symbols)),
            "symbols": source_symbols,
        },
    )


def _entry_index(calendar: pd.DatetimeIndex, filing_date: pd.Timestamp) -> int | None:
    first_after = int(calendar.searchsorted(filing_date, side="right"))
    entry = first_after + FILING_DELAY_SESSIONS
    return entry if entry < len(calendar) else None


def schedule_events(
    clusters: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    closes: pd.DataFrame,
    adv: pd.DataFrame,
    close_returns: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    accepted: list[dict[str, object]] = []
    next_free_by_issuer: dict[str, int] = {}
    rejection = {
        "unmapped": 0,
        "cooldown": 0,
        "liquidity": 0,
        "beta_history": 0,
        "incomplete_hold": 0,
    }
    for row in clusters.sort_values(["filing_date", "issuer_cik"]).itertuples(index=False):
        symbol = row.ticker
        if symbol not in closes.columns:
            rejection["unmapped"] += 1
            continue
        entry_idx = _entry_index(calendar, row.filing_date)
        if entry_idx is None or entry_idx >= len(calendar) - 1:
            continue
        if entry_idx < next_free_by_issuer.get(row.issuer_cik, -1):
            rejection["cooldown"] += 1
            continue
        entry_date = calendar[entry_idx]
        prior_idx = entry_idx - 1
        prior_date = calendar[prior_idx]
        price = closes.at[prior_date, symbol] if prior_date in closes.index else np.nan
        liquidity = adv.at[prior_date, symbol] if prior_date in adv.index else np.nan
        if (
            not np.isfinite(price)
            or not np.isfinite(liquidity)
            or price < PRICE_FLOOR
            or liquidity < ADV_FLOOR
        ):
            rejection["liquidity"] += 1
            continue

        history = close_returns[[symbol, SPY]].loc[:prior_date].dropna().tail(252)
        if len(history) < 252 or float(history[SPY].var(ddof=0)) <= 0:
            rejection["beta_history"] += 1
            continue
        beta = float(history[symbol].cov(history[SPY]) / history[SPY].var())
        beta = float(np.clip(beta, 0.0, 3.0))
        exit_idx = entry_idx + HOLD_SESSIONS
        if exit_idx >= len(calendar):
            rejection["incomplete_hold"] += 1
            continue
        next_free_by_issuer[row.issuer_cik] = exit_idx
        accepted.append(
            {
                "issuer_cik": row.issuer_cik,
                "ticker": symbol,
                "filing_date": row.filing_date,
                "entry_date": entry_date,
                "exit_date": calendar[exit_idx],
                "entry_idx": entry_idx,
                "exit_idx": exit_idx,
                "beta": beta,
                "entry_adv": float(liquidity),
                "distinct_insiders": int(row.distinct_insiders),
                "purchase_value_usd": float(row.purchase_value_usd),
            }
        )
    return pd.DataFrame(accepted), rejection


def target_weights(
    scheduled: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    symbols: list[str],
) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=calendar, columns=symbols)
    if scheduled.empty:
        return weights
    for day_idx in range(len(calendar)):
        active = scheduled[(scheduled["entry_idx"] <= day_idx) & (scheduled["exit_idx"] > day_idx)]
        if active.empty:
            continue
        # One issuer can only have one active event by construction. Equal notional before hedge.
        long_weight = 1.0 / len(active)
        beta = 0.0
        for event in active.itertuples(index=False):
            weights.iat[day_idx, weights.columns.get_loc(event.ticker)] += long_weight
            beta += long_weight * event.beta
        weights.iat[day_idx, weights.columns.get_loc(SPY)] = -beta
        gross = float(weights.iloc[day_idx].abs().sum())
        if gross > 0:
            weights.iloc[day_idx] /= gross
    return weights


def nw_t(returns: pd.Series, lags: int = 10) -> float:
    values = returns.dropna().to_numpy(dtype=float)
    if len(values) < 30:
        return 0.0
    residual = values - values.mean()
    variance = float(residual @ residual) / len(values)
    for lag in range(1, lags + 1):
        covariance = float(residual[lag:] @ residual[:-lag]) / len(values)
        variance += 2 * (1 - lag / (lags + 1)) * covariance
    return float(values.mean() / math.sqrt(max(variance, 1e-18) / len(values)))


def sharpe(returns: pd.Series) -> float:
    values = returns.dropna()
    std = float(values.std(ddof=1))
    return float(values.mean() / std * math.sqrt(ANN)) if std > 0 else 0.0


def max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def capacity_report(scheduled: pd.DataFrame, weights: pd.DataFrame) -> dict[str, float]:
    """Portfolio AUM capacity from actual issuer weights and entry-time trailing ADV.

    Each day's capacity is the most restrictive active issuer's allowed dollars divided by its
    portfolio weight. Reporting the fifth percentile prevents one unusually liquid event from
    making the sleeve look scalable. ADV is frozen at entry so no future liquidity is used.
    """
    levels = {"1bp": 0.0001, "5bp": 0.0005, "10bp": 0.001, "1pct": 0.01}
    daily: dict[str, list[float]] = {name: [] for name in levels}
    if scheduled.empty:
        return {f"p05_usd_at_{name}_adv": 0.0 for name in levels}

    for day_idx in range(len(weights)):
        active = scheduled[
            (scheduled["entry_idx"] <= day_idx) & (scheduled["exit_idx"] > day_idx)
        ]
        if active.empty:
            continue
        limits: dict[str, list[float]] = {name: [] for name in levels}
        for event in active.itertuples(index=False):
            issuer_weight = float(weights.iloc[day_idx].get(event.ticker, 0.0))
            if issuer_weight <= 0:
                continue
            for name, participation in levels.items():
                limits[name].append(participation * float(event.entry_adv) / issuer_weight)
        for name in levels:
            if limits[name]:
                daily[name].append(min(limits[name]))

    report: dict[str, float] = {}
    for name, observations in daily.items():
        report[f"p05_usd_at_{name}_adv"] = (
            float(pd.Series(observations).quantile(0.05)) if observations else 0.0
        )
        report[f"median_usd_at_{name}_adv"] = (
            float(pd.Series(observations).median()) if observations else 0.0
        )
    return report


def correlation_report(
    candidate: pd.Series,
) -> tuple[dict[str, float], float, float, dict[str, float]]:
    sleeves = {name: read_curve(path) for name, path in SLEEVE_CURVES.items()}
    joined = pd.concat({"candidate": np.log1p(candidate), **sleeves}, axis=1, sort=True).dropna()
    ordinary = {name: float(joined["candidate"].corr(joined[name])) for name in sleeves}
    base = joined[list(sleeves)].mean(axis=1)
    stress = joined[base <= base.quantile(0.10)]
    stressed = {name: float(stress["candidate"].corr(stress[name])) for name in sleeves}
    average = float(np.mean(list(ordinary.values())))
    max_pair = float(max(ordinary.values()))
    return ordinary, average, max_pair, stressed


def marginal_book_report(candidate: pd.Series) -> dict[str, object]:
    sleeves = {name: read_curve(path) for name, path in SLEEVE_CURVES.items()}
    joined = pd.concat({"candidate": np.log1p(candidate), **sleeves}, axis=1, sort=True).dropna()
    simple = np.expm1(joined)
    base = simple[list(sleeves)].mean(axis=1)
    with_candidate = simple[list(sleeves)].sum(axis=1) * 0.225 + simple["candidate"] * 0.10
    demeaned = simple["candidate"] - simple["candidate"].mean()
    mean_zero = simple[list(sleeves)].sum(axis=1) * 0.225 + demeaned * 0.10
    loo: dict[str, float] = {}
    for year in sorted(simple.index.year.unique()):
        keep = simple.index.year != year
        loo[str(year)] = sharpe(with_candidate[keep]) - sharpe(base[keep])
    return {
        "common_start": str(simple.index.min().date()),
        "common_end": str(simple.index.max().date()),
        "common_days": len(simple),
        "base_sharpe": sharpe(base),
        "candidate_10pct_sharpe": sharpe(with_candidate),
        "delta_sharpe": sharpe(with_candidate) - sharpe(base),
        "mean_zero_delta_sharpe": sharpe(mean_zero) - sharpe(base),
        "leave_one_year_out_delta": loo,
        "all_leave_one_year_out_positive": all(value > 0 for value in loo.values()),
    }


def main() -> None:
    assert_matches(
        PREREG,
        profile="insider_clusters",
        lake_dir="data/lake_sharadar",
        alpha_names=["insider_purchase_cluster_30d"],
        allocator="event_beta_hedged",
        extra={
            "cluster_days": CLUSTER_DAYS,
            "min_distinct_insiders": MIN_INSIDERS,
            "min_purchase_value_usd": int(MIN_VALUE),
            "hold_sessions": HOLD_SESSIONS,
            "filing_delay_sessions": FILING_DELAY_SESSIONS,
            "oos_start": str(OOS_START.date()),
        },
    )
    events = load_events()
    clusters = build_cluster_dates(events)
    symbols = set(clusters["ticker"].dropna().astype(str))
    print(f"events {len(events):,}; raw cluster dates {len(clusters):,}; tickers {len(symbols):,}")
    opens, closes, dollar_volume, market_sources = load_panels(symbols)
    if SPY not in opens:
        raise SystemExit("SPY price series is required for the pre-registered hedge")
    calendar = opens[SPY].dropna().index
    opens = opens.reindex(calendar)
    closes = closes.reindex(calendar)
    dollar_volume = dollar_volume.reindex(calendar)
    open_returns = np.expm1(adjusted_log_returns(opens, ca_dir=CORPORATE_ACTION_ROOT))
    close_returns = adjusted_log_returns(closes, ca_dir=CORPORATE_ACTION_ROOT)
    adv = dollar_volume.rolling(21, min_periods=21).mean()
    scheduled, rejection = schedule_events(clusters, calendar, closes, adv, close_returns)
    print(f"scheduled {len(scheduled):,}; rejection {rejection}")
    used_symbols = sorted(set(scheduled["ticker"]) | {SPY})
    weights = target_weights(scheduled, calendar, used_symbols)
    returns = open_returns.reindex(columns=used_symbols)
    gross = (weights.shift(1).fillna(0.0) * returns).sum(axis=1)
    changes = weights.diff().fillna(weights)
    costs = changes.drop(columns=[SPY]).abs().sum(axis=1) * ISSUER_COST
    costs += changes[SPY].abs() * SPY_COST
    net = (gross - costs).fillna(0.0).loc[OOS_START:]

    OUT.mkdir(parents=True, exist_ok=True)
    event_paths = sorted(Path(path) for path in glob.glob(EVENT_GLOB))
    action_sources = action_data_manifest(set(closes) - {SPY})
    input_manifest = build_input_manifest(event_paths, market_sources, action_sources)
    INPUT_MANIFEST.write_text(json.dumps(input_manifest, indent=2) + "\n")
    write_curve(net, OUT)
    scheduled.to_parquet(OUT / "events.parquet", index=False)
    weights.loc[:, (weights != 0).any()].to_parquet(OUT / "weights.parquet")

    trial_config = trial_configuration()
    ledger_record = record_probe_trial(
        "insider_purchase_clusters",
        trial_config,
        net,
        now_ms=int(pd.Timestamp.now(tz="UTC").timestamp() * 1000),
        periods_per_year=ANN,
        prereg=str(PREREG),
    )
    n_trials, variance = selection_context(root=_ROOT)
    dsr = dsr_from_returns(
        net,
        n_trials=n_trials,
        sr_trials_variance=variance,
        periods_per_year=ANN,
    )
    ordinary, average_corr, max_corr, stressed = correlation_report(net)
    book = marginal_book_report(net)
    beta_frame = pd.concat(
        {"candidate": net, "spy": open_returns[SPY].reindex(net.index)}, axis=1
    ).dropna()
    realized_beta = float(beta_frame["candidate"].cov(beta_frame["spy"]) / beta_frame["spy"].var())
    turnover = float(weights.diff().abs().sum(axis=1).mean() * ANN)
    capacity = capacity_report(scheduled, weights)
    net_2x_costs = (gross - 2.0 * costs).fillna(0.0).loc[OOS_START:]
    result = {
        "schema": "canli.insider-cluster-probe.v3",
        "preregistration": str(PREREG),
        "hypotheses_spent": 1,
        "configuration": trial_config,
        "pbo": "not defined for a one-configuration probe; no selection surface exists",
        "implementation_correction": {
            "status": "corrected_before_publication",
            "issue": (
                "The preliminary pass linearly combined adjusted log returns while the canonical "
                "curve and cost contracts require simple returns."
            ),
            "research_parameters_changed": False,
            "preliminary_verdict": "KILL",
            "preliminary_net_sharpe": -0.9929526796481759,
            "preliminary_newey_west_t": -3.0486717545950497,
            "ledger_policy": (
                "The corrected implementation has a distinct auditable config field and therefore "
                "raises, rather than lowers, the union trial count."
            ),
        },
        "data": {
            "source": "SEC DERA Insider Transactions Data Sets",
            "qualifying_purchase_rows": len(events),
            "raw_cluster_dates": len(clusters),
            "scheduled_nonoverlapping_events": len(scheduled),
            "rejections": rejection,
        },
        "metrics": {
            "observations": int(net.notna().sum()),
            "net_sharpe": sharpe(net),
            "newey_west_t": nw_t(net),
            "dsr": dsr.dsr,
            "psr": dsr.psr,
            "n_trials_union_including_candidate": n_trials,
            "sr_trial_variance": variance,
            "max_drawdown": max_drawdown(net),
            "skew": float(net.skew()),
            "realized_spy_beta": realized_beta,
            "turnover_ann": turnover,
            "net_sharpe_at_2x_costs": sharpe(net_2x_costs),
            "capacity": capacity,
        },
        "correlation": {
            "ordinary_by_sleeve": ordinary,
            "average": average_corr,
            "max_pair": max_corr,
            "stressed_by_sleeve": stressed,
            "max_stressed": max(stressed.values()),
        },
        "book": book,
    }
    gates = {
        "net_sharpe_at_least_0_40": result["metrics"]["net_sharpe"] >= 0.40,
        "dsr_at_least_0_95": result["metrics"]["dsr"] >= 0.95,
        "newey_west_t_at_least_2": result["metrics"]["newey_west_t"] >= 2.0,
        "net_sharpe_at_2x_costs_at_least_0_40": (
            result["metrics"]["net_sharpe_at_2x_costs"] >= 0.40
        ),
        "absolute_beta_at_most_0_10": abs(realized_beta) <= 0.10,
        "average_correlation_at_most_0_15": average_corr <= 0.15,
        "max_pair_correlation_at_most_0_35": max_corr <= 0.35,
        "max_stressed_correlation_at_most_0_50": max(stressed.values()) <= 0.50,
        "book_delta_positive": book["delta_sharpe"] > 0,
        "mean_zero_book_delta_positive": book["mean_zero_delta_sharpe"] > 0,
        "all_leave_one_year_out_positive": book["all_leave_one_year_out_positive"],
        "capacity_p05_at_least_5m": (
            result["metrics"]["capacity"]["p05_usd_at_1pct_adv"] >= 5_000_000
        ),
    }
    result["gates"] = gates
    result["verdict"] = "ADD_TO_SHADOW" if all(gates.values()) else "KILL"
    result["admission_review"] = admission_review(gates)
    result["lineage"] = {
        "preregistration_sha256": file_sha256(PREREG),
        "input_data_manifest_sha256": file_sha256(INPUT_MANIFEST),
        "runner_sha256": file_sha256(RUNNER),
        "admission_contract_sha256": file_sha256(ADMISSION_CONTRACT),
    }
    result["ledger_reconciliation"] = reconcile_ledger_measurement(ledger_record, net)
    result["reproduction"] = reproduction_environment() | {
        "scope": "current_input_snapshot_replay",
        "exact_first_measurement_reproduced": result["ledger_reconciliation"][
            "exact_first_measurement_reproduced"
        ],
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
