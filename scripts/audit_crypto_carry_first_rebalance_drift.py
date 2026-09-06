#!/usr/bin/env python3
"""Exactly reproduce the crypto-carry replay's first-rebalance sizing drift.

This is deliberately a one-decision causal diagnostic, not a performance replay.
The rank allocator consumes only the ordering of ``mu_ann``.  The historical and
current order records reveal the same five longs and five shorts; assigning those
two observed tails synthetic +2/-2 scores and every unselected name 0 preserves all
information the allocator uses while removing the expensive signal recomputation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from alphaforge.config.settings import load_settings
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.time import Timeframe
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.universe.store import UniverseStore
from alphaforge.portfolio.covariance import (
    annualize_cov,
    ewma_cov,
    ledoit_wolf_cc,
    nearest_psd,
)
from alphaforge.portfolio.optimizer import (
    PortfolioConstraints,
    RankEqualVolFallback,
)
from alphaforge.portfolio.overlay import vol_target

ROOT: Final = Path(__file__).resolve().parents[1]
SOURCE: Final = ROOT / "artifacts/walkforward/crypto_carry_wk/legs/leg_00/orders.parquet"
REPLAY: Final = (
    ROOT
    / "artifacts/probe/crypto_carry_frozen_current_code_replay/legs/leg_00/orders.parquet"
)
EOS: Final = "BINANCE:PERP:EOSUSDT"
WINDOW_BARS: Final = 721
HALFLIFE_BARS: Final = 720
MIN_PERIODS: Final = 240
INITIAL_EQUITY: Final = 100_000.0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _instrument(store: InstrumentStore, instrument_id: str, as_of: int) -> Instrument:
    instrument = store.get(instrument_id, as_of)
    if instrument is not None:
        return instrument
    history = store.history(instrument_id)
    if not history:
        raise RuntimeError(f"no instrument metadata for {instrument_id}")
    # Exact fallback used by EventDrivenBacktester when the lake predates SCD2 capture.
    return history[0][2]


def _close_panel(reader: PITDataReader, ids: list[str], decision_ts: int) -> pd.DataFrame:
    tf = Timeframe.H1
    start = decision_ts - WINDOW_BARS * tf.ms
    table = reader.ohlcv(ids, start=start, end=decision_ts, as_of=decision_ts, tf=tf)
    frame = pd.DataFrame(
        {
            "instrument_id": table.column("instrument_id").to_pylist(),
            "ts_open": table.column("ts_open").cast("int64").to_pylist(),
            "close": table.column("close").to_pylist(),
        }
    )
    grid = pd.Index(range(start, decision_ts, tf.ms), name="ts_open")
    return (
        frame.pivot(index="ts_open", columns="instrument_id", values="close")
        .reindex(index=grid, columns=ids)
        .astype("float64")
    )


def _reconstruct(
    *,
    ids: list[str],
    longs: set[str],
    shorts: set[str],
    decision_ts: int,
    reader: PITDataReader,
    store: InstrumentStore,
    allocator: RankEqualVolFallback,
) -> dict[str, Any]:
    closes = _close_panel(reader, ids, decision_ts)
    returns = closes.pct_change().iloc[1:]
    finite_counts = returns.notna().sum(axis=0)
    used = [iid for iid in ids if int(finite_counts[iid]) >= 2]
    covariance = ewma_cov(
        returns.loc[:, used],
        halflife_bars=HALFLIFE_BARS,
        min_periods=MIN_PERIODS,
    )
    keep = np.flatnonzero(np.diag(covariance) > 0.0)
    used = [used[int(index)] for index in keep]
    covariance = covariance[np.ix_(keep, keep)]
    complete = returns.loc[:, used]
    full = np.flatnonzero(complete.notna().all(axis=0).to_numpy())
    shrinkage_intensity: float | None = None
    if full.size >= 2:
        block, shrinkage_intensity = ledoit_wolf_cc(
            complete.iloc[:, full].to_numpy(dtype=np.float64),
            covariance[np.ix_(full, full)],
        )
        covariance[np.ix_(full, full)] = block
    covariance_ann = annualize_cov(nearest_psd(covariance), 8760.0)

    # RankEqualVolFallback uses rank only. These scores encode the observed tails
    # exactly; the middle ranks are immaterial because k=5 in both cross-sections.
    mu = np.array(
        [2.0 if iid in longs else -2.0 if iid in shorts else 0.0 for iid in used],
        dtype=np.float64,
    )
    instruments = [_instrument(store, iid, decision_ts) for iid in used]
    result = allocator.solve(
        mu,
        covariance_ann,
        np.zeros(len(used), dtype=np.float64),
        np.full(len(used), 0.001, dtype=np.float64),
        np.array([float(instrument.can_short) for instrument in instruments]),
    )
    weights, scale = vol_target(
        result.weights,
        covariance_ann,
        0.0,  # first decision: there is no realized return history yet
        target=0.15,
        s_max=1.5,
        gross_max=1.0,
    )
    quantities: dict[str, float] = {}
    selected_weights: dict[str, float] = {}
    for iid, weight, instrument in zip(used, weights, instruments, strict=True):
        if iid not in longs | shorts:
            continue
        price = float(closes.iloc[-1][iid])
        steps = math.floor(abs(float(weight) * INITIAL_EQUITY) / price / instrument.lot_size + 1e-9)
        quantities[iid] = steps * instrument.lot_size
        selected_weights[iid] = float(weight)
    return {
        "cross_section_size": len(used),
        "jointly_complete_size": int(full.size),
        "shrinkage_intensity": shrinkage_intensity,
        "pre_overlay_gross": float(np.abs(result.weights).sum()),
        "ex_ante_vol_ann": float(result.ex_ante_vol_ann),
        "overlay_scale": float(scale),
        "target_gross": float(np.abs(weights).sum()),
        "selected_weights": selected_weights,
        "discretized_quantities": quantities,
    }


def run(output: Path) -> dict[str, Any]:
    source_orders = pd.read_parquet(SOURCE)
    replay_orders = pd.read_parquet(REPLAY)
    source_ts = int(source_orders["decision_ts"].min())
    replay_ts = int(replay_orders["decision_ts"].min())
    if source_ts != replay_ts:
        raise RuntimeError(f"first decision timestamp drift: {source_ts} != {replay_ts}")
    source_first = source_orders[source_orders["decision_ts"] == source_ts]
    replay_first = replay_orders[replay_orders["decision_ts"] == replay_ts]
    source_ids = sorted(source_first["instrument_id"].astype(str).tolist())
    replay_ids = sorted(replay_first["instrument_id"].astype(str).tolist())
    source_only = sorted(set(source_ids) - set(replay_ids))
    replay_only = sorted(set(replay_ids) - set(source_ids))
    if source_only != [EOS] or replay_only:
        raise RuntimeError(
            f"unexpected first-decision cross-section drift: {source_only=} {replay_only=}"
        )

    replay_filled = replay_first[replay_first["status"] == "filled"]
    source_filled = source_first[source_first["status"] == "filled"]
    longs = set(replay_filled.loc[replay_filled["side"] == "buy", "instrument_id"])
    shorts = set(replay_filled.loc[replay_filled["side"] == "sell", "instrument_id"])
    if set(source_filled["instrument_id"]) != longs | shorts:
        raise RuntimeError("selected tails changed; the rank-only diagnostic is not admissible")

    settings = load_settings(None)
    reader = PITDataReader(LakePaths(settings.paths.lake_dir))
    universe = UniverseStore(LakePaths(settings.paths.lake_dir))
    allocator = RankEqualVolFallback(PortfolioConstraints.from_settings(settings))
    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
        current = _reconstruct(
            ids=replay_ids,
            longs=longs,
            shorts=shorts,
            decision_ts=source_ts,
            reader=reader,
            store=store,
            allocator=allocator,
        )
        with_eos = _reconstruct(
            ids=source_ids,
            longs=longs,
            shorts=shorts,
            decision_ts=source_ts,
            reader=reader,
            store=store,
            allocator=allocator,
        )

    observed_source = {
        str(row.instrument_id): float(row.qty) for row in source_filled.itertuples()
    }
    observed_replay = {
        str(row.instrument_id): float(row.qty) for row in replay_filled.itertuples()
    }
    source_exact = observed_source == with_eos["discretized_quantities"]
    replay_exact = observed_replay == current["discretized_quantities"]
    if not source_exact or not replay_exact:
        raise RuntimeError(
            "first-rebalance reconstruction is not exact: "
            f"{source_exact=} {replay_exact=}"
        )

    eos_intervals = [
        {
            "effective_from": int(row["effective_from"].timestamp() * 1000),
            "effective_to": (
                None
                if pd.isna(row["effective_to"])
                else int(row["effective_to"].timestamp() * 1000)
            ),
            "rank": int(row["rank"]),
            "reason": str(row["reason"]),
        }
        for _, row in universe.read_intervals().to_pandas().query(
            "instrument_id == @EOS"
        ).iterrows()
    ]
    current_members = universe.membership_asof(source_ts)
    document: dict[str, Any] = {
        "schema": "canli.alphac-crypto-carry-first-rebalance-drift-audit.v1",
        "author": "Arhan Canli",
        "status": "PASS_FIRST_REBALANCE_CAUSE_EXACTLY_REPRODUCED",
        "scope": "first decision only; this does not attribute the full multi-year replay drift",
        "decision_ts": source_ts,
        "source_orders_binding": {"path": str(SOURCE.relative_to(ROOT)), "sha256": _sha256(SOURCE)},
        "replay_orders_binding": {"path": str(REPLAY.relative_to(ROOT)), "sha256": _sha256(REPLAY)},
        "cross_section_difference": {
            "source_size": len(source_ids),
            "replay_size": len(replay_ids),
            "source_only": source_only,
            "replay_only": replay_only,
            "eos_is_member_in_current_derived_universe": EOS in current_members,
            "current_eos_intervals": eos_intervals,
        },
        "causal_method": {
            "allocator": "RankEqualVolFallback",
            "observed_long_tail": sorted(longs),
            "observed_short_tail": sorted(shorts),
            "synthetic_mu": "observed longs=+2, observed shorts=-2, unselected middle=0",
            "why_exact": (
                "The allocator uses only stable rank order; k=5 in both N=21 and N=22. "
                "All other sizing inputs are read through the production covariance, overlay, "
                "instrument-grid, and lot-rounding functions."
            ),
        },
        "reconstruction": {
            "current_21_name_cross_section": current,
            "source_22_name_cross_section_with_eos": with_eos,
            "observed_replay_quantities": observed_replay,
            "observed_source_quantities": observed_source,
            "replay_quantities_exact": replay_exact,
            "source_quantities_exact": source_exact,
        },
        "conclusion": (
            "The first-rebalance quantity drift is exactly caused by the mutable derived "
            "universe snapshot: restoring EOS to the otherwise current 21-name cross-section "
            "reproduces every historical order quantity. Later path drift remains a separate "
            "causal question, including the corrected realized-vol overlay."
        ),
        "new_trials": 0,
    }
    document["content_hash"] = _content_hash(document)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT
            / "artifacts/probe/crypto_carry_replay_drift/first_rebalance_attribution.json"
        ),
    )
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.output.resolve()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
