"""Every forward packet is published at the URL its reservation promised before the result.

Until 2026-09-24 only crypto_carry_portable_v1's reserved URL existed; the 120 narrative-batch
reservations promised /glassbox/trial-packets/<label> and those URLs answered 404.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "research_export_reserved_aliases_under_test", ROOT / "scripts" / "research_export.py"
)
assert _SPEC and _SPEC.loader
EXPORT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(EXPORT)


def _register(tmp_path: Path, reservations: dict[str, dict]) -> dict:
    rows = []
    for key, reservation in reservations.items():
        path = tmp_path / f"{key}.json"
        path.write_text(json.dumps(reservation), encoding="utf-8")
        rows.append({"hypothesis_key": key, "reservation_path": path.name})
    return {"identities": rows}


def test_each_reserved_url_maps_to_its_packet(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(EXPORT, "REPO", tmp_path)
    register = _register(
        tmp_path,
        {
            "aaaa": {
                "hypothesis_identity": "aaaa",
                "packet_public_path": "/glassbox/trial-packets/crypto_carry_portable_v1.json",
            },
            "bbbb": {
                "hypothesis_identity": "bbbb",
                "packet_public_path": "/glassbox/trial-packets/alphac-vol-control-primary-20260913",
            },
            "cccc": {
                "hypothesis_identity": "cccc",
                "packet_public_path": "/glassbox/trial-packets/cccc.json",
            },
        },
    )
    assert EXPORT.reserved_packet_aliases(register) == (
        {
            "aaaa": "crypto_carry_portable_v1.json",
            "bbbb": "alphac-vol-control-primary-20260913",
        },
        {},
    )
    assert EXPORT.reserved_packet_aliases(None) == ({}, {})


@pytest.mark.parametrize(
    ("reservation", "message"),
    [
        (
            {"hypothesis_identity": "other", "packet_public_path": "/glassbox/trial-packets/x"},
            "not for aaaa",
        ),
        (
            {"hypothesis_identity": "aaaa", "packet_public_path": "/glassbox/elsewhere/x.json"},
            "unpublishable",
        ),
        (
            {"hypothesis_identity": "aaaa", "packet_public_path": "/glassbox/trial-packets/../x"},
            "unpublishable",
        ),
        (
            {
                "hypothesis_identity": "aaaa",
                "packet_public_path": "/glassbox/trial-packets/index.json",
            },
            "collides with an index",
        ),
    ],
)
def test_a_wrong_or_unsafe_reservation_fails_closed(
    tmp_path: Path, monkeypatch, reservation: dict, message: str
) -> None:
    monkeypatch.setattr(EXPORT, "REPO", tmp_path)
    with pytest.raises(ValueError, match=message):
        EXPORT.reserved_packet_aliases(_register(tmp_path, {"aaaa": reservation}))


def test_a_url_several_reservations_promised_goes_to_none_of_them(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(EXPORT, "REPO", tmp_path)
    same = "/glassbox/trial-packets/shared"
    register = _register(
        tmp_path,
        {
            "aaaa": {"hypothesis_identity": "aaaa", "packet_public_path": same},
            "bbbb": {"hypothesis_identity": "bbbb", "packet_public_path": same},
        },
    )
    aliases, shared = EXPORT.reserved_packet_aliases(register)
    assert aliases == {}
    assert [row["hypothesis_key"] for row in shared["shared"]] == ["aaaa", "bbbb"]
    document = json.loads(EXPORT._shared_reserved_url_document("shared", shared["shared"]))
    assert document["reserved_public_path"] == same
    assert [row["packet_public_path"] for row in document["claimants"]] == [
        "/glassbox/trial-packets/aaaa.json",
        "/glassbox/trial-packets/bbbb.json",
    ]
