"""Fresh-process recovery of committed diagnostic targets without recomputing signals."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from alphaforge.backtest import StrategyContext
from alphaforge.config.settings import load_settings
from alphaforge.config.sleeve import sleeve_for
from alphaforge.core.instruments import InstrumentStore
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.portfolio.strategy import BlendStrategy
from alphaforge.validation.causal_trend_journal import CausalTrendJournal
from alphaforge.validation.trend_observation import fingerprint
from alphaforge.validation.trend_producer import CausalTrendProducer

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-producer-20260912_completed"
SOURCE = ROOT / "artifacts/analysis/alphatrend_directional_20260912_attempt2"


def main():
    binding = json.loads((OUT / "binding.json").read_text())
    config = binding["trial_config"]
    readonly = sqlite3.connect(
        (OUT / "observations.sqlite").resolve().as_uri() + "?mode=ro", uri=True
    )
    epoch = json.loads(readonly.execute("SELECT payload FROM epoch WHERE id=1").fetchone()[0])
    readonly.close()
    settings = load_settings("managed_futures", root=ROOT)
    sleeve = sleeve_for(settings.data.asset_class)
    reader = PITDataReader(LakePaths(SOURCE / "lake_mf"))

    def verify(inputs):
        assert inputs["source_id"] == fingerprint(binding)
        assert all(
            hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h
            for p, h in binding["file_bindings"].items()
        )

    with InstrumentStore(OUT / "ops.sqlite") as store:
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

            def __call__(self, signals, context):
                self.mu = {k: v for k, v in signals.items() if v is not None}
                return self.strategy.on_bar_close(
                    StrategyContext(
                        reader=reader,
                        tf=sleeve.anchor_tf,
                        ts=context["decision_ms"],
                        equity=context["equity"],
                        positions=context["positions"],
                        instruments=instruments,
                        asset_class=settings.data.asset_class,
                    )
                )

        def forbidden(inputs):
            raise AssertionError("Recovery must not replace committed forecasts")

        journal = CausalTrendJournal(OUT / "observations.sqlite", epoch=epoch, binding=binding)
        before = journal.verify()
        producer = CausalTrendProducer(
            journal, verify_inputs=verify, compute_signals=forbidden, allocator_factory=Allocator
        )
        count = producer.recover()
        assert count == 2 and before == journal.verify()
        with (OUT / "fresh_process_recovery.json").open("x") as f:
            json.dump(
                {
                    "recovered_decisions": count,
                    "targets_exact": True,
                    "journal_unchanged": True,
                    "signals_recomputed": False,
                    "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                },
                f,
                indent=2,
            )
        journal.close()
    print("Fresh process recovered both allocation decisions exactly.")


if __name__ == "__main__":
    main()
