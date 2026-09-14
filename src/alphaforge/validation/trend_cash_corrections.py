"""Explicit current-vintage cash revisions; original evidence remains immutable."""

from __future__ import annotations

import math
from decimal import Decimal

import pandas as pd

from alphaforge.validation.trend_observation import ObservationError, fingerprint


def apply_cash_corrections(actions: pd.DataFrame, corrections: list[dict]) -> pd.DataFrame:
    """Return a revised snapshot, refusing stale identities, replay and bad evidence.

    Source values remain provenance, while raw_value becomes reviewed cash.
    Downstream price panels must be rebuilt and rebound to this new snapshot.
    """
    if not actions.index.is_unique:
        raise ObservationError("Unique source row index required")
    if actions.event_id.duplicated().any():
        raise ObservationError("Duplicate source event identity")
    if actions.duplicated(["symbol", "session_ms", "kind"]).any():
        raise ObservationError("Duplicate source action key")
    ids = [c["original_event_id"] for c in corrections]
    if len(set(ids)) != len(ids):
        raise ObservationError("Duplicate correction")
    result = actions.copy(deep=True)
    for c in corrections:
        found = result.index[result.event_id == c["original_event_id"]]
        if len(found) != 1:
            raise ObservationError("Correction source identity absent or already revised")
        index = found[0]
        old = result.loc[index]
        if old.kind != "dividend" or old.symbol != c["symbol"] or old.session_ms != c["session_ms"]:
            raise ObservationError("Correction action key mismatch")
        if Decimal(str(old.raw_value)) != Decimal(str(c["previous_raw_cash"])):
            raise ObservationError("Correction amount is stale")
        value = float(c["reviewed_raw_cash"])
        if not math.isfinite(value) or value <= 0:
            raise ObservationError("Positive finite reviewed cash required")
        observed = c["observed_ms"]
        if type(observed) is not int or observed < int(old.observed_ms):
            raise ObservationError("Revision observation cannot predate source capture")
        hashes = c["evidence_sha256"]
        if (
            len(hashes) < 2
            or len(set(hashes)) != len(hashes)
            or any(len(h) != 64 or any(ch not in "0123456789abcdef" for ch in h) for h in hashes)
        ):
            raise ObservationError("Distinct issuer and corroborating evidence hashes required")
        revision_id = fingerprint(c)
        result.loc[index, "raw_value"] = value
        result.loc[index, "observed_ms"] = observed
        result.loc[index, "normalization"] = "reviewed_raw_cash_revision_v1"
        result.loc[index, "event_id"] = revision_id
        result.loc[index, "original_event_id"] = old.event_id
        result.loc[index, "cash_revision_id"] = revision_id
    return result
