"""Experiment tracking for the Deflated Sharpe Ratio's trial count (alphaDesign.md section 7.4).

The Deflated Sharpe Ratio inflates the benchmark Sharpe ``SR*`` by the expected
maximum Sharpe across ``N`` independent trials (alphaDesign.md section 7.4)::

    SR* = sqrt(V[SR]) * ( (1 - gamma) * Phi^-1(1 - 1/N) + gamma * Phi^-1(1 - 1/(N*e)) )

``N`` must be *measured*, not guessed: it is the number of strategy
configurations actually tried, and ``V[SR]`` is the sample variance of their
per-period Sharpe estimates. The design (section 7.4) mandates this be logged
automatically -- "every CPCV run appends its config hash to ``experiments.log``,
so N is measured, not guessed". This module is that log.

:class:`ExperimentLog` is an append-only JSONL ledger. Every walk-forward (or
CPCV) configuration that is ever evaluated records one line: a deterministic
hash of the *config that defines the trial* (alphas / rebalance / band /
allocator / window), the wall-clock timestamp **passed in by the caller** (the
clock is never read here -- determinism, leakageCritique discipline), and the
realized per-period and annualized Sharpe plus the daily-return moments.

The hash makes the log **idempotent**: re-evaluating an identical configuration
(a re-run, a retry, the same grid swept twice) does not double-count ``N`` -- a
config that is already on the ledger is skipped. This is the whole point: an
honest ``N`` counts *distinct* trials, so re-running a backtest 100 times cannot
silently inflate the deflation and make a weak edge look unbeatable.

JSON record schema (one object per line, sorted keys, ASCII)::

    config_hash         str    16-hex-char truncated SHA-256 of the canonical config
    config              obj    the canonical config that was hashed (audit trail)
    now_ms              int    caller-supplied wall-clock epoch ms (never read here)
    sharpe_ann          float  annualized Sharpe (human-facing diagnostic)
    sharpe_per_period   float  per-period Sharpe -- THE quantity DSR variance uses
    n_obs               int    number of (daily) return observations behind the Sharpe
    skew                float  sample skewness of the daily returns (gamma_3, DSR moment)
    kurtosis            float  sample kurtosis of the daily returns (gamma_4, non-excess)

Determinism: pure functions of inputs + the JSONL file; no clock, no RNG. The
file is created (with parents) on first :meth:`record`; reads of a missing file
return an empty log.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

    from alphaforge.core.time import Ms

__all__ = [
    "DEFAULT_LOG_PATH",
    "DEFAULT_SR_TRIALS_VARIANCE",
    "ExperimentLog",
    "ExperimentRecord",
    "config_hash",
]

DEFAULT_LOG_PATH: Final[Path] = Path("var/experiments.jsonl")
"""Default ledger location (``settings.paths.var_dir / "experiments.jsonl"`` in wiring)."""

DEFAULT_SR_TRIALS_VARIANCE: Final[float] = 1.0
"""Fallback ``V[SR]`` when fewer than 2 distinct trials exist.

With < 2 trials the sample variance of per-period Sharpes is undefined, but the
DSR benchmark ``SR*`` still needs a cross-trial SR variance. We default to 1.0:
the de Prado convention treating per-period Sharpe estimates as drawn from a
unit-variance population when no empirical spread is available yet. This is a
*conservative documented placeholder*, not a measurement -- a one-trial DSR is
necessarily provisional and the verdict surfaces ``n_trials`` so a reader knows
the deflation is not yet data-driven.
"""

_HASH_LEN: Final[int] = 16


def config_hash(config: Mapping[str, Any]) -> str:
    """Deterministic ``_HASH_LEN``-hex-char SHA-256 of a canonicalized config.

    The config is canonicalized with ``json.dumps(sort_keys=True,
    separators=(",", ":"))`` so key order, whitespace, and equivalent
    numeric/string spellings that round-trip through JSON do not change the
    hash. Two configs hash equal iff their canonical JSON is byte-identical;
    this is the identity used for idempotency in :meth:`ExperimentLog.record`.

    Raises ``TypeError`` if ``config`` is not JSON-serializable (a non-trivial
    object in the config is a caller bug -- trials must be described by plain
    data so the ledger is portable and reproducible).
    """
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode("ascii")).hexdigest()
    return digest[:_HASH_LEN]


@dataclass(frozen=True, slots=True, kw_only=True)
class ExperimentRecord:
    """One logged trial -- a single walk-forward/CPCV configuration's outcome.

    ``sharpe_per_period`` is THE field the DSR variance consumes; ``sharpe_ann``
    is the human-facing annualized figure. All Sharpe/moment fields may be
    non-finite (e.g. a degenerate single-observation leg) and round-trip through
    JSON as ``null`` <-> ``nan`` so the ledger never silently drops a trial.
    """

    config_hash: str
    config: dict[str, Any]
    now_ms: Ms
    sharpe_ann: float
    sharpe_per_period: float
    n_obs: int
    skew: float
    kurtosis: float

    def to_json_obj(self) -> dict[str, Any]:
        """JSON-safe dict (non-finite floats -> ``None``); keys sorted on dump."""
        return {
            "config_hash": self.config_hash,
            "config": self.config,
            "now_ms": int(self.now_ms),
            "sharpe_ann": _json_float(self.sharpe_ann),
            "sharpe_per_period": _json_float(self.sharpe_per_period),
            "n_obs": int(self.n_obs),
            "skew": _json_float(self.skew),
            "kurtosis": _json_float(self.kurtosis),
        }

    @classmethod
    def from_json_obj(cls, obj: Mapping[str, Any]) -> ExperimentRecord:
        """Inverse of :meth:`to_json_obj` (``None`` -> ``nan``)."""
        return cls(
            config_hash=str(obj["config_hash"]),
            config=dict(obj["config"]),
            now_ms=int(obj["now_ms"]),
            sharpe_ann=_from_json_float(obj["sharpe_ann"]),
            sharpe_per_period=_from_json_float(obj["sharpe_per_period"]),
            n_obs=int(obj["n_obs"]),
            skew=_from_json_float(obj["skew"]),
            kurtosis=_from_json_float(obj["kurtosis"]),
        )


def _json_float(value: float) -> float | None:
    """Map non-finite floats to ``None`` (JSON has no NaN/Inf in strict mode)."""
    return None if not math.isfinite(value) else float(value)


def _from_json_float(value: Any) -> float:
    """Map JSON ``null`` back to ``nan``; pass finite floats through."""
    return math.nan if value is None else float(value)


class ExperimentLog:
    """Append-only, idempotent JSONL ledger of evaluated trials (module docstring).

    Args:
        path: JSONL ledger file. Defaults to :data:`DEFAULT_LOG_PATH`
            (``var/experiments.jsonl``). Created with parents on first
            :meth:`record`; a missing file reads as an empty log.

    Thread/process-safety is intentionally NOT provided: the research workflow
    is single-writer (one walk-forward at a time appends its trial). The ledger
    is plain JSONL so it can be inspected, diffed, and hand-audited.
    """

    __slots__ = ("_path",)

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else DEFAULT_LOG_PATH

    @property
    def path(self) -> Path:
        """The ledger file this log reads/writes."""
        return self._path

    def all(self) -> list[ExperimentRecord]:
        """Every recorded trial in file (append) order; ``[]`` if the file is absent.

        Blank lines are skipped (tolerant of trailing newlines). A malformed
        line raises ``ValueError`` with the line number -- a corrupt ledger is a
        loud failure, never a silently-truncated ``N``.
        """
        if not self._path.exists():
            return []
        records: list[ExperimentRecord] = []
        text = self._path.read_text(encoding="utf-8")
        for lineno, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                records.append(ExperimentRecord.from_json_obj(obj))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"corrupt experiment ledger {self._path} at line {lineno}: {exc}"
                ) from exc
        return records

    def _hashes(self) -> set[str]:
        """The set of config hashes already on the ledger (idempotency check)."""
        return {rec.config_hash for rec in self.all()}

    def record(
        self,
        config: Mapping[str, Any],
        *,
        sharpe_ann: float,
        sharpe_per_period: float,
        n_obs: int,
        skew: float,
        kurtosis: float,
        now_ms: Ms,
    ) -> ExperimentRecord:
        """Append one trial; idempotent on the config hash.

        Hashes ``config`` (see :func:`config_hash`). If that hash is already on
        the ledger the call is a no-op for the file -- the *existing* record is
        returned unchanged, so re-running an identical configuration never
        inflates ``N`` (module docstring). Otherwise a new line is appended and
        the freshly-built record returned.

        ``now_ms`` is the caller's wall-clock timestamp; the clock is never read
        here (determinism). All float arguments may be non-finite.
        """
        h = config_hash(config)
        for existing in self.all():
            if existing.config_hash == h:
                return existing
        record = ExperimentRecord(
            config_hash=h,
            config=dict(config),
            now_ms=int(now_ms),
            sharpe_ann=float(sharpe_ann),
            sharpe_per_period=float(sharpe_per_period),
            n_obs=int(n_obs),
            skew=float(skew),
            kurtosis=float(kurtosis),
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.to_json_obj(), sort_keys=True, ensure_ascii=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return record

    def n_trials(self) -> int:
        """Number of DISTINCT configurations on the ledger -- the DSR ``N``.

        Distinct by construction (idempotent :meth:`record`), but counted from
        the deduplicated hash set so a hand-edited ledger with duplicate hashes
        still yields an honest count.
        """
        return len(self._hashes())

    def trial_sharpe_variance(self) -> float:
        """Sample variance (ddof=1) of recorded per-period Sharpes -- DSR ``V[SR]``.

        Uses only **finite** per-period Sharpes (a degenerate trial logged with
        a ``nan`` Sharpe cannot define a spread). With fewer than 2 finite
        values the sample variance is undefined and this returns
        :data:`DEFAULT_SR_TRIALS_VARIANCE` (a documented conservative
        placeholder, see its docstring). The variance is over *per-period*
        Sharpes because DSR's ``SR*`` and ``SR`` are both per-period (section 7.4).
        """
        sharpes = [
            rec.sharpe_per_period for rec in self.all() if math.isfinite(rec.sharpe_per_period)
        ]
        n = len(sharpes)
        if n < 2:
            return DEFAULT_SR_TRIALS_VARIANCE
        mean = math.fsum(sharpes) / n
        ss = math.fsum((x - mean) ** 2 for x in sharpes)
        return ss / (n - 1)
