"""Rebuild allocator state from persisted CAPTURE events, never from in-memory contexts."""

import json
import sqlite3
from pathlib import Path

import pandas as pd

from alphaforge.backtest import StrategyContext
from alphaforge.config.settings import load_settings
from alphaforge.config.sleeve import sleeve_for
from alphaforge.core.instruments import InstrumentStore
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.portfolio.strategy import BlendStrategy
from alphaforge.validation.input_snapshot import validate_input_snapshot

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/analysis/alphatrend_directional_20260912_attempt2"
OUT = ROOT / "evidence/alphatrend-observation-recorder-20260912_completed"


def main():
    manifest = validate_input_snapshot(SOURCE / "candidate/input_snapshot")
    config = json.loads((SOURCE / "reservation.json").read_text())["trial_config"]
    frame = pd.read_parquet(SOURCE / "candidate/input_snapshot/derived_signal_frame.parquet")
    settings = load_settings("managed_futures", root=ROOT)
    sleeve = sleeve_for(settings.data.asset_class)
    reader = PITDataReader(LakePaths(SOURCE / "lake_mf"))

    def provider(ts):
        bar = sleeve.calendar.floor_bar(ts - 1, sleeve.anchor_tf)
        return frame.xs(bar, level="ts_open").mu_ann.to_dict()

    strategy = BlendStrategy(settings, mu_provider=provider, allocator="trend", rebalance_bars=10)
    db = sqlite3.connect(
        (OUT / "replay_observations.sqlite").resolve().as_uri() + "?mode=ro", uri=True
    )
    rows = db.execute(
        "SELECT a.payload, b.payload FROM events a JOIN events b ON "
        "a.session_ms=b.session_ms WHERE a.kind='CAPTURE' AND b.kind='DECISION' "
        "ORDER BY a.seq"
    ).fetchall()
    db.close()
    count = 0
    with InstrumentStore(OUT / "ops.sqlite") as store:
        for raw_capture, raw_decision in rows:
            inputs = json.loads(raw_capture)["inputs"]
            expected = json.loads(raw_decision)
            assert inputs["source_snapshot"] == manifest["content_hash"]
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
            assert dict(strategy.on_bar_close(ctx)) == expected["targets"]
            count += 1
            assert expected["allocation_state"] == {"decisions": count}
    with (OUT / "journal_restart_result.json").open("x") as f:
        json.dump(
            {
                "persisted_contexts_replayed": count,
                "target_recovery_exact": True,
                "source": "Read-only SQLite CAPTURE/DECISION events, source-bound archived price history",  # noqa: E501
                "claim": "Recovery of the continuous provider path; NOT parity with leg-reset research",  # noqa: E501
            },
            f,
            indent=2,
        )
    print(f"{count} persisted decision targets recovered exactly.")


if __name__ == "__main__":
    main()
