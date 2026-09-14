"""Target IC-update dates explicitly: next-session prices cannot enter a prior close decision."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/analysis/alphatrend_directional_20260912_attempt2"
OUT = ROOT / "evidence/alphatrend-observation-recorder-20260912_completed"


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
    from alphaforge.research import zoo
    from alphaforge.signals.service import SignalService

    with (OUT / "weight_maturity_protocol.json").open("x") as f:
        json.dump(
            {
                "scope": "Supplementary no-return availability diagnostic",
                "selection": "Six latest IC weight-grid dates with finite archived forecasts; no outcome-based selection",  # noqa: E501
                "reason": "Calendar transition samples need not land on IC updates; explicitly test maturity boundaries",  # noqa: E501
                "rule": "At completed session t, opens from sessions after t are unavailable",
            },
            f,
            indent=2,
        )
    settings = load_settings("managed_futures", root=ROOT)
    config = json.loads((SOURCE / "reservation.json").read_text())["trial_config"]
    zoo.register_all()
    paths = LakePaths(SOURCE / "lake_mf")
    universe = UniverseStore(paths)
    with InstrumentStore(OUT / "ops.sqlite") as store:
        service = SignalService(
            FeatureEngine(
                PITDataReader(paths), store, universe, asset_class=settings.data.asset_class
            ),
            universe,
            default_registry(),
            settings.signals,
            alpha_names=config["alpha_names"],
            sleeve=sleeve_for(settings.data.asset_class),
            blend_normalization="directional_rms",
        )
        frame, mask, zs = service._panel(config["start"], config["end"])
        weights = service._weights_from_panel(frame, mask, zs)
        full = service._emit(frame, mask, zs, weights)
        dates = [
            int(t)
            for t in weights.weights.index
            if t in full.index.get_level_values(0) and full.xs(t, level=0).mu_ann.notna().any()
        ][-6:]
        results = []
        for t in dates:
            selected = frame.index.get_level_values(0) <= t
            f, m, z = (
                frame.loc[selected],
                mask.loc[selected],
                {k: v.loc[selected] for k, v in zs.items()},
            )
            known = service._weights_from_panel(f, m, z)
            observed = service._emit(f, m, z, known).xs(t, level=0)
            expected = full.xs(t, level=0)
            results.append(
                {
                    "session": str(pd.to_datetime(t, unit="ms").date()),
                    "weight_max_abs_error": float((known.asof(t) - weights.asof(t)).abs().max()),
                    "mu_max_abs_error": float((observed.mu_ann - expected.mu_ann).abs().max()),
                    "sign_changes": int(
                        (np.sign(observed.mu_ann) != np.sign(expected.mu_ann)).sum()
                    ),
                    "weights_match": bool(
                        np.allclose(known.asof(t), weights.asof(t), rtol=1e-9, atol=1e-12)
                    ),
                }
            )
    with (OUT / "weight_maturity_result.json").open("x") as f:
        json.dump(
            {
                "samples": results,
                "all_match": all(r["weights_match"] for r in results),
                "returns_computed": False,
            },
            f,
            indent=2,
            allow_nan=False,
        )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
