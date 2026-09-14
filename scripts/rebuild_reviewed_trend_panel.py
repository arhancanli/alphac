"""Rebuild diagnostic prices from reviewed actions and one corroborated raw open."""

import hashlib
import importlib.util
import json
import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-price-repair-20260912"
REBUILT = ROOT / "evidence/alphatrend-reviewed-panel-20260912"


def main():
    if REBUILT.exists():
        raise FileExistsError("Refuse to overwrite a reviewed panel")
    for directory in (
        "alphatrend-efa-event-review-20260912",
        "alphatrend-full-price-panel-20260912",
    ):
        seal = json.loads((ROOT / "evidence" / directory / "closure.json").read_text())
        for name, digest in seal.get("files", seal.get("sha256", {})).items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    receipt = json.loads((OUT / "uso_sip_receipt.json").read_text())
    response = (OUT / "uso_sip.json").read_bytes()
    assert receipt["status"] == 200 and receipt["params"]["adjustment"] == "raw"
    assert receipt["params"]["feed"] == "sip"
    assert hashlib.sha256(response).hexdigest() == receipt["sha256"]
    payload = json.loads(response)
    assert not payload["next_page_token"]
    bars = [r for r in payload["bars"]["USO"] if r["t"] == "2020-04-09T04:00:00Z"]
    assert len(bars) == 1
    bar = bars[0]
    raw_path = ROOT / "evidence/alphatrend-sharadar-direct-20260912/imputed_raw_ohlcv_v2.parquet"
    raw = pd.read_parquet(raw_path)
    stamp = int(pd.Timestamp("2020-04-09", tz="UTC").timestamp() * 1000)
    mask = (raw.symbol == "USO") & (raw.session_ms == stamp)
    assert mask.sum() == 1
    old = raw.loc[mask].iloc[0]
    assert math.isclose(old.open, 5.41, abs_tol=1e-12) and bar["o"] == 5.4
    for field, key in [("high", "h"), ("low", "l"), ("close", "c")]:
        assert math.isclose(old[field], bar[key], rel_tol=0, abs_tol=1e-12)
    archived_path = ROOT / (
        "artifacts/analysis/alphatrend_directional_20260912_attempt2/lake_mf/"
        "ohlcv_1d/instrument_id=XUSE:CASH:USOUSD/year=2020/data.parquet"
    )
    archive = pd.read_parquet(archived_path)
    archive = archive[archive.ts_open.dt.strftime("%Y-%m-%d") == "2020-04-09"]
    assert len(archive) == 1
    implied_open = float(archive.iloc[0].open / archive.iloc[0].close * old.close)
    assert abs(implied_open - bar["o"]) < 1e-6
    revised = raw.copy(deep=True)
    revised.loc[mask, "open"] = bar["o"]
    pd.testing.assert_frame_equal(raw.loc[~mask], revised.loc[~mask])
    pd.testing.assert_frame_equal(raw.drop(columns="open"), revised.drop(columns="open"))
    corrected = OUT / "reviewed_raw_ohlcv.parquet"
    revised.to_parquet(corrected, index=False)
    review = {
        "symbol": "USO",
        "session_ms": stamp,
        "old_open": old.open,
        "reviewed_open": bar["o"],
        "archived_implied_raw_open": implied_open,
        "source_volume_retained": old.volume,
        "sip_volume": bar["v"],
        "volume_disagreement_resolved": False,
        "observed_at": receipt["received_at"],
        "bindings": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [raw_path, archived_path, OUT / "uso_sip.json", corrected]
        },
    }
    (OUT / "price_review.json").write_text(json.dumps(review, indent=2) + "\n")
    builder_path = ROOT / "scripts/build_trend_full_price_panel.py"
    spec = importlib.util.spec_from_file_location("reviewed_panel_builder", builder_path)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    builder.OUT = REBUILT
    builder.RAW = corrected
    builder.EVENTS = (
        ROOT / "evidence/alphatrend-efa-event-review-20260912/revised_actions_v3.parquet"
    )
    builder.main()
    panel = pd.read_parquet(REBUILT / "paired_prices.parquet")
    previous = pd.read_parquet(
        ROOT / "evidence/alphatrend-quality-routing-20260912/quality_tagged_panel.parquet"
    )
    flags = previous[["symbol", "session_ms", "price_disputed"]].copy()
    cleared = (flags.symbol == "USO") & (flags.session_ms == stamp)
    assert cleared.sum() == 1 and flags.loc[cleared, "price_disputed"].all()
    flags.loc[cleared, "price_disputed"] = False
    panel = panel.merge(flags, on=["symbol", "session_ms"], validate="one_to_one")
    assert len(panel) == len(previous) == len(raw)
    assert panel.price_disputed.sum() == 2
    panel.to_parquet(REBUILT / "quality_tagged_panel.parquet", index=False)
    (REBUILT / "readiness.json").write_text(
        json.dumps(
            {
                "price_disputes": 2,
                "zero_volume_rows": int(panel.zero_volume.sum()),
                "payment_disputes": 4,
                "volume_difference_on_reviewed_bar": True,
                "historical_availability_proven": False,
                "runner_ready": False,
                "real_strategy_trials": 0,
                "hypothesis_union": 238,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
