"""The owner's 2026-10-20 headline rule: correlation first, hundreds of thousands of sleeves.

WHY. On 2026-10-15, 2026-10-17 and 2026-10-20 the owner said the thing that matters most is the
correlation between sleeves, that each sleeve may be weak as long as that correlation is very weak,
and that ALPHAC should scale to hundreds of thousands of sleeves for a Sharpe far beyond 2. On
2026-10-20 he approved making that the headline of config/owner_goals.json. This pins that:

- the file carries the rule in the owner's own words, and the words are in his dated document;
- the rule only extends the goals of 2026-09-14, which stay the checkpoints the forward-evidence
  and capital-readiness contracts evaluate (the Sharpe ladder starts at that target, the sleeve
  target is at or above that minimum, and the checkpoint values themselves do not move);
- the loader refuses a goals file that drops the rule or lets it undercut a checkpoint.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from alphaforge.research import owner_goals as og

REPO = Path(__file__).parents[2]
DOCUMENT = REPO / "docs" / "design" / "ALPHAC_OWNER_GOALS_2026-10-20.md"


@pytest.fixture
def goals() -> dict[str, Any]:
    return og.load_owner_goals()


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_rule_is_the_owners_words_from_the_owners_document(goals: dict[str, Any]) -> None:
    rule = goals["governing_rule"]
    document = _flat(DOCUMENT.read_text(encoding="utf-8"))
    assert rule["source_document"] == "docs/design/ALPHAC_OWNER_GOALS_2026-10-20.md"
    assert rule["decision"]["approval_words"] == "yes change it bro"
    assert f'"{rule["decision"]["approval_words"]}"' in document
    for quote in rule["decision"]["words"]:
        assert _flat(quote["words"]) in document, quote["on"]
    assert any(
        "the thing that matters most is the corellation" in q["words"]
        for q in rule["decision"]["words"]
    )
    assert rule["rule"].startswith("Correlation between sleeves is what matters most.")


def test_the_rule_extends_the_checkpoints_and_does_not_move_them(goals: dict[str, Any]) -> None:
    rule = goals["governing_rule"]
    checkpoints = goals["goals"]
    assert checkpoints["combined_forward_sharpe"]["target"] == 2.0
    assert checkpoints["qualified_economically_distinct_sleeves"]["minimum"] == 14
    assert checkpoints["combined_max_drawdown"]["bound"] == 0.1
    assert rule["sharpe_direction"]["ladder"] == [2.0, 3.0, 5.0]
    assert rule["sleeve_target"]["at_least"] == 100_000
    assert rule["sleeve_target"]["scale_words"] == "hundreds of thousands"
    assert rule["headline_metric"]["name"] == "effective independent bets"
    assert "<= 1 / rho_bar" in rule["headline_metric"]["identity"]


def _write(tmp_path: Path, goals: dict[str, Any]) -> Path:
    path = tmp_path / "owner_goals.json"
    path.write_text(json.dumps(goals), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda g: g.pop("governing_rule"), "correlation-first rule"),
        (lambda g: g["governing_rule"].update(rule="More sleeves."), "correlation-first rule"),
        (lambda g: g["governing_rule"]["sleeve_target"].update(at_least=13), "checkpoint"),
        (lambda g: g["governing_rule"]["sleeve_target"].update(at_least=1e5), "checkpoint"),
        (lambda g: g["governing_rule"]["sharpe_direction"].update(ladder=[1.5, 3.0]), "target"),
        (lambda g: g["governing_rule"]["sharpe_direction"].update(ladder=[2.0, 2.0]), "target"),
        (
            lambda g: g["governing_rule"]["headline_metric"]["ladder"].reverse(),
            "rise in date and count",
        ),
    ],
)
def test_the_loader_refuses_a_file_that_drops_or_undercuts_the_rule(
    goals: dict[str, Any], tmp_path: Path, mutate: Any, message: str
) -> None:
    broken = copy.deepcopy(goals)
    mutate(broken)
    with pytest.raises(ValueError, match=message):
        og.load_owner_goals(_write(tmp_path, broken))
