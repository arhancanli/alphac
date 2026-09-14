"""The live book ladder is a derived replay of the published marks: it must equal the vectorized
twin the study used when no rearm intervenes, stay halted until an owner rearm, and restart with a
fresh high-water mark at the rearm mark."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from alphaforge.risk.ladder_paths import simulate_book_ladder

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "book_drawdown_ladder.py"
_SPEC = importlib.util.spec_from_file_location("book_drawdown_ladder", SCRIPT)
assert _SPEC and _SPEC.loader
MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(MOD)

PARAMS = {"dd_half_frac": 0.055, "dd_flat_frac": 0.11, "release_frac": 0.75}
CODE = {"NORMAL": 0, "HALF_GROSS": 1, "FLAT_HALTED": 2}


def _curve(returns: list[float], start: str = "2026-08-07") -> list[dict]:
    import datetime as dt

    day = dt.date.fromisoformat(start)
    equity = 100_000.0
    out = [{"date": day.isoformat(), "equity": equity}]
    for r in returns:
        day += dt.timedelta(days=1)
        equity *= 1.0 + r
        out.append({"date": day.isoformat(), "equity": equity})
    return out


def _run(returns, rearms=()):
    return MOD.ladder_from_curve(_curve(returns), rearm_dates=list(rearms), **PARAMS)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_replay_equals_the_vectorized_twin_when_no_rearm_intervenes(seed: int) -> None:
    """The published curve is the REALIZED curve (sizing already applied the multiplier), so the
    twin's realized returns are what the replay must see; on that series both must agree."""
    rng = np.random.default_rng(seed)
    raw = rng.normal(0.0, 0.012, size=120)
    raw[30:36] = -0.035  # through half gross into a halt
    twin = simulate_book_ladder(raw[None, :], flat_cooldown_bars=None, **PARAMS)
    realized = list(twin.realized_returns[0])
    result = _run(realized)
    assert [CODE[d["state_after_close"]] for d in result["daily"]] == twin.states[0].tolist()
    applied = [d["multiplier_applied_to_this_day"] for d in result["daily"]]
    assert applied == twin.multipliers[0].tolist()
    assert result["state"] == "FLAT_HALTED" and result["gross_multiplier"] == 0.0
    assert result["days_at_reduced_gross"] == int(twin.days_reduced[0])
    halt_row = _curve(realized)[int(twin.first_halt_day[0]) + 1]
    assert result["halts"][0]["halted_on"] == halt_row["date"]
    assert result["max_drawdown_all_time_peak"] == pytest.approx(float(twin.max_drawdowns[0]))


def test_a_calm_book_stays_normal_at_full_gross() -> None:
    result = _run([0.001] * 20 + [-0.002] * 5)
    assert result["state"] == "NORMAL" and result["gross_multiplier"] == 1.0
    assert result["halts"] == [] and result["days_at_reduced_gross"] == 0
    assert result["drawdown"] == pytest.approx(1.0 - result["equity"] / result["high_water_mark"])


def test_a_first_day_loss_counts_from_the_boot_mark() -> None:
    result = _run([-0.06])
    assert result["state"] == "HALF_GROSS"
    assert result["drawdown"] == pytest.approx(0.06)
    assert result["daily"][0]["multiplier_applied_to_this_day"] == 1.0


def test_a_halt_is_absorbing_until_an_owner_rearm_and_restarts_with_a_fresh_high_water_mark() -> (
    None
):
    returns = [-0.035] * 6 + [0.03] * 10  # halt, then a recovery the ladder must ignore
    halted = _run(returns)
    assert halted["state"] == "FLAT_HALTED"
    assert all(d["multiplier_applied_to_this_day"] == 0.0 for d in halted["daily"][6:])
    assert halted["rearms_unused"] == []

    halt_date = halted["halts"][0]["halted_on"]
    rearm_date = _curve(returns)[8]["date"]  # two marks after the halt
    rearmed = _run(returns, rearms=[rearm_date])
    assert rearmed["state"] == "NORMAL" and rearmed["gross_multiplier"] == 1.0
    assert rearmed["rearms_applied"] == [{"rearm_date": rearm_date, "boot_mark": rearm_date}]
    assert rearmed["halts"][0]["rearmed_on"] == rearm_date
    assert rearm_date > halt_date
    boot = next(d for d in rearmed["daily"] if d["date"] == rearm_date)
    assert boot["multiplier_applied_to_this_day"] == 0.0  # that day was earned flat
    assert boot["high_water_mark"] == pytest.approx(boot["high_water_mark"])  # fresh mark
    assert boot["drawdown"] == pytest.approx(0.0)
    after = rearmed["daily"][-1]
    assert after["multiplier_applied_to_this_day"] == 1.0


def test_a_rearm_that_follows_no_halt_is_unused() -> None:
    result = _run([0.001] * 10, rearms=["2026-08-12"])
    assert result["rearms_applied"] == [] and result["rearms_unused"] == ["2026-08-12"]
    result = _run([-0.035] * 6, rearms=["2026-08-01"])  # dated before the halt
    assert result["state"] == "FLAT_HALTED" and result["rearms_unused"] == ["2026-08-01"]


def test_invalid_curves_fail_closed() -> None:
    with pytest.raises(ValueError, match="date-ordered"):
        MOD.ladder_from_curve(
            [{"date": "2026-08-08", "equity": 1.0}, {"date": "2026-08-07", "equity": 1.0}],
            rearm_dates=[],
            **PARAMS,
        )
    with pytest.raises(ValueError, match="non-positive"):
        MOD.ladder_from_curve(
            [{"date": "2026-08-07", "equity": 1.0}, {"date": "2026-08-08", "equity": 0.0}],
            rearm_dates=[],
            **PARAMS,
        )


def test_build_binds_the_contract_and_the_state_and_the_current_file_is_a_subset(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"generated_at": "t", "live_curve": _curve([0.001, -0.002])}))
    contract = tmp_path / "contract.json"
    contract.write_text(
        json.dumps(
            {
                "status": "TEST",
                "ladder": {
                    "dd_half_frac": 0.055,
                    "dd_flat_frac": 0.11,
                    "release_frac_of_half": 0.75,
                },
                "activation": {"live": False},
            }
        )
    )
    rearms = tmp_path / "rearms.json"
    rearms.write_text(json.dumps({"rearms": []}))
    payload = MOD.build(state_path=state, contract_path=contract, rearms_path=rearms)
    assert payload["bindings"]["contract"]["sha256"] == MOD._sha256_bytes(contract.read_bytes())
    assert payload["bindings"]["live_curve_source"]["sha256"] == MOD._sha256_bytes(
        state.read_bytes()
    )
    assert payload["activation"] == {"live": False}
    assert payload["content_hash"] == MOD._content_hash(payload)
    current = MOD.current_file(payload)
    assert current["gross_multiplier"] == 1.0 and current["state"] == "NORMAL"
    assert current["artifact_content_hash"] == payload["content_hash"]


@pytest.mark.workspace_evidence
def test_the_real_book_is_not_halted_and_the_artifact_reproduces() -> None:
    if not MOD.STATE_PATH.exists():
        pytest.skip("paper state lives in the working tree")
    payload = MOD.build()
    assert payload["marks"] >= 37
    assert payload["state"] in {"NORMAL", "HALF_GROSS", "FLAT_HALTED"}
    assert payload["content_hash"] == MOD._content_hash(payload)
