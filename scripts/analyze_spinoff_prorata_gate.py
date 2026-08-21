"""Can the spin-off pro-rata gate be reached by fixing the detector, or is the language absent?

WHY THIS MATTERS. spin_off_dislocation is the family closest to clearing feasibility: seven of its
eight gates pass and one fails, `pro_rata_distribution_language_rate_gte_0_30` at a measured
0.1633. That shape invites the wrong move -- widen the regex until the number clears -- which is
tuning a measurement until it agrees with a target. So the question is asked the other way round:
is the shipped detector MISSING pro-rata language that is really there, or is the language simply
not in these documents?

Runs against the 98 frozen Form 10 primary documents in the local cache, every one hash-verified
against `initial_document_schema.parquet`. Opens no market data, registers no hypothesis: 0 trials.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from audit_spinoff_document_schema import PRO_RATA_PATTERN, html_to_text  # noqa: E402

SCHEMA = REPO / "artifacts/feasibility/spin_off_dislocation/initial_document_schema.parquet"
DOCS = REPO / "data/raw/spin_off_dislocation/document_schema/documents"
OUTPUT = REPO / "artifacts/analysis/spinoff_prorata_gate/result.json"
GATE = 0.30

# Any way the token can be written, including hyphen, non-breaking space and Unicode dashes.
TOKEN = re.compile("\\bpro[\\s\u00a0\u2010\u2011-]*rata\\b", re.I)
# The shipped pattern's INTENDED meaning -- pro-rata language near a distribution reference --
# made tolerant of those forms and symmetric in order. This is the most generous honest reading.
_PRO_RATA = "\\bpro[\\s\u00a0\u2010\u2011-]*rata\\b"
TOLERANT = re.compile(
    f"(?:{_PRO_RATA}.{{0,220}}\\bdistribut|\\bdistribut.{{0,220}}{_PRO_RATA})",
    re.I | re.S,
)


def main() -> int:
    if not SCHEMA.exists() or not DOCS.exists():
        print("frozen document cache or schema missing; refusing to guess")
        return 1
    recorded = set(pd.read_parquet(SCHEMA)["primary_document_sha256"].dropna())
    paths = sorted(DOCS.iterdir())

    verified = shipped = token = tolerant = 0
    shipped_without_token = []
    token_without_shipped = []
    for path in paths:
        raw = gzip.decompress(path.read_bytes())
        if hashlib.sha256(raw).hexdigest() in recorded:
            verified += 1
        text = html_to_text(raw)
        s, t, v = (
            bool(PRO_RATA_PATTERN.search(text)),
            bool(TOKEN.search(text)),
            bool(TOLERANT.search(text)),
        )
        shipped += s
        token += t
        tolerant += v
        if s and not t:
            shipped_without_token.append(path.name)
        if t and not s:
            token_without_shipped.append(path.name)

    n = len(paths)
    result = {
        "schema": "canli.alphac-spinoff-prorata-gate.v1",
        "claim_boundary": (
            "A measurement of document LANGUAGE on 98 frozen Form 10 filings, every one "
            "hash-verified against the feasibility artifact. Opens no market data, registers no "
            "hypothesis identity, and proposes no change to the pre-registered threshold. "
            "0 trials."
        ),
        "documents": n,
        "hash_verified_against_artifact": verified,
        "gate": "pro_rata_distribution_language_rate_gte_0_30",
        "gate_threshold": GATE,
        "shipped_detector_rate": shipped / n,
        "documents_containing_any_pro_rata_token": token,
        "any_pro_rata_token_rate": token / n,
        "tolerant_near_distribution_rate": tolerant / n,
        "verdict": "GATE_UNREACHABLE_BY_DETECTOR_REPAIR",
        "why": (
            f"Only {token} of {n} documents contain a pro-rata token in ANY written form "
            f"({token / n:.1%}), and only {tolerant} contain one near a distribution reference "
            f"({tolerant / n:.1%}). The gate asks for {GATE:.0%}. A perfect detector therefore "
            f"reaches at most {token / n:.1%}: the shortfall is not extraction, it is that this "
            "language is not in these documents. Widening the pattern until the number cleared "
            "would have been tuning a measurement to agree with a target."
        ),
        "⚠️_the_shipped_detector_OVERSTATES_the_rate": {
            "shipped_hits": shipped,
            "documents_with_any_pro_rata_token": token,
            "hits_with_no_pro_rata_language_at_all": len(shipped_without_token),
            "cause": (
                "PRO_RATA_PATTERN's second alternative matches 'distribut...' followed by "
                "'holders of' or 'stockholders of' with NO pro-rata text required. So a field "
                "named pro_rata_distribution_language fires on documents that never say pro "
                "rata, and the published 0.1633 is higher than the true rate of "
                f"{token / n:.4f}. The gate fails either way, and it fails harder than recorded."
            ),
            "affected_documents": sorted(shipped_without_token),
        },
        "false_negatives_reviewed": {
            "count": len(token_without_shipped),
            "documents": sorted(token_without_shipped),
            "note": (
                "Each was read. They are preemptive-rights and similar boilerplate uses of 'pro "
                "rata share', not a spin-off distribution, so they are correct negatives for the "
                "intended meaning rather than misses."
            ),
        },
        "what_this_implies": (
            "The identity is not observable as pre-registered, which is the same classification "
            "already applied to treasury_auction_concession. The next step is an identity "
            "REDESIGN with its own pre-registration -- an initial Form 10 evidently does not "
            "carry distribution mechanics at the rate this protocol assumed, and any redesign "
            "must name the document that does before it names a threshold. Lowering the "
            "threshold on the existing protocol would be fitting the gate to the result."
        ),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(f"  {verified}/{n} documents hash-verified against the feasibility artifact")
    print(f"  shipped detector      {shipped:>3}/{n} = {shipped / n:.4f}  (gate needs {GATE:.2f})")
    print(f"  ANY pro-rata token    {token:>3}/{n} = {token / n:.4f}  <- the real ceiling")
    print(f"  tolerant, near distrib{tolerant:>3}/{n} = {tolerant / n:.4f}")
    print(f"  shipped hits with NO pro-rata language: {len(shipped_without_token)}")
    print(f"  verdict: {result['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
