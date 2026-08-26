"""Every sanitized publication-bundle byte must match on both public surfaces."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "publication"
PRIMARY = ROOT.parent / "meridian" / "public" / "publication"
APP = ROOT.parent / "meridian-app" / "public" / "publication"


def _relative_files(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}


def test_publication_bundle_inventories_are_exact() -> None:
    source_files = _relative_files(SOURCE)
    assert len(source_files) >= 250
    assert _relative_files(PRIMARY) == source_files
    assert _relative_files(APP) == source_files


def test_every_publication_bundle_file_is_byte_identical() -> None:
    for relative in sorted(_relative_files(SOURCE)):
        expected = (SOURCE / relative).read_bytes()
        assert (PRIMARY / relative).read_bytes() == expected
        assert (APP / relative).read_bytes() == expected
