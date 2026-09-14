"""Activation is one pass over six files that must agree; the script must flip all of them, refuse
to run twice, and refuse when the fingerprint does not move (activation off the hashed surface)."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "activate_book_drawdown_brake.py"


def _module():
    spec = importlib.util.spec_from_file_location("activate_book_brake_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sandbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Copies of the six real files in tmp, the script pointed at them, a fingerprinter whose
    hash follows the sandboxed contract's activation flag."""
    module = _module()
    copies = {}
    for name in (
        "CONTROL",
        "BASE_YAML",
        "LIVE_CHANGE",
        "FORWARD_EVIDENCE",
        "STUDY_PIN",
        "PREREG_DRAFT",
    ):
        src: Path = getattr(module, name)
        dst = tmp_path / src.name
        shutil.copyfile(src, dst)
        monkeypatch.setattr(module, name, dst)
        copies[name] = dst
    # The repository's contract has been live since 2026-09-15. The script's job is the flip
    # itself, so the sandbox starts from the not-live state the real activation started from:
    # the flag off, no activation date or decision, the pre-activation status. Everything else
    # (the pins, the yaml, the change log) is the real file, so the arithmetic is the real one.
    control = json.loads(copies["CONTROL"].read_text())
    control["activation"] = {
        k: v for k, v in control["activation"].items() if k not in ("activated_on", "decision")
    }
    control["activation"]["live"] = False
    control["status"] = "MEASURED_ACCEPTED_AS_BOUND_MECHANISM_NOT_LIVE"
    copies["CONTROL"].write_text(json.dumps(control, indent=2) + "\n")
    live_change = json.loads(copies["LIVE_CHANGE"].read_text())
    old_fp = live_change["declared_fingerprint"]

    class _Fingerprinter:
        OUTPUT = tmp_path / "live_config_fingerprint.json"

        @staticmethod
        def build_fingerprint(book_aggregation: dict[str, Any] | None = None) -> dict[str, Any]:
            control = json.loads(copies["CONTROL"].read_text())
            live = control["activation"]["live"]
            return {
                "fingerprint": "sha256:" + ("b" * 64 if live else old_fp[7:]),
                "surface": {
                    "risk_path_settings": {"book_ladder_activation_live": live},
                    "book_aggregation_settings": book_aggregation or {},
                },
            }

        @staticmethod
        def main() -> int:
            return 0

    monkeypatch.setattr(module, "_load_fingerprinter", lambda: _Fingerprinter)
    # The fresh aggregation policy is what paper_trading_state publishes after the flip; the
    # sandbox states it directly rather than importing the publisher against the real contract.
    monkeypatch.setattr(
        module,
        "_fresh_book_aggregation",
        lambda: {"scheme": "fixed", "book_level_drawdown_ladder": {"dd_half_frac": 0.05}},
    )
    return module, copies, old_fp


def test_activation_flips_all_six_files_consistently(monkeypatch, tmp_path) -> None:
    module, copies, old_fp = _sandbox(monkeypatch, tmp_path)
    plan = module.plan(decision="ok lets do all of those", activated_on="2026-09-15")
    new_fp = module.apply(plan)
    assert new_fp == "sha256:" + "b" * 64 and new_fp != old_fp

    control = json.loads(copies["CONTROL"].read_text())
    assert control["activation"]["live"] is True
    assert control["activation"]["activated_on"] == "2026-09-15"
    assert control["activation"]["decision"]["words"] == "ok lets do all of those"
    assert control["status"] == control["activation"]["status_after_activation"]

    yaml_text = copies["BASE_YAML"].read_text()
    risk_block = yaml_text[yaml_text.index("risk:") :]
    assert "book_ladder:" in risk_block and "source: https" in risk_block

    live_change = json.loads(copies["LIVE_CHANGE"].read_text())
    assert live_change["declared_fingerprint"] == new_fp
    assert live_change["declared_at"] == "2026-09-15"
    entry = live_change["change_log"][-1]
    assert entry["date"] == "2026-09-15" and entry["contaminates_forward_record"] is True
    assert "ACTIVATED" in entry["change"] and "ok lets do all of those" in entry["reason"]

    forward = json.loads(copies["FORWARD_EVIDENCE"].read_text())
    assert forward["required_live_config_fingerprint"] == new_fp
    assert old_fp not in copies["STUDY_PIN"].read_text()
    assert new_fp in copies["STUDY_PIN"].read_text()
    draft = copies["PREREG_DRAFT"].read_text()
    assert old_fp not in draft and new_fp in draft
    assert f"sha256:{old_fp[7:15]}…" not in draft

    with pytest.raises(SystemExit, match="already live"):
        module.plan(decision="again", activated_on="2026-09-16")


def test_activation_refuses_when_the_fingerprint_does_not_move(monkeypatch, tmp_path) -> None:
    module, _copies, old_fp = _sandbox(monkeypatch, tmp_path)

    class _Frozen:
        OUTPUT = tmp_path / "live_config_fingerprint.json"

        @staticmethod
        def build_fingerprint(book_aggregation: dict[str, Any] | None = None) -> dict[str, Any]:
            return {"fingerprint": old_fp, "surface": {}}

        @staticmethod
        def main() -> int:
            return 0

    monkeypatch.setattr(module, "_load_fingerprinter", lambda: _Frozen)
    plan = module.plan(decision="x", activated_on="2026-09-15")
    with pytest.raises(SystemExit, match="did not move"):
        module.apply(plan)


def test_the_yaml_edit_is_idempotent_and_keeps_other_risk_keys(monkeypatch, tmp_path) -> None:
    module = _module()
    text = "risk:\n  max_gross: 1.0\n  dd_flat_halt: -0.15\nlive:\n  paper: true\n"
    once = module._set_source_https(text)
    assert "  book_ladder:" in once and "    source: https" in once
    assert "max_gross: 1.0" in once and "dd_flat_halt: -0.15" in once and "paper: true" in once
    twice = module._set_source_https(once.replace("source: https", "source: file"))
    assert twice.count("book_ladder:") == 1 and "source: https" in twice
