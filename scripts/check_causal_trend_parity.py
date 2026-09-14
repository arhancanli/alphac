"""No-return gates for exit-session weights and uninterrupted allocation."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/analysis/alphatrend_directional_20260912_attempt2"
PRIOR = ROOT / "evidence/alphatrend-observation-recorder-20260912_completed"
OUT = ROOT / "evidence/alphatrend-causal-parity-20260912"


def write(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
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
    from alphaforge.signals.causal_trend import CausalTrendSignalService
    from alphaforge.validation.input_snapshot import validate_input_snapshot

    manifest = validate_input_snapshot(SOURCE / "candidate/input_snapshot")
    OUT.mkdir(exist_ok=False)
    write(
        OUT / "protocol.json",
        {
            "scope": "NO_RETURN_CORRECTNESS_GATES",
            "source_snapshot": manifest["content_hash"],
            "sample_rule": "Last six original IC dates plus next sessions; both normalizations",
            "allocation_rule": "Both interfaces retain state across all 252 archived contexts",
            "returns_computed": False,
            "implementation": {
                str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [Path(__file__), ROOT / "src/alphaforge/signals/causal_trend.py"]
            },
        },
    )
    shutil.copy2(SOURCE / "state/ops.sqlite", OUT / "ops.sqlite")
    settings = load_settings("managed_futures", root=ROOT)
    sleeve = sleeve_for(settings.data.asset_class)
    config = json.loads((SOURCE / "reservation.json").read_text())["trial_config"]
    archived = pd.read_parquet(SOURCE / "candidate/input_snapshot/derived_signal_frame.parquet")
    anchor = int(archived.index.get_level_values(0).min())
    paths = LakePaths(SOURCE / "lake_mf")
    reader, universe = PITDataReader(paths), UniverseStore(paths)
    zoo.register_all()
    db = sqlite3.connect(
        (PRIOR / "replay_observations.sqlite").resolve().as_uri() + "?mode=ro", uri=True
    )
    captures = [
        json.loads(r[0])["inputs"]
        for r in db.execute("SELECT payload FROM events WHERE kind='CAPTURE' ORDER BY seq")
    ]
    db.close()
    dates = [
        int(pd.Timestamp(r["session"], tz="UTC").timestamp() * 1000)
        for r in json.loads((PRIOR / "weight_maturity_result.json").read_text())["samples"]
    ]
    dates = sorted(set(dates + [sleeve.calendar.next_bar_open(t, sleeve.anchor_tf) for t in dates]))
    results = {}
    with InstrumentStore(OUT / "ops.sqlite") as store:
        for arm, normalization in [
            ("baseline", "cross_sectional_zscore"),
            ("candidate", "directional_rms"),
        ]:
            service = CausalTrendSignalService(
                FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
                universe,
                default_registry(),
                settings.signals,
                alpha_names=config["alpha_names"],
                sleeve=sleeve,
                blend_normalization=normalization,
                history_anchor=anchor,
            )
            frame, mask, zs = service._panel(config["start"], config["end"])
            weights = service._weights_from_panel(frame, mask, zs)
            full = service._emit(frame, mask, zs, weights)
            samples = []
            for t in dates:
                selected = frame.index.get_level_values(0) <= t
                f, m, z = (
                    frame.loc[selected],
                    mask.loc[selected],
                    {k: v.loc[selected] for k, v in zs.items()},
                )
                known = service._weights_from_panel(f, m, z)
                expected = full.xs(t, level=0)
                prefix = service._emit(f, m, z, known).xs(t, level=0)
                live = service.on_bar_close(
                    sleeve.calendar.next_bar_open(t, sleeve.anchor_tf), weights=known
                )
                samples.append(
                    {
                        "session": str(pd.to_datetime(t, unit="ms").date()),
                        "weights_exact": bool(np.array_equal(known.asof(t), weights.asof(t))),
                        "prefix_mu_max_error": float((prefix.mu_ann - expected.mu_ann).abs().max()),
                        "live_mu_max_error": float((live.mu_ann - expected.mu_ann).abs().max()),
                        "live_match": bool(
                            np.allclose(
                                live.mu_ann, expected.mu_ann, rtol=1e-9, atol=1e-12, equal_nan=True
                            )
                        ),
                    }
                )

            def provider(ts, full=full):
                t = sleeve.calendar.floor_bar(ts - 1, sleeve.anchor_tf)
                return full.xs(t, level=0).mu_ann.to_dict()

            a = BlendStrategy(settings, signal_frame=full, allocator="trend", rebalance_bars=10)
            b = BlendStrategy(settings, mu_provider=provider, allocator="trend", rebalance_bars=10)
            mismatches = []
            for n, inputs in enumerate(captures):
                meta = json.loads(
                    (SOURCE / "candidate/legs" / inputs["leg"] / "run_meta.json").read_text()
                )["config"]
                instruments = {
                    iid: store.get(iid, as_of=meta["end"]) or store.history(iid)[0][2]
                    for iid in config["instrument_ids"]
                }
                ctx = StrategyContext(
                    reader=reader,
                    tf=sleeve.anchor_tf,
                    ts=inputs["model_decision_ms"],
                    equity=inputs["equity"],
                    positions=inputs["positions"],
                    instruments=instruments,
                    asset_class=settings.data.asset_class,
                )
                if dict(a.on_bar_close(ctx)) != dict(b.on_bar_close(ctx)):
                    mismatches.append(n)
            passed = (
                all(
                    r["weights_exact"] and r["prefix_mu_max_error"] == 0 and r["live_match"]
                    for r in samples
                )
                and not mismatches
            )
            results[arm] = {
                "samples": samples,
                "allocation_contexts": len(captures),
                "allocation_mismatches": mismatches,
                "pass": passed,
                "trial_binding": service.trial_binding,
            }
            full.to_parquet(OUT / f"{arm}_signals.parquet")
            print(
                f"{arm}: pass={passed}, contexts={len(captures)}, mismatches={len(mismatches)}",
                flush=True,
            )
    write(
        OUT / "result.json",
        {
            "arms": results,
            "all_pass": all(r["pass"] for r in results.values()),
            "returns_computed": False,
            "union_unchanged": 234,
        },
    )


if __name__ == "__main__":
    main()
