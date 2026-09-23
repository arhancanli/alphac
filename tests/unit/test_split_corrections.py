"""Stored splits that contradict the raw prices are corrected once, at the lake reader.

The 2026-09-14 kernel fix made the engine read the vendor convention (new shares per old)
correctly, and that exposed the rows that do not follow it. The direction audit
(artifacts/audit/split_adjustment_direction.json) found, in data/lake, 90 splits stored as the
reciprocal (AMRN's 1-for-20 stored as 20.0, AZN's 2026 ADR change as 2.0) and 126 "phantom"
splits whose ex-date shows no raw move at all (HON 0.5 on 2026-06-29, IESC 2.0 on 2026-08-14).
Under the fixed kernel each of them writes a fake move of the full ratio into every adjusted
series that crosses it. The raw bars are the evidence; the correction file beside the lake
records every decision, and the reader applies it so no consumer can forget to.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.data.schemas import Dataset
from alphaforge.data.store.corrections import (
    CORRECTIONS_RELPATH,
    SplitCorrection,
    apply_split_corrections,
    classify_split,
    load_split_corrections,
    write_split_corrections,
)
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter

DAY = 86_400_000
T0 = 1_750_000_000_000 - (1_750_000_000_000 % DAY)


def _closes(prices: list[float]) -> pd.Series:
    return pd.Series(prices, index=[T0 + i * DAY for i in range(len(prices))], dtype="float64")


def _ex(i: int) -> int:
    return T0 + i * DAY


FLAT = [10.0] * 6


def test_a_split_in_the_vendor_convention_needs_nothing() -> None:
    # 2-for-1 stored as 2.0 (new per old): the raw price halves on the ex-date.
    v = classify_split(_closes([*FLAT, 5.0, 5.0, 5.0]), _ex(6), 2.0)
    assert v["verdict"] == "VENDOR_CONVENTION"
    assert v["action"] is None


def test_a_reciprocal_row_is_inverted() -> None:
    # AMRN-like 1-for-20 reverse split stored as 20.0: the raw price rises twentyfold.
    v = classify_split(_closes([*FLAT, 200.0, 200.0]), _ex(6), 20.0)
    assert v["verdict"] == "RECIPROCAL"
    assert v["action"] == "invert"
    assert v["ratio"] == pytest.approx(0.05)
    assert v["ex_ms"] == _ex(6)


def test_a_split_one_session_off_is_moved_to_the_session_that_moved() -> None:
    v = classify_split(_closes([*FLAT, 10.0, 5.0, 5.0]), _ex(6), 2.0)
    assert v["verdict"] == "MISDATED"
    assert v["action"] == "redate"
    assert v["ex_ms"] == _ex(7)
    assert v["ratio"] == 2.0


def test_a_misdated_copy_of_a_split_already_stored_on_the_right_day_is_voided() -> None:
    # ACTA 2004: the same 1-for-20 stored on 05-07 and on 05-10, where the price moved. Moving
    # the first onto the second would apply the split twice; it is a duplicate.
    closes = _closes([*FLAT, 10.0, 200.0, 200.0])
    v = classify_split(closes, _ex(6), 0.05, other_splits=[(_ex(7), 0.05)])
    assert v["verdict"] == "DUPLICATE"
    assert v["action"] == "void"
    # The copy stored on the right day is itself in the vendor convention and stays.
    assert classify_split(closes, _ex(7), 0.05, other_splits=[(_ex(6), 0.05)])["action"] is None
    # A different split on the target day is not a copy: the move is still this one's.
    assert classify_split(closes, _ex(6), 0.05, other_splits=[(_ex(7), 3.0)])["verdict"] == (
        "MISDATED"
    )


def test_a_reciprocal_copy_is_a_duplicate_too() -> None:
    closes = _closes([*FLAT, 10.0, 20.0, 20.0])
    v = classify_split(closes, _ex(6), 2.0, other_splits=[(_ex(7), 0.5)])
    assert v["verdict"] == "DUPLICATE"
    assert v["action"] == "void"


def test_a_reciprocal_row_that_is_also_misdated_is_inverted_and_moved() -> None:
    v = classify_split(_closes([*FLAT, 10.0, 20.0, 20.0]), _ex(6), 2.0)
    assert v["verdict"] == "RECIPROCAL_MISDATED"
    assert v["action"] == "invert_redate"
    assert v["ratio"] == pytest.approx(0.5)
    assert v["ex_ms"] == _ex(7)


def test_a_phantom_split_with_no_raw_move_nearby_is_voided() -> None:
    # HON-like: 0.5 stored on a date where the raw price barely moves, and nothing nearby does.
    prices = [100.0, 101.0, 99.5, 100.2, 100.8, 99.9, 98.1, 99.0, 100.3, 99.7, 100.1, 100.4]
    v = classify_split(_closes(prices), _ex(6), 0.5)
    assert v["verdict"] == "PHANTOM"
    assert v["action"] == "void"


def test_a_move_that_matches_neither_convention_is_left_alone_and_reported() -> None:
    # A 3-for-1 stored as 3.0, but the ex-date shows a -20% move: not the split, not flat.
    v = classify_split(_closes([*FLAT, 8.0, 8.0, 8.0]), _ex(6), 3.0)
    assert v["verdict"] == "UNRESOLVED"
    assert v["action"] is None


def test_two_candidate_sessions_are_ambiguous_and_left_alone() -> None:
    v = classify_split(_closes([*FLAT, 10.0, 5.0, 10.0, 5.0, 5.0]), _ex(6), 2.0)
    assert v["verdict"] == "UNRESOLVED"


def test_small_splits_and_missing_bars_are_not_judged() -> None:
    assert classify_split(_closes([*FLAT, 9.5]), _ex(6), 1.05)["verdict"] == "SMALL"
    assert classify_split(_closes(FLAT), _ex(6), 2.0)["verdict"] == "UNDETERMINED"
    assert classify_split(_closes(FLAT), _ex(0), 2.0)["verdict"] == "UNDETERMINED"
    assert classify_split(_closes(FLAT), _ex(3), float("nan"))["verdict"] == "INVALID"


def _table(rows: list[tuple[str, int, float, str]]) -> pa.Table:
    ts = pa.timestamp("ms", tz="UTC")
    return pa.table(
        {
            "instrument_id": pa.array([r[0] for r in rows], type=pa.string()),
            "action_type": pa.array([r[3] for r in rows], type=pa.string()),
            "ex_date": pa.array([r[1] for r in rows], type=ts),
            "available_at": pa.array([r[1] - 7 * DAY for r in rows], type=ts),
            "ratio": pa.array([r[2] for r in rows], type=pa.float64()),
            "cash_amount": pa.array([None] * len(rows), type=pa.float64()),
            "ingested_at": pa.array([r[1] - 6 * DAY for r in rows], type=ts),
        }
    )


CORRECTIONS = (
    SplitCorrection("A", _ex(6), 20.0, "invert", 0.05, _ex(6), "RECIPROCAL"),
    SplitCorrection("B", _ex(6), 2.0, "redate", 2.0, _ex(7), "MISDATED"),
    SplitCorrection("C", _ex(6), 0.5, "void", 0.5, _ex(6), "PHANTOM"),
)


def test_apply_corrects_only_rows_whose_stored_value_still_matches() -> None:
    table = _table(
        [
            ("A", _ex(6), 20.0, "split"),
            ("B", _ex(6), 2.0, "split"),
            ("C", _ex(6), 0.5, "split"),
            # No correction names A on this date, and C's dividend is not a split: both untouched.
            ("A", _ex(9), 20.0, "split"),
            ("C", _ex(6), 1.0, "dividend"),
        ]
    )
    out = apply_split_corrections(table, CORRECTIONS).to_pylist()
    keyed = {
        (r["instrument_id"], r["action_type"], r["ex_date"].timestamp() * 1000): r for r in out
    }
    assert keyed[("A", "split", _ex(6))]["ratio"] == pytest.approx(0.05)
    assert ("B", "split", _ex(6)) not in keyed
    assert keyed[("B", "split", _ex(7))]["ratio"] == 2.0
    assert ("C", "split", _ex(6)) not in keyed
    assert keyed[("C", "dividend", _ex(6))]["ratio"] == 1.0
    assert keyed[("A", "split", _ex(9))]["ratio"] == 20.0
    assert len(out) == 4


def test_the_file_round_trips_and_is_content_hashed(tmp_path: Path) -> None:
    path = write_split_corrections(tmp_path, CORRECTIONS, evidence={"source": "unit"})
    assert path == tmp_path / CORRECTIONS_RELPATH
    loaded, sha = load_split_corrections(tmp_path)
    assert loaded == CORRECTIONS
    assert sha is not None and sha.startswith("sha256:")
    doc = json.loads(path.read_text())
    doc["corrections"][0]["ratio"] = 99.0
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="content hash"):
        load_split_corrections(tmp_path)


def test_a_lake_without_a_file_has_no_corrections(tmp_path: Path) -> None:
    assert load_split_corrections(tmp_path) == ((), None)


def test_the_reader_serves_corrected_rows_including_one_moved_into_the_window(
    tmp_path: Path,
) -> None:
    paths = LakePaths(tmp_path / "lake")
    _write_actions(paths, [("A", _ex(6), 20.0), ("B", _ex(6), 2.0), ("C", _ex(6), 0.5)])
    reader = PITDataReader(paths)
    before = reader.corporate_actions(["A", "B", "C"], start=_ex(0), end=_ex(20), as_of=_ex(30))
    assert sorted(before.column("ratio").to_pylist()) == [0.5, 2.0, 20.0]
    assert reader.corrections_sha256 is None

    write_split_corrections(paths.root, CORRECTIONS, evidence={"source": "unit"})
    reader = PITDataReader(paths)
    after = reader.corporate_actions(["A", "B", "C"], start=_ex(0), end=_ex(20), as_of=_ex(30))
    rows = {r["instrument_id"]: r for r in after.to_pylist()}
    assert set(rows) == {"A", "B"}
    assert rows["A"]["ratio"] == pytest.approx(0.05)
    assert rows["B"]["ex_date"].timestamp() * 1000 == _ex(7)
    assert reader.corrections_sha256 is not None
    assert after.schema == before.schema
    # A window that ends between the stored and the corrected ex-date serves the row where
    # the correction puts it, not where the vendor did.
    edge = reader.corporate_actions(["B"], start=_ex(0), end=_ex(7), as_of=_ex(30))
    assert edge.num_rows == 0
    edge = reader.corporate_actions(["B"], start=_ex(7), end=_ex(8), as_of=_ex(30))
    assert edge.num_rows == 1


def _write_actions(paths: LakePaths, rows: list[tuple[str, int, float]]) -> None:
    writer = LakeWriter(paths)
    for iid, ex, ratio in rows:
        writer.write(Dataset.CORPORATE_ACTIONS, _table([(iid, ex, ratio, "split")]))


def test_the_ratio_is_never_non_positive_after_a_correction() -> None:
    for c in CORRECTIONS:
        assert c.ratio > 0 and math.isfinite(c.ratio)


def _builder():  # type: ignore[no-untyped-def]
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_split_corrections_under_test",
        Path(__file__).resolve().parents[2] / "scripts" / "build_split_corrections.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_builder_keeps_a_correction_only_if_the_kernel_shows_it_helps() -> None:
    builder = _builder()
    iid = "X"
    prices = [10.0] * 12 + [200.0] * 12  # a 1-for-20 reverse split on session 12
    closes = _closes(prices)
    stored = [(_ex(12), 20.0)]  # stored reciprocal
    good = SplitCorrection(iid, _ex(12), 20.0, "invert", 0.05, _ex(12), "RECIPROCAL")
    bad = SplitCorrection(iid, _ex(12), 20.0, "redate", 20.0, _ex(15), "MISDATED")
    (_, before_g, after_g, kept_g), (_, before_b, after_b, kept_b) = builder.verify_instrument(
        closes, iid, stored, [good, bad]
    )
    assert kept_g and after_g < 0.05 < before_g
    assert not kept_b and after_b >= before_b - builder.MIN_IMPROVEMENT
