"""The owner's governing portfolio goals, and the arithmetic every publisher derives from them.

WHY THIS FILE. On 2026-09-12 the owner recorded three outcomes for the combined book
(``docs/design/ALPHAC_OWNER_GOALS_2026-09-12.md``) and on 2026-09-14 confirmed the first in so
many words: the forward Sharpe target is 2, not the 1.5 that admission contract v6 wrote down on
2026-08-21. The admission contract's objective block cannot move to say so: its bytes are sealed by
``config/admission_v7_promotion.json``, and that objective was never a gate
(``targets_are_admission_evidence`` is false). So the goals live in ``config/owner_goals.json``,
one versioned file, and every published projection of "the objective" is derived from it here.
The sealed figures stay published beside the new ones as history: never overwritten, never
silently replaced, never pooled with the record that is measured against the new target.

The frontier arithmetic below is the sealed contract's own identity at the owner's sleeve count
and target, using the same measured per-sleeve quality and the same haircut the contract
published. It is what reaching the goal requires, not evidence that it is reachable.

Nothing here reads return data, spends a hypothesis, or establishes a target.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Final

REPO: Final[Path] = Path(__file__).resolve().parents[3]
OWNER_GOALS_PATH: Final[Path] = REPO / "config" / "owner_goals.json"
ADMISSION_CONTRACT_PATH: Final[Path] = REPO / "config" / "sleeve_admission_contract.json"
PAPER_STATE_PATH: Final[Path] = REPO / "data" / "paper" / "state.json"
SCHEMA: Final[str] = "canli.alphac-owner-goals.v1"
IDENTITY: Final[str] = "S_book = s_bar * sqrt(N / (1 + (N - 1) * rho_bar))"

_PINNED_OBJECTIVE_KEYS: Final[tuple[str, ...]] = (
    "honest_forward_sharpe_target",
    "target_total_sleeves",
    "minimum_new_sleeves",
    "portfolio_max_drawdown_target",
)


def load_owner_goals(path: Path = OWNER_GOALS_PATH) -> dict[str, Any]:
    """Read and validate the goals file, failing closed on any shape that could misprint."""
    goals: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if goals.get("schema") != SCHEMA:
        raise ValueError(f"owner goals schema is {goals.get('schema')!r}, expected {SCHEMA!r}")
    outcomes = goals["goals"]
    sharpe = outcomes["combined_forward_sharpe"]
    drawdown = outcomes["combined_max_drawdown"]
    sleeves = outcomes["qualified_economically_distinct_sleeves"]
    if not (
        type(sharpe["target"]) in (int, float)
        and math.isfinite(sharpe["target"])
        and sharpe["target"] > 0.0
    ):
        raise ValueError("combined_forward_sharpe.target must be a positive number")
    if sharpe["comparison"] != "ABOVE":
        raise ValueError("combined_forward_sharpe.comparison must be ABOVE")
    if not (isinstance(drawdown["bound"], int | float) and 0.0 < drawdown["bound"] < 1.0):
        raise ValueError("combined_max_drawdown.bound must be a fraction in (0, 1)")
    if drawdown["comparison"] != "AT_MOST":
        raise ValueError("combined_max_drawdown.comparison must be AT_MOST")
    if not isinstance(drawdown.get("mechanism_status"), str):
        raise ValueError("combined_max_drawdown.mechanism_status must state the brake's standing")
    if not (isinstance(sleeves["minimum"], int) and sleeves["minimum"] >= 2):
        raise ValueError("qualified_economically_distinct_sleeves.minimum must be an int >= 2")
    if sleeves["comparison"] != "AT_LEAST":
        raise ValueError("qualified_economically_distinct_sleeves.comparison must be AT_LEAST")
    pin = goals["supersedes"]["sleeve_admission_contract_objective"]
    for key in ("path", "sha256", *_PINNED_OBJECTIVE_KEYS):
        if key not in pin:
            raise ValueError(f"supersedes.sleeve_admission_contract_objective lacks {key!r}")
    return goals


def sealed_admission_objective(
    goals: dict[str, Any], contract_path: Path = ADMISSION_CONTRACT_PATH
) -> dict[str, Any]:
    """The superseded objective, read from the sealed contract and checked against the pin.

    The pin is the guard: if the sealed contract's bytes move, or its objective no longer says
    what the goals file records as superseded, every publisher that projects the goals fails
    closed rather than publishing history that has quietly changed.
    """
    pin = goals["supersedes"]["sleeve_admission_contract_objective"]
    raw = contract_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != pin["sha256"]:
        raise ValueError(
            "the sealed admission contract moved under the owner-goals pin: "
            f"{digest[:12]} != {str(pin['sha256'])[:12]}"
        )
    objective: dict[str, Any] = json.loads(raw)["objective"]
    for key in _PINNED_OBJECTIVE_KEYS:
        if objective[key] != pin[key]:
            raise ValueError(f"sealed objective.{key} is {objective[key]!r}, pin says {pin[key]!r}")
    if objective.get("targets_are_admission_evidence") is not False:
        raise ValueError("the sealed objective is a gate; the goals file cannot supersede a gate")
    return objective


def book_sharpe(n: int, rho_bar: float, s_bar: float) -> float:
    """The published identity: equal-risk book Sharpe from N, average correlation, mean quality."""
    return s_bar * math.sqrt(n / (1.0 + (n - 1) * rho_bar))


def psd_floor(n: int) -> float:
    """Average pairwise correlation cannot fall below -1/(N-1) for any real correlation matrix."""
    return -1.0 / (n - 1)


def rho_bar_required(n: int, s_bar: float, book_target: float) -> float:
    """Invert the identity for the average correlation that reaches ``book_target`` at ``s_bar``."""
    return (n / (book_target / s_bar) ** 2 - 1.0) / (n - 1)


def s_bar_required(n: int, rho_bar: float, book_target: float) -> float:
    """Invert the identity for the mean quality that reaches ``book_target`` at ``rho_bar``."""
    return book_target / math.sqrt(n / (1.0 + (n - 1) * rho_bar))


def _haircut_multipliers(sealed_objective: dict[str, Any]) -> list[float]:
    """The haircut ends the sealed objective priced its band at, parsed from its own keys."""
    multipliers: list[float] = []
    for key in sealed_objective["implied_in_sample_target"]:
        match = re.fullmatch(r"at_(\d+)_(\d+)x_haircut", key)
        if match is None:
            raise ValueError(f"unrecognised implied_in_sample_target key {key!r}")
        multipliers.append(float(f"{match.group(1)}.{match.group(2)}"))
    if len(multipliers) < 2:
        raise ValueError("the sealed objective prices fewer than two haircut ends")
    return sorted(multipliers)


def goal_frontier(
    goals: dict[str, Any], contract_path: Path = ADMISSION_CONTRACT_PATH
) -> dict[str, Any]:
    """What reaching the owner's goal requires, on the sealed contract's own identity and inputs.

    Mirrors the shape of the sealed ``frontier_arithmetic`` so a reader can set the two side by
    side: same identity, same measured quality on both bases, same incremental gates, same
    haircut; only N and the forward target are the owner's.
    """
    contract: dict[str, Any] = json.loads(contract_path.read_text(encoding="utf-8"))
    sealed_objective = sealed_admission_objective(goals, contract_path)
    sealed_frontier = contract["frontier_arithmetic"]
    thresholds = contract["thresholds"]
    n = int(goals["goals"]["qualified_economically_distinct_sleeves"]["minimum"])
    forward = float(goals["goals"]["combined_forward_sharpe"]["target"])
    haircuts = _haircut_multipliers(sealed_objective)
    band = [forward * haircuts[0], forward * haircuts[1]]
    gate = float(thresholds["candidate_average_correlation_to_existing_book_max"])
    quality = sealed_frontier["quality_precondition_at_the_gate"]
    bases = {
        "four_curve_basis": float(quality["s_bar_measured_four_curve_basis"]),
        "traded_basis": float(quality["s_bar_measured_traded_basis"]),
    }
    floor = psd_floor(n)

    def _label(end: float) -> str:
        return f"{end:g}"

    correlation_required = {
        basis: {
            **{f"rho_bar_required_for_{_label(end)}": rho_bar_required(n, s, end) for end in band},
            "inside_psd_floor_at_low_end": rho_bar_required(n, s, band[0]) >= floor,
        }
        for basis, s in bases.items()
    }
    low_rho_four = rho_bar_required(n, bases["four_curve_basis"], band[0])
    s_required_low = s_bar_required(n, gate, band[0])
    floor_verdict = (
        " (inside the floor)"
        if low_rho_four >= floor
        else " (OUTSIDE the floor: unreachable at this quality)"
    )
    return {
        "identity": IDENTITY,
        "source": "config/owner_goals.json projected on the sealed contract's identity and inputs",
        "target_sleeve_count": n,
        "honest_forward_sharpe_target": forward,
        "in_sample_support_band": band,
        "in_sample_support_band_unit": (
            f"IN-SAMPLE, being the band an honest forward {forward:g} implies at the "
            f"{haircuts[0]:g}x and {haircuts[1]:g}x ends of this book's own measured "
            "backtest-to-forward haircut. The headline target is the forward figure."
        ),
        "psd_floor_at_target_n": floor,
        "psd_floor_note": (
            "Average pairwise correlation cannot fall below -1/(N-1) for any real correlation "
            f"matrix. At {n} sleeves the floor is {floor:+.4f}."
        ),
        "incremental_candidate_average_correlation_gate": gate,
        "incremental_book_average_correlation_delta_gate_exclusive": float(
            thresholds["book_average_pairwise_correlation_delta_max_exclusive"]
        ),
        "incremental_gates_alone_establish_objective_floor": False,
        "incremental_gates_alone_establish_objective_ceiling": False,
        "book_sharpe_ceiling_at_zero_global_correlation": {
            f"s_bar_{basis}": book_sharpe(n, 0.0, s) for basis, s in bases.items()
        },
        "correlation_required_at_measured_quality": {
            **correlation_required,
            "note": (
                "Hold quality where the sealed contract measured it and read off the average "
                "pairwise correlation each end of the band demands at the owner's sleeve count."
            ),
        },
        "quality_precondition_at_the_gate": {
            **{f"s_bar_measured_{basis}": s for basis, s in bases.items()},
            **{f"s_bar_required_for_{_label(end)}": s_bar_required(n, gate, end) for end in band},
            "note": (
                "What the correlation gate alone does NOT buy. At the gate exactly, reaching each "
                f"end of the band requires at least this average standalone Sharpe across {n} "
                "sleeves."
            ),
        },
        "honest_reading": (
            f"At {n} sleeves of the quality the sealed contract measured "
            f"({bases['four_curve_basis']:.3f} on the four-curve basis), the low end of the band "
            f"({band[0]:g} in-sample, {forward:g} forward on the optimistic haircut) needs an "
            f"average pairwise correlation of {low_rho_four:+.4f} against a floor of {floor:+.4f}"
            f"{floor_verdict}. "
            f"At the {gate:+.2f} gate exactly it needs a mean standalone Sharpe of "
            f"{s_required_low:.3f}. The distance from today's measured quality has to be bought "
            "with per-sleeve quality, genuinely negative correlation, or both; the sleeve count "
            "alone buys none of it."
        ),
        "claim_boundary": (
            "Derived from the governing identity alone. Reads no data, runs no backtest, spends no "
            "hypothesis, and claims no candidate's correlation, sign or return. It states what "
            "the owner's goal requires, not that it is reachable."
        ),
    }


def current_sleeve_count(state_path: Path = PAPER_STATE_PATH) -> int | None:
    """The live book's sleeve count from the published paper state, or None where none exists."""
    if not state_path.exists():
        return None
    state = json.loads(state_path.read_text(encoding="utf-8"))
    return len(state["book"]["sleeves"])


def governing_objective(
    goals: dict[str, Any],
    contract_path: Path = ADMISSION_CONTRACT_PATH,
    *,
    current_sleeves: int | None = None,
    drawdown_contract_path: Path = OWNER_GOALS_PATH.parent / "drawdown_control_contract.json",
) -> dict[str, Any]:
    """The objective block every public surface publishes, projected from the owner's goals.

    Keeps the keys the site's public-claims registry points at
    (``honest_forward_sharpe_target``, ``portfolio_max_drawdown_target``,
    ``target_total_sleeves``, ``average_pairwise_correlation_objective``) and carries the sealed
    objective it supersedes in full, dated, so the old figures are history on the same page.
    """
    sealed = sealed_admission_objective(goals, contract_path)
    frontier = goal_frontier(goals, contract_path)
    outcomes = goals["goals"]
    forward = float(outcomes["combined_forward_sharpe"]["target"])
    bound = float(outcomes["combined_max_drawdown"]["bound"])
    # The goal decision is historical; activation can change later. Project the
    # current declared mechanism from its contract so the site cannot keep saying
    # "not live" after activation while the evidence epoch says it is active.
    drawdown = json.loads(drawdown_contract_path.read_text(encoding="utf-8"))
    if drawdown.get("schema") != "canli.alphac-drawdown-control-contract.v1":
        raise ValueError("drawdown mechanism contract schema is invalid")
    ladder = drawdown["ladder"]
    if (
        drawdown["bound"] != bound
        or ladder["dd_half_frac"] != bound / 2
        or ladder["dd_flat_frac"] != bound
    ):
        raise ValueError("drawdown mechanism disagrees with the owner's bound")
    live = drawdown["activation"]["live"]
    if type(live) is not bool:
        raise ValueError("drawdown mechanism activation.live must be boolean")
    status = drawdown["status"]
    live_status = drawdown["activation"]["status_after_activation"]
    if live_status != "MECHANISM_LIVE_BOUND_ENFORCED_UP_TO_ONE_DAY_OVERSHOOT":
        raise ValueError("drawdown mechanism live status is unrecognized")
    if not isinstance(status, str) or not status:
        raise ValueError("drawdown mechanism status must be nonempty")
    if (status == live_status) is not live:
        raise ValueError("drawdown mechanism status disagrees with activation.live")
    mechanism = (
        f"config/drawdown_control_contract.json declares half gross at {bound * 50:g}% "
        f"below the high-water mark and flat at {bound * 100:g}%, absorbing until an owner rearm. "
        f"Activation is declared {'live' if live else 'off'} in that contract. "
        "A daily brake can overshoot within a day; it does not guarantee the future bound. "
        "This declaration is not independent evidence of runtime enforcement."
    )
    n = int(outcomes["qualified_economically_distinct_sleeves"]["minimum"])
    haircuts = _haircut_multipliers(sealed)
    band = frontier["in_sample_support_band"]
    rho_objective = frontier["correlation_required_at_measured_quality"]["four_curve_basis"][
        f"rho_bar_required_for_{band[0]:g}"
    ]
    objective: dict[str, Any] = {
        "source": "config/owner_goals.json",
        "source_schema": goals["schema"],
        "recorded_on": goals["recorded_on"],
        "in_force_from": goals["in_force_from"],
        "honest_forward_sharpe_target": forward,
        "honest_forward_sharpe_comparison": outcomes["combined_forward_sharpe"]["comparison"],
        "honest_forward_sharpe_basis": outcomes["combined_forward_sharpe"]["basis"],
        "portfolio_max_drawdown_target": bound,
        "portfolio_max_drawdown_comparison": outcomes["combined_max_drawdown"]["comparison"],
        "portfolio_max_drawdown_statistic": outcomes["combined_max_drawdown"]["statistic"],
        "portfolio_max_drawdown_mechanism": mechanism,
        "portfolio_max_drawdown_mechanism_status": status,
        "portfolio_max_drawdown_mechanism_source": "config/drawdown_control_contract.json",
        "portfolio_max_drawdown_mechanism_status_at_goal_recording": outcomes[
            "combined_max_drawdown"
        ]["mechanism_status"],
        # The sealed MODELED objective stays published beside the owner's REALIZED bound. They
        # are different statistics; the site labels them separately and nothing mixes them.
        "expected_max_drawdown_objective": float(sealed["portfolio_max_drawdown_target"]),
        "expected_max_drawdown_objective_statistic": sealed["portfolio_max_drawdown_statistic"],
        "expected_max_drawdown_objective_note": (
            "The admission contract's sealed expected-maximum-drawdown objective and gate, "
            "evaluated on the current-composition drawdown study. Not the owner's bound: the "
            "bound is on realized maximum drawdown and is portfolio_max_drawdown_target."
        ),
        "target_total_sleeves": n,
        "target_total_sleeves_comparison": outcomes["qualified_economically_distinct_sleeves"][
            "comparison"
        ],
        "target_sleeve_count": n,
        "average_pairwise_correlation_objective": rho_objective,
        "average_pairwise_correlation_objective_note": (
            "An objective, not a gate: the average pairwise correlation at which "
            f"{n} sleeves of the quality the sealed contract measured reach {band[0]:g} in-sample, "
            f"which is forward {forward:g} on the optimistic end of the measured haircut. Derived "
            "by inverting the published identity; the PSD floor at this sleeve count is "
            f"{frontier['psd_floor_at_target_n']:+.4f}."
        ),
        "implied_in_sample_target": {
            f"at_{str(h).replace('.', '_')}x_haircut": forward * h for h in haircuts
        },
        "portfolio_sharpe_target": band,
        "portfolio_sharpe_target_unit": frontier["in_sample_support_band_unit"],
        "backtest_to_forward_haircut": sealed["backtest_to_forward_haircut"],
        "targets_are_admission_evidence": False,
        "what_reaching_it_requires": frontier["honest_reading"],
        "superseded_admission_contract_objective": {
            **sealed,
            "superseded_on": goals["in_force_from"],
            "sealed_by": "config/admission_v7_promotion.json",
            "sealed_sha256": goals["supersedes"]["sleeve_admission_contract_objective"]["sha256"],
            "why_the_bytes_stand": goals["supersedes"]["sleeve_admission_contract_objective"][
                "why_the_bytes_stand"
            ],
        },
    }
    if current_sleeves is not None:
        objective["current_sleeves"] = int(current_sleeves)
        objective["minimum_new_sleeves"] = max(0, n - int(current_sleeves))
    return objective
