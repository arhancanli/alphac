"""No-return parity checks on sealed historical inputs; not prospective observations."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/analysis/alphatrend_directional_20260912_attempt2"
OUT = ROOT / "evidence/alphatrend-observation-recorder-20260912_completed"


def write(path, data):
    with path.open("x") as f:
        json.dump(data, f, indent=2, allow_nan=False)
        f.write("\n")


def main():
    import alphaforge.features.library  # noqa: F401
    from alphaforge.backtest import StrategyContext
    from alphaforge.config.settings import load_settings
    from alphaforge.config.sleeve import sleeve_for
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.portfolio.strategy import BlendStrategy
    from alphaforge.research import zoo
    from alphaforge.signals.service import SignalService
    from alphaforge.validation.input_snapshot import validate_input_snapshot
    from alphaforge.validation.trend_observation import TrendObservationJournal, session_window

    OUT.mkdir(parents=True, exist_ok=False)
    manifest = validate_input_snapshot(SOURCE / "candidate/input_snapshot")
    config = json.loads((SOURCE / "reservation.json").read_text())["trial_config"]
    samples = ["2026-01-16", "2026-01-20", "2026-07-02", "2026-07-06", "2026-08-14", "2026-08-17"]
    write(
        OUT / "protocol.json",
        {
            "scope": "REPLAY_DIAGNOSTIC_NO_NEW_RETURN_TRIAL",
            "samples": samples,
            "allocation": "First two archived legs; identical contexts and persistent state",
            "signal_tests": [
                "full archived frame exact reproduction",
                "existing on_bar_close at model session boundary",
                "causal IC weights from history with no next-session open available",
            ],
            "candidate_snapshot": manifest["content_hash"],
            "parameters_changed": False,
        },
    )
    shutil.copy2(SOURCE / "state/ops.sqlite", OUT / "ops.sqlite")
    settings = load_settings("managed_futures", root=ROOT)
    sleeve = sleeve_for(settings.data.asset_class)
    paths = LakePaths(SOURCE / "lake_mf")
    reader = PITDataReader(paths)
    universe = UniverseStore(paths)
    zoo.register_all()
    saved = pd.read_parquet(SOURCE / "candidate/input_snapshot/derived_signal_frame.parquet")
    results = []
    with InstrumentStore(OUT / "ops.sqlite") as store:
        service = SignalService(
            FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
            universe,
            default_registry(),
            settings.signals,
            alpha_names=config["alpha_names"],
            sleeve=sleeve,
            blend_normalization="directional_rms",
        )
        frame, mask, zs = service._panel(config["start"], config["end"])
        weights = service._weights_from_panel(frame, mask, zs)
        pd.testing.assert_frame_equal(
            service._emit(frame, mask, zs, weights), saved, check_exact=True
        )
        for date in samples:
            ts = int(pd.Timestamp(date, tz="UTC").timestamp() * 1000)
            model_time = sleeve.calendar.next_bar_open(ts, sleeve.anchor_tf)
            expected = saved.xs(ts, level="ts_open")
            live = service.on_bar_close(model_time, weights=weights).reindex(expected.index)
            err = float(np.nanmax(np.abs(live.mu_ann - expected.mu_ann)))
            keep = frame.index.get_level_values("ts_open") <= ts
            cut = frame.loc[keep]
            cutmask = mask.loc[keep]
            cutzs = {k: v.loc[keep] for k, v in zs.items()}
            known_weights = service._weights_from_panel(cut, cutmask, cutzs)
            causal = service._emit(cut, cutmask, cutzs, known_weights).xs(ts, level="ts_open")
            error_causal = float(np.nanmax(np.abs(causal.mu_ann - expected.mu_ann)))
            results.append(
                {
                    "session": date,
                    "model_decision_ms": model_time,
                    "asof_mu_max_abs_error": err,
                    "asof_matches": bool(
                        np.allclose(
                            live.mu_ann, expected.mu_ann, rtol=1e-9, atol=1e-12, equal_nan=True
                        )
                    ),
                    "known_history_mu_max_abs_error": error_causal,
                    "known_history_matches": bool(
                        np.allclose(
                            causal.mu_ann, expected.mu_ann, rtol=1e-9, atol=1e-12, equal_nan=True
                        )
                    ),
                    "max_weight_difference": float(
                        (known_weights.asof(ts) - weights.asof(ts)).abs().max()
                    ),
                }
            )
        write(OUT / "signal_parity.json", results)
        # Compare the actual allocator's precomputed and provider seams. Contexts
        # are archived marks, not newly simulated prices or a new return curve.
        direct = BlendStrategy(settings, signal_frame=saved, allocator="trend", rebalance_bars=10)

        def provider(t):
            prior = sleeve.calendar.floor_bar(t - 1, sleeve.anchor_tf)
            return saved.xs(prior, level="ts_open").mu_ann.to_dict()

        streamed = BlendStrategy(
            settings, mu_provider=provider, allocator="trend", rebalance_bars=10
        )
        epoch = {
            "epoch_id": "historical-parity-only",
            "mode": "REPLAY_DIAGNOSTIC",
            "candidate_id": "ec7ec19175ac10a9",
            "candidate_fingerprint": hashlib.sha256(
                (SOURCE / "reservation.json").read_bytes()
            ).hexdigest(),
            "initial_state": {"decisions": 0},
        }
        clock = [0]
        journal = TrendObservationJournal(
            OUT / "replay_observations.sqlite", epoch=epoch, clock=lambda: clock[0]
        )
        count = 0
        contexts = []
        max_error = 0.0
        mismatches = []
        for leg in sorted((SOURCE / "candidate/legs").glob("leg_*"))[:2]:
            equity = pd.read_parquet(leg / "equity.parquet")
            positions = pd.read_parquet(leg / "positions.parquet")
            meta = json.loads((leg / "run_meta.json").read_text())["config"]
            in_leg = (saved.index.get_level_values("ts_open") >= meta["train_start"]) & (
                saved.index.get_level_values("ts_open") < meta["end"]
            )
            direct.load_leg(saved.loc[in_leg])
            instruments = {
                iid: (store.get(iid, as_of=meta["end"]) or store.history(iid)[0][2])
                for iid in config["instrument_ids"]
            }
            for row in equity.itertuples(index=False):
                quantities = (
                    positions.loc[positions.ts == row.ts].set_index("instrument_id").qty.to_dict()
                )
                ctx = StrategyContext(
                    reader=reader,
                    tf=sleeve.anchor_tf,
                    ts=int(row.ts),
                    equity=float(row.equity),
                    positions=quantities,
                    instruments=instruments,
                    asset_class=settings.data.asset_class,
                )
                target = dict(direct.on_bar_close(ctx))
                live_target = dict(streamed.on_bar_close(ctx))
                keys = set(target) | set(live_target)
                error = max(
                    (abs(target.get(k, 0) - live_target.get(k, 0)) for k in keys), default=0.0
                )
                max_error = max(max_error, error)
                if set(target) != set(live_target) or error > 1e-12:
                    mismatches.append(
                        {
                            "leg": leg.name,
                            "model_decision_ms": int(row.ts),
                            "target_max_abs_error": error,
                            "research_targets": target,
                            "continuous_provider_targets": live_target,
                        }
                    )
                session = sleeve.calendar.floor_bar(int(row.ts) - 1, sleeve.anchor_tf)
                close, _ = session_window(session)
                clock[0] = close + 3600000
                count += 1
                payload = {
                    "model_decision_ms": int(row.ts),
                    "equity": float(row.equity),
                    "positions": quantities,
                    "source_snapshot": manifest["content_hash"],
                    "leg": leg.name,
                    "claim": "Archived context replay, not historically received data",
                }

                current_mu = provider(int(row.ts))

                def compute(inputs, state, decision_target=live_target, mu=current_mu):
                    return {
                        "signals": {k: float(v) if np.isfinite(v) else None for k, v in mu.items()},
                        "targets": decision_target,
                        "allocation_state": {"decisions": state["decisions"] + 1},
                    }

                outcome = journal.observe(
                    session_ms=session,
                    inputs=payload,
                    received_ms=clock[0],
                    state_before={"decisions": count - 1},
                    compute=compute,
                )
                assert outcome["status"] == "DECISION"
                contexts.append((ctx, live_target))
            # Reopen durable journal and rebuild allocation state by replaying all
            # captured contexts. This checks event-source recovery, not a new live epoch.
            journal.close()
            journal = TrendObservationJournal(
                OUT / "replay_observations.sqlite", epoch=epoch, clock=lambda: clock[0]
            )
            recovered = BlendStrategy(
                settings, mu_provider=provider, allocator="trend", rebalance_bars=10
            )
            for ctx, expected_target in contexts:
                observed = dict(recovered.on_bar_close(ctx))
                assert observed == expected_target
            assert journal.state() == {"decisions": count}
        receipt = journal.verify()
        journal.close()
    result = {
        "archived_signal_frame_exact": True,
        "signal_samples": results,
        "allocation_contexts_compared": count,
        "allocation_target_max_abs_error": max_error,
        "allocation_restart_replay_exact": True,
        "allocation_parity_pass": not mismatches,
        "allocation_mismatches": mismatches,
        "journal": receipt,
        "scope": "Retrospective parity diagnostic, no new returns or prospective evidence",
        "ready_for_forward_activation": False,
    }
    write(OUT / "result.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
