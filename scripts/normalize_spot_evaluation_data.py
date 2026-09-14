"""Normalize completed, source-bound collection without computing returns."""

import hashlib
import json
from pathlib import Path

from alphaforge.validation.spot_dataset import normalize

ROOT = Path(__file__).resolve().parents[1]


def main():
    coverage_path = ROOT / "evidence/spot-coverage/coverage.json"
    raw = coverage_path.read_bytes()
    normalized = normalize(ROOT, json.loads(raw))
    normalized["coverage_sha256"] = hashlib.sha256(raw).hexdigest()
    output = ROOT / "evidence/spot-coverage/normalized.json"
    payload = (json.dumps(normalized, sort_keys=True, indent=2) + "\n").encode()
    with output.open("xb") as handle:
        handle.write(payload)
    print(
        json.dumps(
            {
                "status": normalized["status"],
                "days": len(normalized["days"]),
                "unavailable_quotes": len(normalized["unavailable_quotes"]),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "returns_computed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
