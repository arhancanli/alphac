#!/usr/bin/env python3
"""One-shot OOS probe for pre-registered EIA petroleum inventory scarcity."""

from __future__ import annotations

import glob
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
for _path in (_ROOT / "src", _ROOT / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from alphaforge.analytics.curve_store import read_curve, write_curve  # noqa: E402
from alphaforge.validation.dsr import dsr_from_returns  # noqa: E402
from alphaforge.validation.prereg import assert_matches  # noqa: E402
from alphaforge.validation.probe_ledger import record_probe_trial, selection_context  # noqa: E402

PREREG: Final[Path] = Path("docs/design/PREREG_EIA_PETROLEUM_INVENTORY.md")
EVENTS: Final[Path] = Path("data/lake_inventory_releases/events.parquet")
MANIFEST: Final[Path] = Path("data/lake_inventory_releases/manifest.json")
PRICE_ROOT: Final[Path] = Path("data/lake_inventory/ohlcv_1d")
OUT: Final[Path] = Path("artifacts/probe/eia_petroleum_inventory")
INPUT_MANIFEST: Final[Path] = OUT / "input_data_manifest.json"
RUNNER: Final[Path] = Path(__file__).resolve()
PYPROJECT: Final[Path] = Path("pyproject.toml")
UV_LOCK: Final[Path] = Path("uv.lock")
ADMISSION_CONTRACT: Final[Path] = Path("config/sleeve_admission_contract.json")
PRODUCTS: Final[tuple[str, ...]] = ("USO", "UGA")
HEDGE: Final[str] = "DBC"
SEASONAL_YEARS: Final[int] = 5
SCALE_WEEKS: Final[int] = 52
OOS_START: Final[pd.Timestamp] = pd.Timestamp("2016-01-01")
ANN: Final[int] = 252
COSTS: Final[dict[str, float]] = {"USO": 0.0006, "UGA": 0.0010, "DBC": 0.0003}
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
        "mechanism": "eia_first_release_petroleum_inventory_scarcity",
        "products": list(PRODUCTS),
        "seasonal_years": SEASONAL_YEARS,
        "scale_weeks": SCALE_WEEKS,
        "score_clip": [-3.0, 3.0],
        "entry": "next_session_open_after_release",
        "hedge": "trailing_252_session_dbc_beta_clamped_-3_3",
        "costs": COSTS,
        "oos_start": str(OOS_START.date()),
    }


def validate_archive_manifest(manifest: dict[str, Any]) -> None:
    """Require every dated first-release file to match the persisted source manifest."""
    if manifest.get("schema") != "canli.eia-wpsr-vintage-manifest.v1":
        raise RuntimeError("unexpected EIA first-release manifest schema")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != manifest.get("discovered_releases"):
        raise RuntimeError("EIA first-release manifest inventory is incomplete")
    for item in files:
        path = Path(str(item.get("path", "")))
        expected = item.get("sha256")
        if not path.is_file() or not isinstance(expected, str):
            raise RuntimeError(f"EIA first-release source is missing: {path}")
        observed = file_sha256(path)
        if observed != expected:
            raise RuntimeError(f"EIA first-release source hash mismatch: {path}")


def _partition_inventory(symbol: str) -> list[dict[str, object]]:
    root = PRICE_ROOT / f"instrument_id=XUSE:CASH:{symbol}USD"
    paths = sorted(Path(path) for path in glob.glob(glob.escape(str(root)) + "/*/*.parquet"))
    if not paths:
        raise FileNotFoundError(f"missing price series {symbol}")
    return [
        {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": file_sha256(path),
        }
        for path in paths
    ]


def build_input_manifest(source_manifest: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "canli.eia-petroleum-inventory-input-manifest.v1",
        "preregistration_path": str(PREREG),
        "preregistration_sha256": file_sha256(PREREG),
        "events_path": str(EVENTS),
        "events_sha256": file_sha256(EVENTS),
        "first_release_manifest_path": str(MANIFEST),
        "first_release_manifest_sha256": file_sha256(MANIFEST),
        "first_release_files_validated": len(source_manifest["files"]),
        "market_data_partitions": {
            symbol: _partition_inventory(symbol) for symbol in (*PRODUCTS, HEDGE)
        },
        "diversification_curves": {
            name: {"path": path, "sha256": file_sha256(Path(path))}
            for name, path in SLEEVE_CURVES.items()
        },
    }
    payload["content_hash"] = content_hash(payload)
    return payload


def reproduction_environment() -> dict[str, object]:
    return {
        "command": "uv run python scripts/probe_eia_petroleum_inventory.py",
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
    """Bind the historical kill to the current contract without claiming eligibility."""
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
            "This historical ETF feasibility probe failed its preregistered research gates. "
            "Binding it to the current v6 contract does not retroactively change those gates or "
            "make it technically eligible."
        ),
    }


def load_symbol(symbol: str) -> pd.DataFrame:
    root = PRICE_ROOT / f"instrument_id=XUSE:CASH:{symbol}USD"
    paths = sorted(glob.glob(glob.escape(str(root)) + "/*/*.parquet"))
    if not paths:
        raise FileNotFoundError(f"missing price series {symbol}")
    frame = pd.concat(
        [pd.read_parquet(path, columns=["ts_open", "open", "close", "volume"]) for path in paths],
        ignore_index=True,
    ).drop_duplicates("ts_open", keep="last")
    frame.index = pd.to_datetime(frame.pop("ts_open"), utc=True).dt.tz_localize(None).dt.normalize()
    return frame.sort_index()


def build_scores(events: pd.DataFrame) -> pd.DataFrame:
    """Compute the locked seasonal surprise score with no use of future releases."""
    output: list[dict[str, object]] = []
    for proxy, group in events.groupby("proxy", sort=False):
        group = group.sort_values("release_date").copy()
        group["report_year"] = group["period_end"].dt.isocalendar().year.astype(int)
        group["report_week"] = group["period_end"].dt.isocalendar().week.astype(int)
        valid_surprises: list[float] = []
        for row in group.itertuples(index=False):
            history = group[
                (group["report_week"] == row.report_week)
                & (group["report_year"] >= row.report_year - SEASONAL_YEARS)
                & (group["report_year"] < row.report_year)
            ]
            years = set(history["report_year"].astype(int))
            required_years = set(range(row.report_year - SEASONAL_YEARS, row.report_year))
            score = np.nan
            surprise = np.nan
            expected = np.nan
            scale = np.nan
            if years == required_years and len(history) == SEASONAL_YEARS:
                expected = float(history["change_million_barrels"].mean())
                surprise = float(row.change_million_barrels - expected)
                if len(valid_surprises) >= SCALE_WEEKS:
                    scale = float(np.std(valid_surprises[-SCALE_WEEKS:], ddof=1))
                    if np.isfinite(scale) and scale > 0:
                        score = float(np.clip(-surprise / scale, -3.0, 3.0))
                valid_surprises.append(surprise)
            output.append(
                {
                    "release_date": row.release_date,
                    "period_end": row.period_end,
                    "proxy": proxy,
                    "expected_change": expected,
                    "surprise": surprise,
                    "scale": scale,
                    "score": score,
                }
            )
    return pd.DataFrame(output).sort_values(["release_date", "proxy"])


def next_session(calendar: pd.DatetimeIndex, release_date: pd.Timestamp) -> int | None:
    index = int(calendar.searchsorted(release_date, side="right"))
    return index if index < len(calendar) else None


def target_weights(
    scores: pd.DataFrame,
    all_releases: list[pd.Timestamp],
    calendar: pd.DatetimeIndex,
    close_returns: pd.DataFrame,
    *,
    products: tuple[str, ...] = PRODUCTS,
) -> tuple[pd.DataFrame, dict[str, int]]:
    weights = pd.DataFrame(0.0, index=calendar, columns=[*products, HEDGE])
    changes: list[tuple[int, pd.Series]] = []
    rejected = {"not_both_products": 0, "beta_history": 0, "past_calendar": 0}
    pivot = scores.pivot(index="release_date", columns="proxy", values="score")

    for released in sorted(all_releases):
        entry_idx = next_session(calendar, released)
        if entry_idx is None:
            rejected["past_calendar"] += 1
            continue
        target = pd.Series(0.0, index=weights.columns)
        if released not in pivot.index or any(
            symbol not in pivot.columns or not np.isfinite(pivot.at[released, symbol])
            for symbol in products
        ):
            rejected["not_both_products"] += 1
            changes.append((entry_idx, target))
            continue
        raw = pivot.loc[released, list(products)].astype(float)
        denominator = float(raw.abs().sum())
        if denominator <= 0:
            rejected["not_both_products"] += 1
            changes.append((entry_idx, target))
            continue
        raw /= denominator
        prior_date = calendar[entry_idx - 1]
        history = close_returns.loc[:prior_date, [*products, HEDGE]].dropna().tail(252)
        if len(history) < 252 or float(history[HEDGE].var()) <= 0:
            rejected["beta_history"] += 1
            changes.append((entry_idx, target))
            continue
        aggregate_beta = 0.0
        for symbol in products:
            beta = float(history[symbol].cov(history[HEDGE]) / history[HEDGE].var())
            aggregate_beta += float(raw[symbol]) * float(np.clip(beta, -3.0, 3.0))
            target[symbol] = float(raw[symbol])
        target[HEDGE] = -aggregate_beta
        gross = float(target.abs().sum())
        if gross > 0:
            target /= gross
        changes.append((entry_idx, target))

    # Only closed release-to-release intervals enter OOS. The latest report has no observed next
    # rebalance yet, so using its partial holding period would be right-censored outcome selection.
    for number, (start, target) in enumerate(changes[:-1]):
        end = changes[number + 1][0]
        weights.iloc[start:end] = target.to_numpy()
    return weights, rejected


def sharpe(returns: pd.Series) -> float:
    values = returns.dropna()
    standard_deviation = float(values.std(ddof=1))
    return (
        float(values.mean() / standard_deviation * math.sqrt(ANN))
        if standard_deviation > 0
        else 0.0
    )


def nw_t(returns: pd.Series, lags: int = 10) -> float:
    values = returns.dropna().to_numpy(dtype=float)
    if len(values) < 30:
        return 0.0
    residual = values - values.mean()
    variance = float(residual @ residual) / len(values)
    for lag in range(1, lags + 1):
        covariance = float(residual[lag:] @ residual[:-lag]) / len(values)
        variance += 2.0 * (1.0 - lag / (lags + 1)) * covariance
    return float(values.mean() / math.sqrt(max(variance, 1e-18) / len(values)))


def max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def simulate(
    weights: pd.DataFrame,
    returns: pd.DataFrame,
    cost_multiplier: float = 1.0,
) -> pd.Series:
    gross = (weights.shift(1).fillna(0.0) * returns).sum(axis=1)
    changes = weights.diff().fillna(weights).abs()
    costs = sum(changes[symbol] * COSTS[symbol] for symbol in weights.columns)
    return (gross - cost_multiplier * costs).fillna(0.0)


def correlation_report(candidate: pd.Series) -> dict[str, object]:
    sleeves = {name: read_curve(path) for name, path in SLEEVE_CURVES.items()}
    joined = pd.concat({"candidate": np.log1p(candidate), **sleeves}, axis=1, sort=True).dropna()
    ordinary = {name: float(joined["candidate"].corr(joined[name])) for name in sleeves}
    base = joined[list(sleeves)].mean(axis=1)
    stress = joined[base <= base.quantile(0.10)]
    stressed = {name: float(stress["candidate"].corr(stress[name])) for name in sleeves}
    return {
        "common_start": str(joined.index.min().date()),
        "common_end": str(joined.index.max().date()),
        "ordinary_by_sleeve": ordinary,
        "average": float(np.mean(list(ordinary.values()))),
        "max_pair": float(max(ordinary.values())),
        "stressed_by_sleeve": stressed,
        "max_stressed": float(max(stressed.values())),
    }


def marginal_book_report(candidate: pd.Series) -> dict[str, object]:
    sleeves = {name: read_curve(path) for name, path in SLEEVE_CURVES.items()}
    joined = pd.concat({"candidate": np.log1p(candidate), **sleeves}, axis=1, sort=True).dropna()
    simple = np.expm1(joined)
    base = simple[list(sleeves)].mean(axis=1)
    combined = simple[list(sleeves)].sum(axis=1) * 0.225 + simple["candidate"] * 0.10
    demeaned = simple["candidate"] - simple["candidate"].mean()
    mean_zero = simple[list(sleeves)].sum(axis=1) * 0.225 + demeaned * 0.10
    leave_one_out = {
        str(year): sharpe(combined[simple.index.year != year])
        - sharpe(base[simple.index.year != year])
        for year in sorted(simple.index.year.unique())
    }
    return {
        "common_days": len(simple),
        "base_sharpe": sharpe(base),
        "candidate_10pct_sharpe": sharpe(combined),
        "delta_sharpe": sharpe(combined) - sharpe(base),
        "mean_zero_delta_sharpe": sharpe(mean_zero) - sharpe(base),
        "leave_one_year_out_delta": leave_one_out,
        "all_leave_one_year_out_positive": all(value > 0 for value in leave_one_out.values()),
    }


def capacity_report(weights: pd.DataFrame, adv: pd.DataFrame) -> dict[str, float]:
    output: dict[str, float] = {}
    for name, participation in {"1bp": 0.0001, "5bp": 0.0005, "10bp": 0.001, "1pct": 0.01}.items():
        daily: list[float] = []
        for day in weights.index:
            limits = [
                participation * float(adv.at[day, symbol]) / abs(float(weights.at[day, symbol]))
                for symbol in PRODUCTS
                if abs(float(weights.at[day, symbol])) > 0
                and np.isfinite(float(adv.at[day, symbol]))
            ]
            if limits:
                daily.append(min(limits))
        output[f"p05_usd_at_{name}_adv"] = (
            float(pd.Series(daily).quantile(0.05)) if daily else 0.0
        )
        output[f"median_usd_at_{name}_adv"] = (
            float(pd.Series(daily).median()) if daily else 0.0
        )
    return output


def main() -> None:
    assert_matches(
        PREREG,
        profile="eia_petroleum_inventory",
        lake_dir="data/lake_inventory",
        alpha_names=["eia_petroleum_inventory_scarcity"],
        allocator="score_weighted_dbc_beta_hedged",
        extra={
            "products": list(PRODUCTS),
            "seasonal_years": SEASONAL_YEARS,
            "scale_weeks": SCALE_WEEKS,
            "oos_start": str(OOS_START.date()),
        },
    )
    events = pd.read_parquet(EVENTS)
    events["release_date"] = pd.to_datetime(events["release_date"]).dt.normalize()
    events["period_end"] = pd.to_datetime(events["period_end"]).dt.normalize()
    scores = build_scores(events)
    manifest = json.loads(MANIFEST.read_text())
    validate_archive_manifest(manifest)
    all_releases = [pd.Timestamp(item["release_date"]) for item in manifest["files"]]

    frames = {symbol: load_symbol(symbol) for symbol in (*PRODUCTS, HEDGE)}
    calendar = frames[HEDGE].index
    opens = pd.DataFrame(
        {symbol: frame["open"] for symbol, frame in frames.items()}
    ).reindex(calendar)
    closes = pd.DataFrame(
        {symbol: frame["close"] for symbol, frame in frames.items()}
    ).reindex(calendar)
    dollar_volume = pd.DataFrame(
        {symbol: frame["close"] * frame["volume"] for symbol, frame in frames.items()}
    ).reindex(calendar)
    open_returns = opens.pct_change(fill_method=None)
    close_returns = closes.pct_change(fill_method=None)
    weights, rejections = target_weights(scores, all_releases, calendar, close_returns)
    net = simulate(weights, open_returns).loc[OOS_START:]
    net_2x = simulate(weights, open_returns, cost_multiplier=2.0).loc[OOS_START:]

    OUT.mkdir(parents=True, exist_ok=True)
    input_manifest = build_input_manifest(manifest)
    INPUT_MANIFEST.write_text(json.dumps(input_manifest, indent=2) + "\n")
    write_curve(net, OUT)
    scores.to_parquet(OUT / "scores.parquet", index=False)
    weights.loc[:, (weights != 0).any()].to_parquet(OUT / "weights.parquet")

    trial_config = trial_configuration()
    record_probe_trial(
        "eia_petroleum_inventory",
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

    correlation = correlation_report(net)
    book = marginal_book_report(net)
    aligned_beta = pd.concat(
        {"candidate": net, "dbc": open_returns[HEDGE]}, axis=1, sort=True
    ).dropna()
    realized_beta = float(
        aligned_beta["candidate"].cov(aligned_beta["dbc"]) / aligned_beta["dbc"].var()
    )
    standalone: dict[str, float] = {}
    for symbol in PRODUCTS:
        isolated, _ = target_weights(
            scores[scores["proxy"] == symbol],
            all_releases,
            calendar,
            close_returns,
            products=(symbol,),
        )
        standalone[symbol] = sharpe(simulate(isolated, open_returns).loc[OOS_START:])
    adv = dollar_volume.rolling(21, min_periods=21).mean().shift(1)
    capacity = capacity_report(weights.loc[OOS_START:], adv.loc[OOS_START:])

    result: dict[str, object] = {
        "schema": "canli.eia-petroleum-inventory-probe.v1",
        "preregistration": str(PREREG),
        "hypotheses_spent": 1,
        "configuration": trial_config,
        "pbo": "not defined for a one-configuration probe; no selection surface exists",
        "data": {
            "source": "EIA dated WPSR archive Table 4 first-release CSV files",
            "discovered_releases": manifest["discovered_releases"],
            "accepted_releases": manifest["accepted_releases"],
            "rejected_releases": manifest["rejected_releases"],
            "score_rows": len(scores),
            "tradable_release_rows": int(scores["score"].notna().sum()),
            "schedule_rejections": rejections,
        },
        "metrics": {
            "observations": int(net.notna().sum()),
            "net_sharpe": sharpe(net),
            "newey_west_t": nw_t(net),
            "dsr": dsr.dsr,
            "psr": dsr.psr,
            "n_trials_union_including_candidate": n_trials,
            "sr_trial_variance": variance,
            "net_sharpe_at_2x_costs": sharpe(net_2x),
            "max_drawdown": max_drawdown(net),
            "skew": float(net.skew()),
            "realized_dbc_beta": realized_beta,
            "turnover_ann": float(
                weights.loc[OOS_START:].diff().abs().sum(axis=1).mean() * ANN
            ),
            "standalone_net_sharpe": standalone,
            "capacity": capacity,
        },
        "correlation": correlation,
        "book": book,
    }
    gates = {
        "net_sharpe_at_least_0_40": sharpe(net) >= 0.40,
        "dsr_at_least_0_95": dsr.dsr >= 0.95,
        "newey_west_t_at_least_2": nw_t(net) >= 2.0,
        "net_sharpe_at_2x_costs_at_least_0_40": sharpe(net_2x) >= 0.40,
        "absolute_dbc_beta_at_most_0_10": abs(realized_beta) <= 0.10,
        "average_correlation_at_most_0_15": correlation["average"] <= 0.15,
        "max_pair_correlation_at_most_0_35": correlation["max_pair"] <= 0.35,
        "max_stressed_correlation_at_most_0_50": correlation["max_stressed"] <= 0.50,
        "book_delta_positive": book["delta_sharpe"] > 0,
        "mean_zero_book_delta_positive": book["mean_zero_delta_sharpe"] > 0,
        "all_leave_one_year_out_positive": book["all_leave_one_year_out_positive"],
        "both_products_positive": all(value > 0 for value in standalone.values()),
    }
    capacity_pass = capacity["p05_usd_at_1pct_adv"] >= 5_000_000
    result["gates"] = {**gates, "proxy_capacity_p05_at_least_5m": capacity_pass}
    if all(gates.values()) and capacity_pass:
        verdict = "ADD_TO_SHADOW"
    elif all(gates.values()):
        verdict = "DATA_ESCALATE"
    else:
        verdict = "KILL"
    result["verdict"] = verdict
    result["admission_review"] = admission_review(result["gates"])
    result["lineage"] = {
        "preregistration_sha256": file_sha256(PREREG),
        "events_sha256": file_sha256(EVENTS),
        "first_release_manifest_sha256": file_sha256(MANIFEST),
        "input_data_manifest_sha256": file_sha256(INPUT_MANIFEST),
        "runner_sha256": file_sha256(RUNNER),
        "admission_contract_sha256": file_sha256(ADMISSION_CONTRACT),
    }
    result["reproduction"] = reproduction_environment()
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
