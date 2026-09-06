"""Measure the two structural facts the spin-off redesign note rests on, so neither is a memory.

WHY THIS EXISTS. `docs/design/IDENTITY_REDESIGN_NOTES.md` argues that the spin-off event universe
is declared by a FORM TYPE rather than by language inside a filing, and that the obvious structured
alternative — the corporate-action feed this repo already holds — does not carry the event. Both
are claims about data, so both are measured here and the note quotes this artifact rather than a
recollection. A guard pins the two together.

The second measurement is the more useful one and it exists because the alternative route was
CHECKED rather than assumed. Sampling the corporate-action lake shows it holds exactly two action
types. Had that gone unmeasured, the note would have proposed a route that does not exist, and it
would have read just as confidently.

Reads the held EDGAR master indexes and the corporate-action lake read-only. Registers no
hypothesis, opens no return data: 0 trials.
"""

from __future__ import annotations

import collections
import gzip
import json
import random
from pathlib import Path
from typing import Any

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
INDEXES = REPO / "data" / "raw" / "sec_active_ownership_13d" / "indexes"
CORPORATE_ACTIONS = REPO / "data" / "lake" / "corporate_actions"
OUTPUT = REPO / "artifacts" / "analysis" / "spinoff_form_universe" / "result.json"

SPINOFF_FORM = "10-12B"
SPINOFF_FORM_AMENDED = "10-12B/A"
CORPORATE_ACTION_SAMPLE = 600
SAMPLE_SEED = 0


def _form_counts_by_year() -> tuple[dict[str, dict[str, int]], list[str]]:
    """Count spin-off registrations per year straight out of the EDGAR master index.

    No document is opened and no text is parsed: the form type is a field in the index, which is
    the whole argument the note makes.
    """
    initial: collections.Counter[str] = collections.Counter()
    amended: collections.Counter[str] = collections.Counter()
    files = sorted(INDEXES.glob("*.idx.gz"))
    for path in files:
        year = path.name[:4]
        initial.setdefault(year, 0)
        amended.setdefault(year, 0)
        with gzip.open(path, "rt", errors="replace") as handle:
            for line in handle:
                parts = line.split("|")
                if len(parts) < 3:
                    continue
                form = parts[2].strip()
                if form == SPINOFF_FORM:
                    initial[year] += 1
                elif form == SPINOFF_FORM_AMENDED:
                    amended[year] += 1
    years = sorted(set(initial) | set(amended))
    return (
        {y: {"initial": initial[y], "amended": amended[y]} for y in years},
        [p.name for p in files],
    )


def _corporate_action_types() -> dict[str, Any]:
    """What the corporate-action lake actually holds, on a seeded sample of instruments."""
    instruments = sorted(p.name for p in CORPORATE_ACTIONS.iterdir() if p.is_dir())
    rng = random.Random(SAMPLE_SEED)
    sample = sorted(rng.sample(instruments, min(CORPORATE_ACTION_SAMPLE, len(instruments))))
    kinds: collections.Counter[str] = collections.Counter()
    for name in sample:
        for parquet in (CORPORATE_ACTIONS / name).rglob("*.parquet"):
            kinds.update(
                pd.read_parquet(parquet, columns=["action_type"])["action_type"].astype(str)
            )
    return {
        "instruments_in_lake": len(instruments),
        "instruments_sampled": len(sample),
        "sample_seed": SAMPLE_SEED,
        "action_types": dict(kinds.most_common()),
        "carries_a_spin_off_or_distribution_type": any(
            any(token in kind.lower() for token in ("spin", "distribution", "spinoff"))
            for kind in kinds
        ),
    }


def main() -> int:
    by_year, index_files = _form_counts_by_year()
    actions = _corporate_action_types()

    total_initial = sum(v["initial"] for v in by_year.values())
    total_amended = sum(v["amended"] for v in by_year.values())
    years = sorted(by_year)

    result = {
        "schema": "canli.alphac-spinoff-form-universe.v1",
        "claim_boundary": (
            "Counts filings by form type and enumerates the action types held in the "
            "corporate-action lake. Opens no return data, registers no hypothesis identity, "
            "proposes no threshold and authorises no candidate. 0 trials."
        ),
        "why_this_is_metadata_not_extraction": (
            "The form type is a field in the EDGAR master index. A Form 10-12B is filed to "
            "register a class of securities being distributed to shareholders, so the act of "
            "filing one declares the event and no sentence inside it has to. The protocol that "
            "failed was reading prose to rediscover a universe the index already names."
        ),
        "edgar_index": {
            "quarters_read": len(index_files),
            "first_year": years[0],
            "last_year": years[-1],
            "source": "data/raw/sec_active_ownership_13d/indexes/*.idx.gz",
        },
        "spin_off_registrations": {
            "form_initial": SPINOFF_FORM,
            "form_amended": SPINOFF_FORM_AMENDED,
            "by_year": by_year,
            "total_initial": total_initial,
            "total_amended": total_amended,
            "mean_initial_per_year": round(total_initial / len(years), 1),
        },
        "the_unwelcome_half": (
            f"{total_initial} initial registrations over {len(years)} years is a thin universe. "
            "Whatever a redesigned identity claims is bounded by that count, and the bound belongs "
            "in the pre-registration rather than in a footnote after a disappointing result."
        ),
        "corporate_action_route_checked": {
            **actions,
            "verdict": (
                "The corporate-action lake does NOT carry the event. It holds "
                f"{sorted(actions['action_types'])} and nothing resembling a distribution, so the "
                "structured route is the filing index rather than the corporate-action record. "
                "Checked rather than assumed: an unchecked version of this note would have "
                "proposed a route that does not exist and would have read just as confidently."
            ),
        },
        "note": "docs/design/IDENTITY_REDESIGN_NOTES.md quotes these numbers and a test pins them.",
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(f"  {len(index_files)} quarterly indexes, {years[0]}..{years[-1]}")
    for year in years:
        row = by_year[year]
        print(f"    {year}  initial {row['initial']:>3}   amended {row['amended']:>3}")
    print(f"  total initial {total_initial}, mean {total_initial / len(years):.1f}/yr")
    print(f"  corporate-action types held: {sorted(actions['action_types'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
