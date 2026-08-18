#!/usr/bin/env python3
"""Locked OOS probe for annual SEC Item 1A narrative stability.

The runner refuses to open prices until the official-source corpus and immediate-predecessor pair
artifacts both declare completion. There is one direction, one lexical score, one horizon and no
parameter grid. The complete OOS curve is persisted and registered even when the verdict is KILL.
"""

from __future__ import annotations

import glob
import hashlib
import json
import math
import sys
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RUNNER: Final = Path(__file__).resolve()
for path in (ROOT / "src", ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from lib.px_adjust import adjusted_log_returns, load_actions  # noqa: E402

from alphaforge.analytics.curve_store import read_curve, write_curve  # noqa: E402
from alphaforge.validation.diversification import (  # noqa: E402
    DiversificationReport,
    diversification_report,
)
from alphaforge.validation.dsr import dsr_from_returns  # noqa: E402
from alphaforge.validation.experiments import config_hash  # noqa: E402
from alphaforge.validation.prereg import assert_matches  # noqa: E402
from alphaforge.validation.probe_ledger import record_probe_trial, selection_context  # noqa: E402

PREREG: Final = Path("docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE.md")
PAIRS: Final = Path("artifacts/ingest/earnings_narrative_change/item1a_pairs.parquet")
PAIRS_RESULT: Final = Path("artifacts/ingest/earnings_narrative_change/pairs_result.json")
CORPUS_RESULT: Final = Path("artifacts/ingest/earnings_narrative_change/corpus_result.json")
MANIFEST: Final = Path("artifacts/ingest/earnings_narrative_change/filings_manifest.parquet")
ADMISSION_CONTRACT: Final = Path("config/sleeve_admission_contract.json")
TICKER_HISTORY: Final = Path(
    "artifacts/ingest/earnings_narrative_change/issuer_ticker_history.parquet"
)
EQUITY_ROOT: Final = Path("data/lake_sharadar/ohlcv_1d")
SPY_ROOT: Final = Path("data/lake_mf/ohlcv_1d")
ACTION_ROOT: Final = Path("data/lake_sharadar/corporate_actions")
OUT: Final = Path("artifacts/probe/earnings_narrative_change")
RESERVATION: Final = OUT / "return_identity_reservation.json"
OOS_START: Final = pd.Timestamp("2016-01-01")
OOS_END: Final = pd.Timestamp("2025-12-31")
HOLD_SESSIONS: Final = 63
PRICE_FLOOR: Final = 5.0
ADV_FLOOR: Final = 5_000_000.0
STOCK_COST: Final = 0.0015
SPY_COST: Final = 0.0001
BORROW_ANNUAL: Final = 0.03
ANN: Final = 252
DIV_BOOTSTRAP_SAMPLES: Final = 2_000
DIV_BOOTSTRAP_BLOCK_SIZE: Final = 21
DIV_BOOTSTRAP_SEED: Final = 20260816
SPY: Final = "SPY"
NY: Final = ZoneInfo("America/New_York")
SLEEVE_CURVES: Final = {
    "AlphaForge": "artifacts/walkforward/crypto_carry_wk/equity.parquet",
    "AlphaMax": "artifacts/walkforward/k30_dn_63/equity.parquet",
    "AlphaTrend": "artifacts/walkforward/managed_futures/equity.parquet",
    "AlphaVintage": "artifacts/probe/cpi_surprise_size/equity.parquet",
}


def hypothesis_hash(config: Mapping[str, object]) -> str:
    """Expose the shared selection identity rule used by the experiment union."""
    from alphaforge.validation.experiments import hypothesis_hash as shared_hypothesis_hash

    return shared_hypothesis_hash(config)


def require_complete(path: Path, expected_stage: str) -> dict:
    if not path.exists():
        raise RuntimeError(f"required pre-return artifact is missing: {path}")
    result = json.loads(path.read_text())
    if result.get("stage") != expected_stage or result.get("complete") is not True:
        raise RuntimeError(f"pre-return artifact is not complete: {path}: {result}")
    if int(result.get("hypothesis_identities_spent", -1)) != 0:
        raise RuntimeError(f"corpus stage unexpectedly spent a return identity: {path}")
    return result


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def admission_review(
    gates: dict[str, bool], diversification_report_sha256: str
) -> dict[str, object]:
    """Describe the research subset without implying full technical eligibility."""
    contract = json.loads(ADMISSION_CONTRACT.read_text())
    if contract.get("schema") != "canli.alphac-sleeve-admission-contract.v4":
        raise RuntimeError("unexpected sleeve admission contract schema")
    required = int(contract.get("evidence_checks_per_candidate", 0))
    if required != 75:
        raise RuntimeError("sleeve admission contract must retain exactly 75 checks")
    passed = sum(bool(value) for value in gates.values())
    research_pass = passed == len(gates)
    return {
        "contract_schema": contract["schema"],
        "contract_path": str(ADMISSION_CONTRACT),
        "contract_sha256": file_sha256(ADMISSION_CONTRACT),
        "checks_required_for_technical_eligibility": required,
        "research_subset_checks": len(gates),
        "research_subset_passed": passed,
        "canonical_diversification_report_sha256": diversification_report_sha256,
        "status": (
            "PENDING_FULL_75_CHECK_REVIEW"
            if research_pass
            else "RESEARCH_SUBSET_FAILED"
        ),
        "technically_eligible": False,
        "unresolved_evidence": [
            "point-in-time historical locate and borrow availability",
            "full execution-dimension scenario bundle and replay hashes",
            "capacity-curve reconciliation across stressed capital levels",
            "complete required lineage and robustness bundle",
        ],
        "claim_boundary": contract["claim_boundary"],
    }


def require_bound_pairs(corpus: dict, pair_result: dict, pairs_path: Path) -> None:
    if pair_result.get("source_corpus_parts_sha256") != corpus.get("parts_sha256"):
        raise RuntimeError("pair artifact is not bound to the completed corpus lineage")
    if int(pair_result.get("source_processed_rows", -1)) != int(corpus.get("processed_rows", -2)):
        raise RuntimeError("pair artifact corpus row count is stale")
    if not pairs_path.exists() or pair_result.get("pair_file_sha256") != file_sha256(pairs_path):
        raise RuntimeError("pair parquet bytes do not match the sealed pair result")
    manifest = pair_result.get("source_manifest")
    if not isinstance(manifest, dict):
        raise RuntimeError("pair artifact has no source-manifest lineage")
    if manifest.get("path") != str(MANIFEST):
        raise RuntimeError("pair artifact references an unexpected filing manifest")
    if not MANIFEST.exists() or manifest.get("sha256") != file_sha256(MANIFEST):
        raise RuntimeError("filing manifest bytes do not match the sealed pair result")
    if pair_result.get("preregistration_sha256") != file_sha256(PREREG):
        raise RuntimeError("pair artifact is not bound to the current preregistration bytes")


def locked_trial_config() -> dict[str, Any]:
    return {
        "mechanism": "sec_10k_item1a_stability_jaccard5",
        "direction": "long_stable_short_changed",
        "controls": "filing_reaction_momentum_sic2",
        "cohort": "acceptance_month_second_next_open",
        "tails": "residual_quintiles",
        "hold_sessions": HOLD_SESSIONS,
        "hedge": "individual_252d_spy_beta_clamped_pm1",
        "costs": {
            "stock_oneway": STOCK_COST,
            "spy_oneway": SPY_COST,
            "borrow_annual": BORROW_ANNUAL,
        },
        "oos_start": str(OOS_START.date()),
        "oos_end": str(OOS_END.date()),
    }


def reserve_return_identity(
    corpus: Mapping[str, Any], pair_result: Mapping[str, Any], trial_config: Mapping[str, Any]
) -> dict[str, Any]:
    """Persist one spent identity before the first market-data read; idempotent on exact inputs."""
    stable = {
        "schema": "canli.alphac-return-identity-reservation.v1",
        "status": "RETURN_IDENTITY_RESERVED",
        "family_trial_account": "earnings_narrative_change",
        "return_identity_id": "earnings_narrative_change_v1",
        "hypotheses_spent": 1,
        "preregistration_sha256": file_sha256(PREREG),
        "corpus_parts_sha256": corpus["parts_sha256"],
        "pair_file_sha256": pair_result["pair_file_sha256"],
        "trial_config": dict(trial_config),
        "trial_config_hash": config_hash(dict(trial_config)),
    }
    if RESERVATION.exists():
        existing = json.loads(RESERVATION.read_text())
        comparable = {key: value for key, value in existing.items() if key != "reserved_at"}
        if comparable != stable:
            raise RuntimeError(
                "return identity was already reserved against different locked inputs; "
                "refusing to open market data"
            )
        return existing
    payload = {**stable, "reserved_at": datetime.now(UTC).isoformat()}
    RESERVATION.parent.mkdir(parents=True, exist_ok=True)
    temporary = RESERVATION.with_suffix(RESERVATION.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(RESERVATION)
    return payload


def _symbol_dir(symbol: str) -> Path:
    root = SPY_ROOT if symbol == SPY else EQUITY_ROOT
    return root / f"instrument_id=XUSE:CASH:{symbol}USD"


def load_symbol(symbol: str) -> pd.DataFrame | None:
    paths = sorted(glob.glob(glob.escape(str(_symbol_dir(symbol))) + "/*/*.parquet"))
    pieces: list[pd.DataFrame] = []
    for path in paths:
        try:
            pieces.append(pd.read_parquet(path, columns=["ts_open", "open", "close", "volume"]))
        except Exception as error:
            raise RuntimeError(f"unreadable price partition for {symbol}: {path}") from error
    if not pieces:
        return None
    frame = pd.concat(pieces, ignore_index=True).drop_duplicates("ts_open", keep="last")
    index = pd.to_datetime(frame.pop("ts_open"), utc=True).dt.tz_localize(None).dt.normalize()
    frame.index = index
    return frame.sort_index()[~frame.sort_index().index.duplicated(keep="last")]


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
    actions = load_actions(symbols, ca_dir=ACTION_ROOT, strict=True)
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


def load_spy_calendar() -> pd.DatetimeIndex:
    spy = load_symbol(SPY)
    if spy is None:
        raise RuntimeError("pinned SPY total-return series is missing")
    return spy["close"].dropna().index.sort_values()


def second_session_after_month_end(
    calendar: pd.DatetimeIndex, timestamp: pd.Timestamp
) -> int | None:
    month_end = timestamp.to_period("M").end_time.normalize()
    first = int(calendar.searchsorted(month_end, side="right"))
    second = first + 1
    return second if second < len(calendar) else None


def reaction_window(calendar: pd.DatetimeIndex, accepted: pd.Timestamp) -> tuple[int, int] | None:
    """Latest close before acceptance, then close of first session opening after acceptance."""
    if accepted.tzinfo is None:
        accepted = accepted.tz_localize("UTC")
    local = accepted.tz_convert(NY)
    day = local.tz_localize(None).normalize()
    same_pos = int(calendar.searchsorted(day, side="left"))
    is_session = same_pos < len(calendar) and calendar[same_pos] == day
    local_clock = local.time()

    if is_session and local_clock >= pd.Timestamp("16:00").time():
        previous_close = same_pos
    else:
        previous_close = same_pos - 1
    if is_session and local_clock < pd.Timestamp("09:30").time():
        complete_close = same_pos
    else:
        complete_close = same_pos + (1 if is_session else 0)
    if previous_close < 0 or complete_close >= len(calendar) or complete_close <= previous_close:
        return None
    return previous_close, complete_close


def prepare_ticker_history(path: Path = TICKER_HISTORY) -> pd.DataFrame:
    history = pd.read_parquet(path)
    history["firstpricedate"] = pd.to_datetime(history["firstpricedate"])
    history["lastpricedate"] = pd.to_datetime(history["lastpricedate"])
    history["ticker"] = history["ticker"].astype(str).str.upper().str.strip()
    return history.sort_values(["cik", "firstpricedate", "ticker"])


def map_ticker(history: pd.DataFrame, cik: int, entry_date: pd.Timestamp) -> tuple[str | None, str]:
    issuer = history[history["cik"].eq(cik)]
    valid = issuer[issuer["firstpricedate"].le(entry_date) & issuer["lastpricedate"].ge(entry_date)]
    if len(valid) != 1:
        return None, "issuer_interval_missing" if valid.empty else "issuer_interval_ambiguous"
    ticker = str(valid.iloc[0]["ticker"])
    collisions = history[
        history["ticker"].eq(ticker)
        & history["firstpricedate"].le(entry_date)
        & history["lastpricedate"].ge(entry_date)
    ]
    if collisions["cik"].nunique() != 1:
        return None, "ticker_reuse_ambiguous"
    return ticker, "mapped"


def map_pairs_to_entries(
    pairs: pd.DataFrame, history: pd.DataFrame, calendar: pd.DatetimeIndex
) -> tuple[pd.DataFrame, dict[str, int]]:
    rows: list[dict] = []
    rejected: defaultdict[str, int] = defaultdict(int)
    for record in pairs.itertuples(index=False):
        accepted = pd.Timestamp(record.current_acceptance)
        entry_idx = second_session_after_month_end(calendar, accepted.tz_localize(None))
        if entry_idx is None:
            rejected["entry_outside_calendar"] += 1
            continue
        exit_idx = entry_idx + HOLD_SESSIONS
        if exit_idx >= len(calendar) or calendar[exit_idx] > OOS_END:
            rejected["incomplete_hold"] += 1
            continue
        entry_date = calendar[entry_idx]
        if entry_date < OOS_START:
            rejected["pre_oos"] += 1
            continue
        ticker, reason = map_ticker(history, int(record.cik), entry_date)
        if ticker is None:
            rejected[reason] += 1
            continue
        window = reaction_window(calendar, accepted)
        if window is None:
            rejected["reaction_window"] += 1
            continue
        rows.append(
            {
                **record._asdict(),
                "accepted": accepted,
                "cohort_month": accepted.tz_localize(None).to_period("M").to_timestamp(),
                "ticker": ticker,
                "entry_idx": entry_idx,
                "entry_date": entry_date,
                "exit_idx": exit_idx,
                "exit_date": calendar[exit_idx],
                "reaction_start_idx": window[0],
                "reaction_end_idx": window[1],
            }
        )
    return pd.DataFrame(rows), dict(rejected)


def load_panels(
    symbols: set[str], calendar: pd.DatetimeIndex
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    opens: dict[str, pd.Series] = {}
    closes: dict[str, pd.Series] = {}
    volumes: dict[str, pd.Series] = {}
    source_symbols: dict[str, dict[str, object]] = {}
    for number, symbol in enumerate(sorted(symbols | {SPY}), 1):
        frame = load_symbol(symbol)
        if frame is not None:
            opens[symbol] = frame["open"].astype(float)
            closes[symbol] = frame["close"].astype(float)
            volumes[symbol] = frame["volume"].astype(float)
            source_symbols[symbol] = {
                "sha256": market_frame_sha256(frame),
                "rows": len(frame),
                "start": str(frame.index.min().date()),
                "end": str(frame.index.max().date()),
            }
        if number % 500 == 0:
            print(f"loaded {number:,}/{len(symbols) + 1:,} price histories", flush=True)
    return (
        pd.DataFrame(opens).reindex(calendar),
        pd.DataFrame(closes).reindex(calendar),
        pd.DataFrame(volumes).reindex(calendar),
        {
            "requested_symbols": len(symbols | {SPY}),
            "loaded_symbols": len(source_symbols),
            "missing_symbols": sorted((symbols | {SPY}) - set(source_symbols)),
            "symbols": source_symbols,
        },
    )


def adjusted_panels(opens: pd.DataFrame, closes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    stock_columns = [column for column in closes if column != SPY]
    # Carry stale marks through stock-specific halts so the eventual reopening move is realized.
    # Terminal histories are force-flattened separately; they are never carried as live positions.
    close_lr = adjusted_log_returns(
        closes[stock_columns],
        ca_dir=ACTION_ROOT,
        strict_actions=True,
        carry_missing=True,
    )
    open_lr = adjusted_log_returns(
        opens[stock_columns],
        ca_dir=ACTION_ROOT,
        strict_actions=True,
        carry_missing=True,
    )
    close_lr[SPY] = np.log(closes[SPY].ffill()).diff()
    open_lr[SPY] = np.log(opens[SPY].ffill()).diff()
    return open_lr.reindex(columns=closes.columns), close_lr.reindex(columns=closes.columns)


def require_complete_spy_execution(opens: pd.DataFrame) -> None:
    window = opens.loc[OOS_START:OOS_END, SPY]
    missing = window[window.isna()]
    if missing.empty:
        return
    sample = ", ".join(str(timestamp.date()) for timestamp in missing.index[:5])
    raise RuntimeError(
        f"SPY has {len(missing)} missing OOS opening prints; hedge execution cannot be "
        f"simulated at stale prices (first dates: {sample})"
    )


def ranked_residuals(frame: pd.DataFrame) -> pd.Series | None:
    ranked = frame[["fivegram_jaccard", "reaction", "momentum"]].rank(method="average", pct=True)
    dummies = pd.get_dummies(frame["sic2"], prefix="sic", drop_first=True, dtype=float)
    design = np.column_stack(
        [np.ones(len(frame)), ranked["reaction"], ranked["momentum"], dummies.to_numpy()]
    )
    rank = int(np.linalg.matrix_rank(design))
    if len(frame) - rank < 10:
        return None
    beta = np.linalg.lstsq(design, ranked["fivegram_jaccard"].to_numpy(), rcond=None)[0]
    residual = ranked["fivegram_jaccard"].to_numpy() - design @ beta
    result = pd.Series(residual, index=frame.index)
    if result[np.isfinite(result)].nunique() < 10:
        return None
    return result


def enrich_and_select(
    mapped: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    closes: pd.DataFrame,
    volume: pd.DataFrame,
    close_lr: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    candidates: list[dict] = []
    rejected: defaultdict[str, int] = defaultdict(int)
    duplicate_issuer_month = mapped.duplicated(["cohort_month", "cik"], keep=False)
    rejected["duplicate_issuer_month"] += int(duplicate_issuer_month.sum())
    mapped = mapped.loc[~duplicate_issuer_month]
    dollar_volume = closes * volume
    adv = dollar_volume.rolling(21, min_periods=21).median()
    for row in mapped.itertuples(index=False):
        symbol = row.ticker
        if symbol not in closes or SPY not in closes:
            rejected["price_unmapped"] += 1
            continue
        prior_idx = row.entry_idx - 1
        month_end_idx = (
            int(calendar.searchsorted(row.cohort_month + pd.offsets.MonthEnd(0), side="right")) - 1
        )
        if month_end_idx < 252 or prior_idx < 20:
            rejected["insufficient_history"] += 1
            continue
        price = closes[symbol].iloc[prior_idx]
        liquidity = adv[symbol].iloc[prior_idx]
        if (
            not np.isfinite(price)
            or not np.isfinite(liquidity)
            or price < PRICE_FLOOR
            or liquidity < ADV_FLOOR
        ):
            rejected["liquidity"] += 1
            continue
        required_close_cells = [
            closes[symbol].iloc[row.reaction_start_idx],
            closes[symbol].iloc[row.reaction_end_idx],
            closes[SPY].iloc[row.reaction_start_idx],
            closes[SPY].iloc[row.reaction_end_idx],
            closes[symbol].iloc[month_end_idx - 252],
            closes[symbol].iloc[month_end_idx - 21],
        ]
        if not all(np.isfinite(value) for value in required_close_cells):
            rejected["control_endpoint_missing"] += 1
            continue
        reaction_slice = close_lr.iloc[row.reaction_start_idx + 1 : row.reaction_end_idx + 1]
        reaction = float(reaction_slice[symbol].sum() - reaction_slice[SPY].sum())
        momentum_window = close_lr[symbol].iloc[month_end_idx - 251 : month_end_idx - 20]
        momentum = float(np.expm1(momentum_window.sum()))
        beta_history = (
            close_lr[[symbol, SPY]].iloc[month_end_idx - 251 : month_end_idx + 1].dropna()
        )
        if len(beta_history) != 252 or float(beta_history[SPY].var(ddof=0)) <= 0:
            rejected["beta_history"] += 1
            continue
        beta = float(beta_history[symbol].cov(beta_history[SPY]) / beta_history[SPY].var())
        if not np.isfinite(reaction) or not np.isfinite(momentum) or not np.isfinite(beta):
            rejected["nonfinite_control"] += 1
            continue
        candidates.append(
            {
                **row._asdict(),
                "reaction": reaction,
                "momentum": momentum,
                "beta": float(np.clip(beta, -1.0, 1.0)),
                "entry_adv": float(liquidity),
                "sic2": str(row.sic).zfill(4)[:2],
            }
        )

    frame = pd.DataFrame(candidates)
    if frame.empty:
        return pd.DataFrame(), dict(rejected)
    selected: list[pd.DataFrame] = []
    for _, cohort in frame.groupby("cohort_month", sort=True):
        if len(cohort) < 20:
            rejected["cohort_below_20"] += len(cohort)
            continue
        residual = ranked_residuals(cohort)
        if residual is None:
            rejected["saturated_cohort"] += len(cohort)
            continue
        cohort = cohort.assign(residual=residual)
        n_tail = math.floor(len(cohort) * 0.20)
        if n_tail < 5:
            rejected["tail_below_5"] += len(cohort)
            continue
        ordered = cohort.sort_values(["residual", "cik"], kind="stable")
        short = ordered.head(n_tail).copy().assign(side=-1, cohort_stock_weight=-0.5 / n_tail)
        long = ordered.tail(n_tail).copy().assign(side=1, cohort_stock_weight=0.5 / n_tail)
        selected.extend([short, long])
    return (pd.concat(selected, ignore_index=True) if selected else pd.DataFrame()), dict(rejected)


def target_weights(
    selected: pd.DataFrame, calendar: pd.DatetimeIndex
) -> tuple[pd.DataFrame, pd.DataFrame]:
    symbols = sorted(set(selected["ticker"]))
    stock = pd.DataFrame(0.0, index=calendar, columns=symbols)
    beta_weight = pd.DataFrame(0.0, index=calendar, columns=symbols)
    active_count = pd.Series(0.0, index=calendar)
    for (_, entry_idx, exit_idx), cohort in selected.groupby(
        ["cohort_month", "entry_idx", "exit_idx"], sort=True
    ):
        active_count.iloc[int(entry_idx) : int(exit_idx)] += 1.0
        for row in cohort.itertuples(index=False):
            active_dates = calendar[int(entry_idx) : int(exit_idx)]
            stock.loc[active_dates, row.ticker] += float(row.cohort_stock_weight)
            beta_weight.loc[active_dates, row.ticker] += float(row.cohort_stock_weight * row.beta)
    divisor = active_count.replace(0.0, np.nan)
    stock = stock.div(divisor, axis=0).fillna(0.0)
    beta_weight = beta_weight.div(divisor, axis=0).fillna(0.0)
    return stock, beta_weight


def normalize_stock_gross(
    stock: pd.DataFrame, beta_weight: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the locked post-netting stock-gross normalization before hedging."""
    gross = stock.abs().sum(axis=1).replace(0.0, np.nan)
    return (
        stock.div(gross, axis=0).fillna(0.0),
        beta_weight.div(gross, axis=0).fillna(0.0),
    )


def force_flat_terminal_histories(
    stock: pd.DataFrame,
    beta_weight: pd.DataFrame,
    opens: pd.DataFrame,
    selected: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    stock = stock.copy()
    beta_weight = beta_weight.copy()
    events: list[dict] = []
    for symbol in stock.columns:
        last_date = opens[symbol].last_valid_index() if symbol in opens else None
        if last_date is None:
            continue
        last_idx = stock.index.get_loc(last_date)
        affected = selected[
            selected["ticker"].eq(symbol)
            & selected["entry_idx"].le(last_idx)
            & selected["exit_idx"].gt(last_idx)
        ]
        if affected.empty:
            continue
        stock.loc[last_date:, symbol] = 0.0
        beta_weight.loc[last_date:, symbol] = 0.0
        events.append(
            {
                "ticker": symbol,
                "last_observed_open": str(last_date.date()),
                "affected_cohorts": int(affected["cohort_month"].nunique()),
            }
        )
    return stock, beta_weight, events


def hedged_targets(
    stock: pd.DataFrame, beta_weight: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return total-gross-normalized desired weights and per-stock beta contributions."""
    weights = stock.copy()
    weights[SPY] = -beta_weight.sum(axis=1)
    gross = weights.abs().sum(axis=1).replace(0.0, np.nan)
    return (
        weights.div(gross, axis=0).fillna(0.0),
        beta_weight.div(gross, axis=0).fillna(0.0),
    )


def hedged_weights(stock: pd.DataFrame, beta_weight: pd.DataFrame) -> pd.DataFrame:
    return hedged_targets(stock, beta_weight)[0]


def executable_weights(
    desired: pd.DataFrame, beta_contribution: pd.DataFrame, opens: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Defer each stock target change until that stock next has a real opening print."""
    executed = desired.copy()
    executed_beta = beta_contribution.copy()
    deferred: dict[str, int] = {}
    for symbol in beta_contribution.columns:
        tradable = opens[symbol].notna() if symbol in opens else pd.Series(False, index=opens.index)
        changed_while_closed = desired[symbol].diff().fillna(desired[symbol]).ne(0.0) & ~tradable
        if changed_while_closed.any():
            deferred[symbol] = int(changed_while_closed.sum())
        executed[symbol] = desired[symbol].where(tradable).ffill().fillna(0.0)
        executed_beta[symbol] = beta_contribution[symbol].where(tradable).ffill().fillna(0.0)
    executed[SPY] = -executed_beta.sum(axis=1)
    return executed, deferred


def sharpe(returns: pd.Series) -> float:
    values = returns.dropna()
    std = float(values.std(ddof=1))
    return float(values.mean() / std * math.sqrt(ANN)) if std > 0 else 0.0


def nw_t(returns: pd.Series, lags: int = 10) -> float:
    values = returns.dropna().to_numpy(float)
    if len(values) < 30:
        return 0.0
    residual = values - values.mean()
    variance = float(residual @ residual) / len(values)
    for lag in range(1, lags + 1):
        covariance = float(residual[lag:] @ residual[:-lag]) / len(values)
        variance += 2 * (1 - lag / (lags + 1)) * covariance
    return float(values.mean() / math.sqrt(max(variance, 1e-18) / len(values)))


def max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def annual_report(returns: pd.Series) -> dict[str, dict[str, float | int]]:
    report: dict[str, dict[str, float | int]] = {}
    for year, values in returns.groupby(returns.index.year):
        report[str(year)] = {
            "observations": len(values),
            "total_return": float((1.0 + values).prod() - 1.0),
            "sharpe": sharpe(values),
        }
    return report


def canonical_diversification_evidence(
    candidate: pd.Series,
) -> tuple[DiversificationReport, dict[str, object], pd.DataFrame]:
    """Build the exact common-window input without silently dropping internal gaps."""
    sleeve_log = {name: read_curve(path) for name, path in SLEEVE_CURVES.items()}
    series = {"candidate": np.log1p(candidate), **sleeve_log}
    starts = {name: value.first_valid_index() for name, value in series.items()}
    ends = {name: value.last_valid_index() for name, value in series.items()}
    empty = [name for name in series if starts[name] is None or ends[name] is None]
    if empty:
        raise RuntimeError(f"canonical diversification series contain no valid data: {empty}")
    common_start = max(pd.Timestamp(value) for value in starts.values())
    common_end = min(pd.Timestamp(value) for value in ends.values())
    if common_start > common_end:
        raise RuntimeError("candidate and current sleeves have no valid common OOS window")
    common_index = candidate.loc[common_start:common_end].index
    joined = pd.DataFrame(
        {name: value.reindex(common_index) for name, value in series.items()},
        index=common_index,
    )
    missing = {name: int(joined[name].isna().sum()) for name in joined if joined[name].isna().any()}
    if missing:
        raise RuntimeError(
            "canonical diversification alignment has internal missing dates; "
            f"no rows may be dropped: {missing}"
        )
    simple = np.expm1(joined)
    base = simple[list(sleeve_log)].mean(axis=1)
    stress_mask = (base <= base.quantile(0.10)).to_numpy(dtype=bool)
    report = diversification_report(
        simple["candidate"].to_numpy(),
        {name: simple[name].to_numpy() for name in sleeve_log},
        base.to_numpy(),
        stress_mask=stress_mask,
        period_labels=[str(year) for year in simple.index.year],
        candidate_weight=0.10,
        bootstrap_samples=DIV_BOOTSTRAP_SAMPLES,
        bootstrap_block_size=DIV_BOOTSTRAP_BLOCK_SIZE,
        bootstrap_seed=DIV_BOOTSTRAP_SEED,
    )
    alignment: dict[str, object] = {
        "common_start": str(common_index.min().date()),
        "common_end": str(common_index.max().date()),
        "common_days": len(common_index),
        "candidate_days_before_common_start": int((candidate.index < common_start).sum()),
        "candidate_days_after_common_end": int((candidate.index > common_end).sum()),
        "internal_missing_by_series": {},
        "stress_rule": "bottom decile of pre-existing equal-weight ALPHAC book returns",
        "stress_threshold": float(base.quantile(0.10)),
    }
    return report, alignment, simple


def marginal_book_report(
    simple: pd.DataFrame, report: DiversificationReport
) -> dict[str, object]:
    sleeves = list(SLEEVE_CURVES)
    base = simple[sleeves].mean(axis=1)
    combined = simple[list(sleeves)].sum(axis=1) * 0.225 + simple["candidate"] * 0.10
    demeaned = simple["candidate"] - simple["candidate"].mean()
    mean_zero = simple[list(sleeves)].sum(axis=1) * 0.225 + demeaned * 0.10
    return {
        "common_start": str(simple.index.min().date()),
        "common_end": str(simple.index.max().date()),
        "common_days": len(simple),
        "base_sharpe": sharpe(base),
        "candidate_10pct_sharpe": sharpe(combined),
        "delta_sharpe": report.book_sharpe_delta,
        "mean_zero_delta_sharpe": sharpe(mean_zero) - sharpe(base),
        "leave_one_year_out_delta": report.leave_one_period_out_book_sharpe_deltas,
        "all_leave_one_year_out_positive": (
            report.minimum_leave_one_period_out_book_sharpe_delta > 0
        ),
        "max_drawdown_delta": report.book_max_drawdown_delta,
        "expected_shortfall_delta": report.book_expected_shortfall_delta,
    }


def capacity_report(selected: pd.DataFrame, weights: pd.DataFrame) -> dict[str, float]:
    levels = {"1bp": 0.0001, "5bp": 0.0005, "10bp": 0.001, "1pct": 0.01}
    observations: dict[str, list[float]] = {name: [] for name in levels}
    ticker_adv = selected.groupby("ticker")["entry_adv"].min().to_dict()
    for day in weights.index:
        for name, participation in levels.items():
            limits = []
            for ticker in weights.columns.drop(SPY):
                weight = abs(float(weights.at[day, ticker]))
                if weight > 0:
                    limits.append(participation * float(ticker_adv[ticker]) / weight)
            if limits:
                observations[name].append(min(limits))
    result: dict[str, float] = {}
    for name, values in observations.items():
        series = pd.Series(values, dtype=float)
        result[f"p05_usd_at_{name}_adv"] = float(series.quantile(0.05)) if len(series) else 0.0
        result[f"median_usd_at_{name}_adv"] = float(series.median()) if len(series) else 0.0
    return result


def main() -> None:
    assert_matches(
        PREREG,
        profile="earnings_narrative_change_v1",
        lake_dir="data/lake_sharadar",
        alpha_names=["sec_10k_item1a_stability_jaccard5"],
        allocator="monthly_residual_quintile_beta_hedged",
        extra={
            "parser_version": "sec-filing-sections-v2",
            "direction": "long_stable_short_changed",
            "hold_sessions": HOLD_SESSIONS,
            "oos_start": str(OOS_START.date()),
            "oos_end": str(OOS_END.date()),
        },
    )
    corpus = require_complete(CORPUS_RESULT, "corpus_ingest_no_prices_no_returns")
    pair_result = require_complete(PAIRS_RESULT, "narrative_pairs_no_prices_no_returns")
    require_bound_pairs(corpus, pair_result, PAIRS)
    pairs = pd.read_parquet(PAIRS)
    trial_config = locked_trial_config()
    reservation = reserve_return_identity(corpus, pair_result, trial_config)
    history = prepare_ticker_history()
    calendar = load_spy_calendar()
    mapped, mapping_rejections = map_pairs_to_entries(pairs, history, calendar)
    symbols = set(mapped["ticker"])
    opens, closes, volume, market_sources = load_panels(symbols, calendar)
    if SPY not in closes or SPY not in opens:
        raise RuntimeError("SPY is required for controls and beta hedge")
    require_complete_spy_execution(opens)
    action_sources = action_data_manifest(set(closes) - {SPY})
    open_lr, close_lr = adjusted_panels(opens, closes)
    selected, selection_rejections = enrich_and_select(mapped, calendar, closes, volume, close_lr)
    if selected.empty:
        raise RuntimeError("locked signal produced no selected cohorts")
    stock_targets, beta_targets = target_weights(selected, calendar)
    stock_targets, beta_targets = normalize_stock_gross(stock_targets, beta_targets)
    stock_targets, beta_targets, force_flats = force_flat_terminal_histories(
        stock_targets, beta_targets, opens, selected
    )
    desired, beta_contribution = hedged_targets(stock_targets, beta_targets)
    weights, deferred_trades = executable_weights(desired, beta_contribution, opens)
    used = list(weights.columns)
    simple_open = np.expm1(open_lr.reindex(columns=used))
    held = weights.shift(1).fillna(0.0)
    gross_by_symbol = held * simple_open
    gross = gross_by_symbol.sum(axis=1)
    changes = weights.diff().fillna(weights)
    stock_changes = changes.drop(columns=[SPY]).abs().sum(axis=1)
    transaction_cost = stock_changes * STOCK_COST + changes[SPY].abs() * SPY_COST
    short_gross = weights.drop(columns=[SPY]).clip(upper=0.0).abs().sum(axis=1)
    borrow = short_gross.shift(1).fillna(0.0) * BORROW_ANNUAL / ANN
    net = (gross - transaction_cost - borrow).fillna(0.0).loc[OOS_START:OOS_END]
    stressed = (
        (
            gross
            - 2.0 * transaction_cost
            - short_gross.shift(1).fillna(0.0) * 2.0 * BORROW_ANNUAL / ANN
        )
        .fillna(0.0)
        .loc[OOS_START:OOS_END]
    )
    long_contribution = gross_by_symbol.where(held > 0.0, 0.0).drop(columns=[SPY]).sum(axis=1)
    short_contribution = gross_by_symbol.where(held < 0.0, 0.0).drop(columns=[SPY]).sum(axis=1)

    OUT.mkdir(parents=True, exist_ok=True)
    data_manifest_payload = {
        "schema": "canli.alphac-probe-input-manifest.v1",
        "filing_manifest_sha256": pair_result["source_manifest"]["sha256"],
        "ticker_history_sha256": file_sha256(TICKER_HISTORY),
        "market_calendar": {
            "symbol": SPY,
            "start": str(calendar.min().date()),
            "end": str(calendar.max().date()),
            "sessions": len(calendar),
        },
        "market_data": market_sources,
        "corporate_actions": action_sources,
    }
    data_manifest_canonical = json.dumps(
        data_manifest_payload, sort_keys=True, separators=(",", ":")
    ).encode()
    data_manifest_payload["content_hash"] = (
        "sha256:" + hashlib.sha256(data_manifest_canonical).hexdigest()
    )
    data_manifest_path = OUT / "input_data_manifest.json"
    data_manifest_path.write_text(json.dumps(data_manifest_payload, indent=2) + "\n")
    data_manifest_sha256 = file_sha256(data_manifest_path)
    write_curve(net, OUT)
    selected.to_parquet(OUT / "selected_events.parquet", index=False)
    weights.loc[:, (weights != 0).any()].to_parquet(OUT / "weights.parquet")

    record_probe_trial(
        "earnings_narrative_change",
        trial_config,
        net,
        now_ms=int(pd.Timestamp.now(tz="UTC").timestamp() * 1000),
        periods_per_year=ANN,
        prereg=str(PREREG),
    )
    n_trials, variance = selection_context(root=ROOT)
    dsr = dsr_from_returns(
        net,
        n_trials=n_trials,
        sr_trials_variance=variance,
        periods_per_year=ANN,
    )
    diversification, diversification_alignment, aligned_simple = (
        canonical_diversification_evidence(net)
    )
    diversification_payload = {
        "schema": "canli.alphac-canonical-diversification.v1",
        "family_trial_account": "earnings_narrative_change",
        "return_identity_id": "earnings_narrative_change_v1",
        "alignment": diversification_alignment,
        "report": diversification.to_dict(),
    }
    diversification_canonical = json.dumps(
        diversification_payload, sort_keys=True, separators=(",", ":")
    ).encode()
    diversification_payload["content_hash"] = (
        "sha256:" + hashlib.sha256(diversification_canonical).hexdigest()
    )
    diversification_path = OUT / "diversification.json"
    diversification_path.write_text(json.dumps(diversification_payload, indent=2) + "\n")
    correlation = {
        "ordinary_by_sleeve": diversification.pairwise_correlations,
        "average": diversification.average_pairwise_correlation,
        "max_pair": diversification.max_pairwise_correlation,
        "ordinary_upper_95_by_sleeve": diversification.pairwise_correlation_upper_95,
        "max_pair_upper_95": diversification.max_pairwise_correlation_upper_95,
        "stressed_by_sleeve": diversification.stressed_pairwise_correlations,
        "max_stressed": diversification.max_stressed_pairwise_correlation,
        "stressed_upper_95_by_sleeve": (
            diversification.stressed_pairwise_correlation_upper_95
        ),
        "max_stressed_upper_95": (
            diversification.max_stressed_pairwise_correlation_upper_95
        ),
        "observations": diversification.observations,
        "stressed_observations": diversification.stressed_observations,
        "candidate_mean_on_book_es_days": diversification.candidate_mean_on_book_es_days,
        "stressed_joint_loss_rate": diversification.stressed_joint_loss_rate,
        "artifact": str(diversification_path),
        "artifact_sha256": file_sha256(diversification_path),
        "content_hash": diversification_payload["content_hash"],
    }
    book = marginal_book_report(aligned_simple, diversification)
    spy_frame = pd.concat({"candidate": net, "spy": simple_open[SPY]}, axis=1).dropna()
    realized_beta = float(spy_frame["candidate"].cov(spy_frame["spy"]) / spy_frame["spy"].var())
    capacity = capacity_report(selected, weights)
    metrics = {
        "net_sharpe": sharpe(net),
        "newey_west_t": nw_t(net),
        "dsr": dsr.dsr,
        "psr": dsr.psr,
        "n_trials_union_including_candidate": n_trials,
        "sr_trial_variance": variance,
        "max_drawdown": max_drawdown(net),
        "skew": float(net.skew()),
        "realized_spy_beta": realized_beta,
        "turnover_ann": float(weights.diff().abs().sum(axis=1).mean() * ANN),
        "net_sharpe_at_2x_costs": sharpe(stressed),
        "long_leg_gross_contribution": float(long_contribution.loc[OOS_START:OOS_END].sum()),
        "short_leg_gross_contribution": float(short_contribution.loc[OOS_START:OOS_END].sum()),
        "capacity": capacity,
    }
    gates = {
        "net_sharpe_at_least_0_40": metrics["net_sharpe"] >= 0.40,
        "dsr_at_least_0_95": metrics["dsr"] >= 0.95,
        "newey_west_t_at_least_2": metrics["newey_west_t"] >= 2.0,
        "stressed_sharpe_at_least_0_40": metrics["net_sharpe_at_2x_costs"] >= 0.40,
        "absolute_beta_at_most_0_10": abs(realized_beta) <= 0.10,
        "average_correlation_at_most_0_15": correlation["average"] <= 0.15,
        "max_pair_correlation_at_most_0_35": correlation["max_pair"] <= 0.35,
        "max_stressed_correlation_at_most_0_50": correlation["max_stressed"] <= 0.50,
        "max_pair_correlation_upper_95_at_most_0_35": (
            correlation["max_pair_upper_95"] <= 0.35
        ),
        "max_stressed_correlation_upper_95_at_most_0_50": (
            correlation["max_stressed_upper_95"] <= 0.50
        ),
        "correlation_observations_at_least_252": correlation["observations"] >= 252,
        "stressed_observations_at_least_63": correlation["stressed_observations"] >= 63,
        "book_delta_positive": book["delta_sharpe"] > 0,
        "mean_zero_book_delta_positive": book["mean_zero_delta_sharpe"] > 0,
        "all_leave_one_year_out_positive": book["all_leave_one_year_out_positive"],
        "book_max_drawdown_delta_at_most_0_01": book["max_drawdown_delta"] <= 0.01,
        "book_expected_shortfall_delta_nonpositive": (
            book["expected_shortfall_delta"] <= 0.0
        ),
        "long_leg_positive": metrics["long_leg_gross_contribution"] > 0,
        "short_leg_positive": metrics["short_leg_gross_contribution"] > 0,
        "capacity_at_least_5m": capacity["p05_usd_at_1pct_adv"] >= 5_000_000,
    }
    research_gates_pass = all(gates.values())
    admission = admission_review(gates, correlation["artifact_sha256"])
    lineage = {
        "preregistration_sha256": file_sha256(PREREG),
        "data_manifest_sha256": data_manifest_sha256,
        "data_manifest_path": str(data_manifest_path),
        "filing_manifest_sha256": pair_result["source_manifest"]["sha256"],
        "ticker_history_sha256": file_sha256(TICKER_HISTORY),
        "corpus_parts_sha256": corpus["parts_sha256"],
        "corpus_result_sha256": file_sha256(CORPUS_RESULT),
        "pair_file_sha256": pair_result["pair_file_sha256"],
        "pair_result_sha256": file_sha256(PAIRS_RESULT),
        "runner_sha256": file_sha256(RUNNER),
        "diversification_report_sha256": correlation["artifact_sha256"],
        "admission_contract_sha256": admission["contract_sha256"],
        "return_identity_reservation_sha256": file_sha256(RESERVATION),
    }
    result = {
        "schema": "canli.earnings-narrative-change-probe.v1",
        "preregistration": str(PREREG),
        "hypotheses_spent": 1,
        "return_identity_reservation": reservation,
        "pbo": {
            "status": "NOT_DEFINED_SINGLE_IDENTITY",
            "value": None,
            "reason": "one locked configuration has no selection surface",
        },
        "corpus": corpus,
        "pairs": pair_result,
        "mapping": {"eligible_before_prices": len(mapped), "rejections": mapping_rejections},
        "selection": {
            "selected_rows": len(selected),
            "selected_cohorts": int(selected["cohort_month"].nunique()),
            "rejections": selection_rejections,
            "terminal_force_flats": force_flats,
            "deferred_target_changes_during_missing_opens": deferred_trades,
        },
        "metrics": metrics,
        "annual_oos": annual_report(net),
        "correlation": correlation,
        "book": book,
        "lineage": lineage,
        "gates": gates,
        "admission_review": admission,
        "verdict": ("DATA-ESCALATE" if research_gates_pass else "KILL"),
        "data_escalation": (
            {
                "reason": "point-in-time historical locate/borrow evidence is unavailable",
                "terminal_force_flats": bool(force_flats),
                "alpaca_relevant_only_after_research_approval": True,
            }
            if research_gates_pass
            else None
        ),
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
