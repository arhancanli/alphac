"""Frozen descriptive audit of archived forecasts; never evaluates a new portfolio."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/analysis/alphatrend_cash_retention_20260912"
OUT = ROOT / "artifacts/analysis/alphatrend_forecast_audit_20260912"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def correlation(x, y):
    pair = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(pair) < 5 or pair.x.nunique() < 2 or pair.y.nunique() < 2:
        return np.nan
    return float(pair.x.rank().corr(pair.y.rank()))


def strength_buckets(frame):
    """Equal-date cross-sectional absolute-forecast ranks; ties stay together."""
    rank = frame.groupby("ts_open").mu_ann.transform(lambda s: s.abs().rank(pct=True))
    return np.ceil(rank * 5).clip(1, 5).astype("Int64")


def block_interval(series, seed=20260912):
    """Circular 12-observation blocks of nonoverlapping 21-session date statistics."""
    values = np.asarray(series.dropna(), dtype=float)
    if len(values) < 24:
        return [None, None]
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(values), size=(2000, int(np.ceil(len(values) / 12))))
    indices = ((starts[:, :, None] + np.arange(12)) % len(values)).reshape(2000, -1)
    means = values[indices[:, : len(values)]].mean(axis=1)
    return np.quantile(means, [0.025, 0.975]).tolist()


def summarize(frame):
    signed = np.sign(frame.mu_ann) * frame.forward_log_return
    return {
        "rows": len(frame),
        "dates": int(frame.ts_open.nunique()),
        "mean_abs_prediction_bps": float((frame.mu_ann.abs() * 21 / 252).mean() * 1e4),
        "mean_signed_forward_log_bps": float(signed.mean() * 1e4),
        "direction_hit_rate": float((signed > 0).mean()),
        "time_series_rank_ic": correlation(frame.mu_ann, frame.forward_log_return),
    }


def main():
    import alphaforge.features.library  # noqa: F401
    from alphaforge.config.settings import load_settings
    from alphaforge.config.sleeve import sleeve_for
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.labeling import forward_returns
    from alphaforge.research import zoo
    from alphaforge.signals.service import SignalService
    from alphaforge.validation.input_snapshot import validate_input_snapshot

    OUT.mkdir(parents=True, exist_ok=False)
    snapshot = SOURCE / "baseline/input_snapshot"
    manifest = validate_input_snapshot(snapshot)
    wf = json.loads((SOURCE / "baseline/walkforward.json").read_text())
    declared = json.loads((snapshot / "declared_run.json").read_text())
    config = wf["config"]
    # Fix the audit before calculating any forecast/outcome statistics.
    write(
        OUT / "protocol.json",
        {
            "created_at": datetime.now(UTC).isoformat(),
            "scope": "DESCRIPTIVE_ALREADY_INSPECTED_DATA_NO_NEW_PORTFOLIO_TRIAL",
            "selection_union_hypotheses_unchanged": 231,
            "source_snapshot_content_hash": manifest["content_hash"],
            "source_walkforward_sha256": digest(SOURCE / "baseline/walkforward.json"),
            "script_sha256": digest(Path(__file__)),
            "horizon_sessions": 21,
            "sample": ("Every 21st archived signal session from first baseline test_start; "
                       "no phase search"),
            "label": "log(next-session-plus-21 open / next-session open), exact exchange sessions",
            "label_cutoff": config["end"],
            "diagnostics": [
                "cross-sectional Rank IC for alpha_blend and mu_ann",
                "absolute mu quintiles within each date",
                "all instruments, calendar eras 2006-2012/2013-2019/2020-2026",
                "SPY trailing 252-session direction and 63-session volatility "
                "against expanding prior median",
                "reconstruct original blend and measure sign changes from CS centering",
            ],
            "uncertainty": "2000 circular date block bootstrap draws, block 12, seed 20260912; "
            "descriptive intervals, not multiple-testing-adjusted admission evidence",
            "constraints": "No optimizer, asset removal, candidate portfolio, threshold search, "
            "deployment or new data purchase; no net PnL claim from forecast labels",
        },
    )
    signal = pd.read_parquet(snapshot / "derived_signal_frame.parquet")
    if signal.index.has_duplicates:
        raise ValueError("Duplicate forecast keys")
    bars = pd.concat(
        [
            pd.read_parquet(p)
            for p in sorted((snapshot / "raw_partitions/ohlcv_1d").rglob("*.parquet"))
        ],
        ignore_index=True,
    )
    bars["ts_open"] = bars.ts_open.dt.as_unit("ms").astype("int64")
    bars = bars.loc[bars.ts_open < config["end"]].sort_values(["ts_open", "instrument_id"])
    if bars.duplicated(["ts_open", "instrument_id"]).any():
        raise ValueError("Duplicate price keys")
    settings = load_settings("managed_futures", root=ROOT)
    if settings.signals.model_dump(mode="json") != declared["resolved_settings"]["signals"]:
        raise ValueError("Signal settings drift")
    sleeve = sleeve_for(settings.data.asset_class)
    labels = forward_returns(bars, 21, timeframe=sleeve.anchor_tf, calendar=sleeve.calendar)
    panel = signal.join(labels.rename("forward_log_return")).reset_index()
    first = min(leg["test_start"] for leg in wf["legs"])
    dates = np.sort(signal.index.get_level_values("ts_open").unique())
    dates = dates[dates >= first][::21]
    panel = panel.loc[panel.ts_open.isin(dates)].copy()
    missing = panel[["alpha_blend", "mu_ann", "forward_log_return"]].isna().sum().to_dict()
    panel = panel.dropna(subset=["alpha_blend", "mu_ann", "forward_log_return"])
    panel = panel.loc[panel.mu_ann != 0].copy()
    panel["quintile"] = strength_buckets(panel)
    panel["signed_forward_log_return"] = np.sign(panel.mu_ann) * panel.forward_log_return
    panel["year"] = pd.to_datetime(panel.ts_open, unit="ms", utc=True).dt.year
    panel["era"] = pd.cut(
        panel.year, [2005, 2012, 2019, 2026], labels=["2006-2012", "2013-2019", "2020-2026"]
    )
    spy = bars.loc[bars.instrument_id == "XUSE:CASH:SPYUSD"].set_index("ts_open").close
    # Reindex on the exchange session grid so missing observations cannot shorten lookbacks.
    spy = spy.reindex(np.sort(bars.ts_open.unique()))
    logret = np.log(spy / spy.shift(1))
    vol = logret.rolling(63, min_periods=63).std()
    median = vol.expanding(min_periods=252).median().shift(1)
    trend = np.log(spy / spy.shift(252))
    conditions = pd.DataFrame(
        {
            "market_direction": np.where(trend >= 0, "up", "down"),
            "market_volatility": np.where(vol > median, "high", "low"),
        },
        index=spy.index,
    )
    conditions.loc[trend.isna(), "market_direction"] = "unavailable"
    conditions.loc[vol.isna() | median.isna(), "market_volatility"] = "unavailable"
    panel = panel.join(conditions, on="ts_open")
    date_rows = []
    for ts, group in panel.groupby("ts_open"):
        date_rows.append(
            {
                "ts_open": int(ts),
                "members": len(group),
                "alpha_rank_ic": correlation(group.alpha_blend, group.forward_log_return),
                "mu_rank_ic": correlation(group.mu_ann, group.forward_log_return),
            }
        )
    date_stats = pd.DataFrame(date_rows)
    date_stats.to_parquet(OUT / "date_statistics.parquet", index=False)
    tables = {}
    for key in ["instrument_id", "quintile", "era", "market_direction", "market_volatility"]:
        rows = []
        for name, group in panel.groupby(key, observed=True):
            rows.append({key: str(name), **summarize(group)})
        tables[key] = rows
    # Rebuild only the existing signal, then require exact archived parity.
    zoo.register_all()
    shutil.copy2(SOURCE / "state/ops.sqlite", OUT / "reconstruction.sqlite")
    paths = LakePaths(SOURCE / "lake_mf")
    with InstrumentStore(OUT / "reconstruction.sqlite") as store:
        universe = UniverseStore(paths)
        service = SignalService(
            FeatureEngine(
                PITDataReader(paths), store, universe, asset_class=settings.data.asset_class
            ),
            universe,
            default_registry(),
            settings.signals,
            alpha_names=config["alpha_names"],
            sleeve=sleeve,
        )
        frame, mask, zs = service._panel(config["start"], config["end"])
        weights = service._weights_from_panel(frame, mask, zs)
        reconstructed = service._emit(frame, mask, zs, weights)
        pd.testing.assert_frame_equal(reconstructed, signal, check_exact=True)
        factors = pd.DataFrame(zs)
        timestamps = factors.index.get_level_values("ts_open")
        w = pd.DataFrame(
            [weights.asof(int(t)).to_numpy() for t in timestamps.unique()],
            index=timestamps.unique(),
            columns=weights.alpha_names,
        )
        wrows = w.reindex(timestamps).to_numpy()
        raw = pd.Series((factors.to_numpy() * wrows).sum(axis=1), index=factors.index)
        panel = panel.join(raw.rename("pre_centering_blend"), on=["ts_open", "instrument_id"])
        weights.weights.to_parquet(OUT / "existing_blend_weights.parquet")
    panel["sign_changed_by_centering"] = np.sign(panel.pre_centering_blend) != np.sign(
        panel.alpha_blend
    )
    panel.to_parquet(OUT / "forecast_observations.parquet", index=False)
    result = {
        "scope": "Development forecast diagnostics; not a new strategy backtest",
        "snapshot_verified_files": manifest["file_count"],
        "archived_forecast_reconstruction": "EXACT_PARITY",
        "horizon_sessions": 21,
        "summary": summarize(panel),
        "missing_before_complete_case_filter": {k: int(v) for k, v in missing.items()},
        "first_date": str(pd.to_datetime(panel.ts_open.min(), unit="ms").date()),
        "last_date": str(pd.to_datetime(panel.ts_open.max(), unit="ms").date()),
        "mean_alpha_rank_ic": float(date_stats.alpha_rank_ic.mean()),
        "alpha_rank_ic_block_95_interval": block_interval(date_stats.alpha_rank_ic),
        "mean_mu_rank_ic": float(date_stats.mu_rank_ic.mean()),
        "mu_rank_ic_block_95_interval": block_interval(date_stats.mu_rank_ic),
        "sign_changed_by_centering_fraction": float(panel.sign_changed_by_centering.mean()),
        "tables": tables,
        "limitations": [
            "Fixed surviving ETF basket and retrospectively adjusted historical data",
            "Gross log-return targets omit execution costs, financing and borrow",
            "Pooled observations are dependent and asset mix changes over time",
            "Strength bins mix volatility, asset identity and signal strength",
            "Descriptive already-inspected history; no selection or admission claims",
            "Equal-date IC intervals preserve cross-sectional clustering; "
            "not proof of independence or future profitability",
        ],
    }
    # Convert undefined group statistics to JSON null rather than nonstandard NaN.
    result = json.loads(json.dumps(result).replace("NaN", "null"))
    write(OUT / "results.json", result)
    write(
        OUT / "bindings.json",
        {
            "files": [
                {"path": str(p.relative_to(ROOT)), "sha256": digest(p)}
                for p in sorted(OUT.iterdir())
                if p.is_file()
            ]
        },
    )
    print(json.dumps({k: v for k, v in result.items() if k != "tables"}, indent=2))


if __name__ == "__main__":
    main()
