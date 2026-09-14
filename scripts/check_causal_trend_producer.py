"""Two fixed historical sessions test actual causal signals and journal restart; no returns."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from alphaforge.validation.causal_trend_journal import CausalTrendJournal
from alphaforge.validation.trend_observation import fingerprint, session_window
from alphaforge.validation.trend_producer import CausalTrendProducer

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/analysis/alphatrend_directional_20260912_attempt2"
BASE = ROOT / "artifacts/analysis/alphatrend_causal_continuous_20260912"
OUT = ROOT / "evidence/alphatrend-producer-20260912_completed"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    with path.open("x") as f:
        json.dump(data, f, indent=2, sort_keys=True, allow_nan=False)
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

    snapshot = validate_input_snapshot(BASE / "candidate/run/input_snapshot")
    config = json.loads((BASE / "candidate/reservation.json").read_text())["trial_config"]
    OUT.mkdir(exist_ok=False)
    shutil.copy2(SOURCE / "state/ops.sqlite", OUT / "ops.sqlite")
    settings = load_settings("managed_futures", root=ROOT)
    stored = json.loads((BASE / "candidate/run/input_snapshot/declared_run.json").read_text())[
        "resolved_settings"
    ]
    assert {k: v for k, v in settings.model_dump(mode="json").items() if k != "paths"} == {
        k: v for k, v in stored.items() if k != "paths"
    }
    sleeve = sleeve_for(settings.data.asset_class)
    paths = LakePaths(SOURCE / "lake_mf")
    reader = PITDataReader(paths)
    universe = UniverseStore(paths)
    zoo.register_all()
    dates = [
        int(pd.Timestamp(d, tz="UTC").timestamp() * 1000) for d in ["2026-08-20", "2026-08-21"]
    ]
    implementation = [
        Path(__file__),
        ROOT / "src/alphaforge/validation/causal_trend_journal.py",
        ROOT / "src/alphaforge/validation/trend_producer.py",
        ROOT / "src/alphaforge/validation/trend_observation.py",
        ROOT / "src/alphaforge/signals/causal_trend.py",
        ROOT / "src/alphaforge/portfolio/strategy.py",
    ]
    with InstrumentStore(OUT / "ops.sqlite") as store:
        files = [
            *sorted((SOURCE / "lake_mf").rglob("*.parquet")),
            OUT / "ops.sqlite",
            *implementation,
        ]
        hashes = {str(p.relative_to(ROOT)): sha(p) for p in files}
        binding = {
            "trial_config": config,
            "research_snapshot": snapshot["content_hash"],
            "file_bindings": hashes,
            "resolved_settings": stored,
        }
        write(OUT / "binding.json", binding)
        write(
            OUT / "protocol.json",
            {
                "sessions": dates,
                "mode": "REPLAY_DIAGNOSTIC",
                "new_return_trials": 0,
                "context": "Fixed empty diagnostic book, $100000; no modeled fills",
                "checks": "Capture first; match causal signals; recover allocator",
            },
        )

        def verify(inputs):
            assert inputs["source_id"] == fingerprint(binding)
            assert all(sha(ROOT / p) == digest for p, digest in hashes.items())

        service = CausalTrendSignalService(
            FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
            universe,
            default_registry(),
            settings.signals,
            alpha_names=config["alpha_names"],
            sleeve=sleeve,
            history_anchor=config["trend_ic_history_anchor"],
            blend_normalization="directional_rms",
        )

        def signals(inputs):
            t = inputs["session_ms"]
            # There is no next-session open in this feature/label computation.
            frame = service.compute_research(
                config["history_start"], sleeve.calendar.next_bar_open(t, sleeve.anchor_tf)
            ).xs(t, level="ts_open")
            return {iid: float(v) if np.isfinite(v) else None for iid, v in frame.mu_ann.items()}

        instruments = {
            iid: store.get(iid, as_of=config["end"]) or store.history(iid)[0][2]
            for iid in config["instrument_ids"]
        }

        class Allocator:
            def __init__(self):
                self.mu = {}
                self.strategy = BlendStrategy(
                    settings, mu_provider=lambda ts: self.mu, allocator="trend", rebalance_bars=10
                )

            def __call__(self, mu, context):
                self.mu = {k: v for k, v in mu.items() if v is not None}
                ctx = StrategyContext(
                    reader=reader,
                    tf=sleeve.anchor_tf,
                    ts=context["decision_ms"],
                    equity=context["equity"],
                    positions=context["positions"],
                    instruments=instruments,
                    asset_class=settings.data.asset_class,
                )
                return self.strategy.on_bar_close(ctx)

        epoch = {
            "epoch_id": "corrected-producer-two-session-diagnostic",
            "mode": "REPLAY_DIAGNOSTIC",
            "candidate_id": "59901461092dd7a6",
            "candidate_fingerprint": fingerprint(binding),
            "initial_state": {"completed": 0, "last_session": None},
        }
        archived = pd.read_parquet(
            BASE / "candidate/run/input_snapshot/derived_signal_frame.parquet"
        )
        checks = []
        for t in dates:

            def clock(t=t):
                return session_window(t)[0] + 1000

            journal = CausalTrendJournal(
                OUT / "observations.sqlite", epoch=epoch, binding=binding, clock=clock
            )
            producer = CausalTrendProducer(
                journal, verify_inputs=verify, compute_signals=signals, allocator_factory=Allocator
            )
            before = producer.recover()
            inputs = {
                "source_id": fingerprint(binding),
                "session_ms": t,
                "context": {
                    "decision_ms": sleeve.calendar.next_bar_open(t, sleeve.anchor_tf),
                    "equity": 100000.0,
                    "positions": {},
                },
            }
            status = producer.produce(session_ms=t, inputs=inputs, received_ms=clock())
            assert status["status"] == "DECISION"
            payload = json.loads(
                journal.conn.execute(
                    "SELECT payload FROM events WHERE kind='DECISION' ORDER BY seq DESC LIMIT 1"
                ).fetchone()[0]
            )
            expected = archived.xs(t, level="ts_open").mu_ann
            actual = pd.Series(payload["signals"], dtype=float).reindex(expected.index)
            assert np.allclose(actual, expected, rtol=1e-9, atol=1e-12, equal_nan=True)
            checks.append(
                {
                    "session": t,
                    "recovered_before": before,
                    "state": journal.state(),
                    "mu_max_error": float((actual - expected).abs().max()),
                    "status": status,
                }
            )
            journal.close()
        journal = CausalTrendJournal(
            OUT / "observations.sqlite", epoch=epoch, binding=binding, clock=clock
        )
        producer = CausalTrendProducer(
            journal, verify_inputs=verify, compute_signals=signals, allocator_factory=Allocator
        )
        write(
            OUT / "result.json",
            {
                "sessions": checks,
                "journal": journal.verify(),
                "fresh_process_state_reconstruction": producer.recover(),
                "new_return_trials": 0,
                "live_activated": False,
                "adapter_scope": "Frozen historical inputs; live feed/clock/borrow still blocked",
            },
        )
        journal.close()
    print("Two causal sessions recorded and recovered; no returns or live activation.", flush=True)


if __name__ == "__main__":
    main()
