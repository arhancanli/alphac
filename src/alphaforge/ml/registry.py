"""Versioned model registry — champion/challenger lifecycle (alphaDesign.md §4.5).

The registry is the source of truth for "which meta-model is live". It is a
SQLite ledger (``models/registry.db``) of immutable :class:`ModelCard` rows plus
an artifact directory (``models/artifacts/<model_id>/``) holding the bytes:

::

    artifacts/<model_id>/
        model.joblib          # the frozen ModelProtocol implementation
        card.json             # the ModelCard (human-auditable mirror of the DB row)
        mda_importance.parquet  # optional cluster-permutation MDA report

The DB stores the card (queryable history, the single-champion invariant); the
artifact dir stores the model and its provenance files. Both are append-only in
spirit: a model is never mutated once registered, only its ``status`` transitions
``candidate -> champion -> retired`` via :meth:`ModelRegistry.promote`.

Invariants (tested):

* **Exactly one champion.** :meth:`promote` demotes the current champion to
  ``retired`` and elevates the named model, in a single transaction, so a reader
  never sees zero or two champions.
* **Versioned + reproducible.** ``model_id`` is unique; ``data_sha256`` is a
  content hash of the MATERIALIZED training matrices (CRITIQUE_leakage finding 18:
  there is no parquet to hash in the walk-forward in-memory path, so the hash is
  over the sorted ``(X, y, w, t1)`` content + feature names + window bounds,
  computed identically in the live and WF paths by
  :func:`alphaforge.ml.retrain.dataset_content_sha`).
* **Pure of clock.** Every timestamp on a card is caller-supplied (the
  :mod:`alphaforge.validation.experiments` discipline) — the registry never reads
  the wall clock.

The registry loads a model back through the seam: the artifact's class tag selects
:class:`alphaforge.ml.model.HistGBMMetaModel` or
:class:`alphaforge.ml.model.IdentityMeta`, both satisfying
:class:`alphaforge.ml.model.ModelProtocol`, so callers depend only on the Protocol.

SQLite patterns mirror :class:`alphaforge.live.store.TradingStore` (WAL,
``busy_timeout``, single-transaction writes, ``WITHOUT ROWID`` keyed tables).
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any, Final, Literal, Self

import pandas as pd

from alphaforge.ml.model import HistGBMMetaModel, IdentityMeta

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from alphaforge.core.time import Ms
    from alphaforge.ml.model import ModelProtocol

__all__ = [
    "ModelCard",
    "ModelRegistry",
    "ModelStatus",
]

ModelStatus = Literal["candidate", "champion", "retired"]
"""Lifecycle of a registered model. Exactly one row is ``champion`` at any time."""

_MODEL_FILENAME: Final[str] = "model.joblib"
_CARD_FILENAME: Final[str] = "card.json"
_IMPORTANCE_FILENAME: Final[str] = "mda_importance.parquet"

# Artifact class tags: which ModelProtocol implementation to reconstruct on load.
_CLASS_HISTGBM: Final[str] = "HistGBMMetaModel"
_CLASS_IDENTITY: Final[str] = "IdentityMeta"

_CREATE_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS models (
    model_id      TEXT    PRIMARY KEY,
    trained_at    INTEGER NOT NULL,
    train_start   INTEGER NOT NULL,
    fit_end       INTEGER NOT NULL,
    n_samples     INTEGER NOT NULL,
    feature_names TEXT    NOT NULL,   -- JSON array, pins column order
    params_json   TEXT    NOT NULL,
    val_logloss   REAL,               -- diagnostic; NULL/NaN on a cold-start (no OOS yet)
    val_rank_ic   REAL,               -- diagnostic; NULL/NaN on a cold-start (no OOS yet)
    code_git_sha  TEXT    NOT NULL,
    data_sha256   TEXT    NOT NULL,
    label_is_net  INTEGER NOT NULL,
    status        TEXT    NOT NULL,
    class_tag     TEXT    NOT NULL,
    registered_at INTEGER NOT NULL   -- insert order tiebreak for newest-first history
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_models_status ON models (status);
-- At most one champion: a partial unique index over the single 'champion' value.
CREATE UNIQUE INDEX IF NOT EXISTS ux_models_one_champion
    ON models (status) WHERE status = 'champion';
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelCard:
    """One registered model's immutable identity + provenance (alphaDesign §4.5).

    ``model_id`` e.g. ``'histgbm_meta_2026-06-14_a1b2c3'``; it is stamped on every
    prediction row at serve time (Phase 12) for live-vs-backtest reconciliation.
    ``fit_end`` is the last realized label ``t`` used in the fit (``== windows.
    fit_end``). ``data_sha256`` is the content hash of the MATERIALIZED training
    matrices (finding 18), not of a file. ``val_logloss``/``val_rank_ic`` are on
    the 20d isotonic block and are DIAGNOSTICS only — promotion is judged on the
    out-of-sample window after both models' fit ends (the retrain layer).
    """

    model_id: str
    trained_at: Ms
    train_start: Ms
    fit_end: Ms
    n_samples: int
    feature_names: tuple[str, ...]
    params_json: str
    val_logloss: float
    val_rank_ic: float
    code_git_sha: str
    data_sha256: str
    label_is_net: bool
    status: ModelStatus

    def to_json_obj(self) -> dict[str, object]:
        """JSON-safe dict (sorted keys on dump); the auditable mirror of the DB row."""
        return {
            "model_id": self.model_id,
            "trained_at": int(self.trained_at),
            "train_start": int(self.train_start),
            "fit_end": int(self.fit_end),
            "n_samples": int(self.n_samples),
            "feature_names": list(self.feature_names),
            "params_json": self.params_json,
            "val_logloss": float(self.val_logloss),
            "val_rank_ic": float(self.val_rank_ic),
            "code_git_sha": self.code_git_sha,
            "data_sha256": self.data_sha256,
            "label_is_net": bool(self.label_is_net),
            "status": self.status,
        }

    @classmethod
    def from_json_obj(cls, obj: Mapping[str, Any]) -> ModelCard:
        """Inverse of :meth:`to_json_obj`."""
        return cls(
            model_id=str(obj["model_id"]),
            trained_at=int(obj["trained_at"]),
            train_start=int(obj["train_start"]),
            fit_end=int(obj["fit_end"]),
            n_samples=int(obj["n_samples"]),
            feature_names=tuple(str(c) for c in obj["feature_names"]),
            params_json=str(obj["params_json"]),
            val_logloss=float(obj["val_logloss"]),
            val_rank_ic=float(obj["val_rank_ic"]),
            code_git_sha=str(obj["code_git_sha"]),
            data_sha256=str(obj["data_sha256"]),
            label_is_net=bool(obj["label_is_net"]),
            status=_validate_status(str(obj["status"])),
        )

    def with_status(self, status: ModelStatus) -> ModelCard:
        """A copy with a new ``status`` (cards are immutable; transitions are copies)."""
        from dataclasses import replace

        return replace(self, status=status)


def _class_tag(model: ModelProtocol) -> str:
    """The artifact class tag for ``model`` (selects the loader)."""
    if isinstance(model, HistGBMMetaModel):
        return _CLASS_HISTGBM
    if isinstance(model, IdentityMeta):
        return _CLASS_IDENTITY
    raise TypeError(
        f"registry can persist HistGBMMetaModel/IdentityMeta only; got {type(model).__name__}"
    )


def _load_model(class_tag: str, path: Path) -> ModelProtocol:
    """Reconstruct a model from its artifact by class tag."""
    if class_tag == _CLASS_HISTGBM:
        return HistGBMMetaModel.load(path)
    if class_tag == _CLASS_IDENTITY:
        return IdentityMeta.load(path)
    raise ValueError(f"unknown artifact class tag {class_tag!r}")


def _card_from_row(row: sqlite3.Row) -> ModelCard:
    """SQL row -> :class:`ModelCard`."""
    return ModelCard(
        model_id=str(row["model_id"]),
        trained_at=int(row["trained_at"]),
        train_start=int(row["train_start"]),
        fit_end=int(row["fit_end"]),
        n_samples=int(row["n_samples"]),
        feature_names=tuple(json.loads(row["feature_names"])),
        params_json=str(row["params_json"]),
        val_logloss=_real_or_nan(row["val_logloss"]),
        val_rank_ic=_real_or_nan(row["val_rank_ic"]),
        code_git_sha=str(row["code_git_sha"]),
        data_sha256=str(row["data_sha256"]),
        label_is_net=bool(row["label_is_net"]),
        status=_validate_status(str(row["status"])),
    )


def _validate_status(status: str) -> ModelStatus:
    if status not in ("candidate", "champion", "retired"):
        raise ValueError(f"unknown model status {status!r}")
    return status  # type: ignore[return-value]


def _nan_to_none(value: float) -> float | None:
    """Map a non-finite diagnostic float to SQL NULL (a cold-start card has no OOS)."""
    return None if not math.isfinite(value) else float(value)


def _real_or_nan(value: object) -> float:
    """Map a SQL REAL/NULL back to a float (NULL -> NaN), the inverse of :func:`_nan_to_none`."""
    return math.nan if value is None else float(value)  # type: ignore[arg-type]


class ModelRegistry:
    """SQLite card ledger + artifact directory (module docstring).

    Args:
        db_path: SQLite file for the card ledger (``models/registry.db``). Created
            with parents on construction; WAL mode, ``busy_timeout`` (the
            :class:`alphaforge.live.store.TradingStore` idiom).
        artifact_dir: Root for ``<model_id>/`` artifact directories.

    The class is a context manager; :meth:`close` releases the SQLite connection.
    """

    __slots__ = ("_artifact_dir", "_conn")

    def __init__(self, db_path: Path, artifact_dir: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        self._artifact_dir = artifact_dir
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        with self._conn:
            self._conn.executescript(_CREATE_SQL)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    def artifact_path(self, model_id: str) -> Path:
        """The artifact directory for ``model_id`` (``<artifact_dir>/<model_id>/``)."""
        return self._artifact_dir / model_id

    def register(
        self,
        card: ModelCard,
        model: ModelProtocol,
        importance: pd.DataFrame | None = None,
    ) -> None:
        """Persist a model + its card + optional MDA importance (artifacts then DB).

        Writes ``model.joblib``, ``card.json``, and (if given)
        ``mda_importance.parquet`` under ``artifacts/<model_id>/``, then inserts the
        card row. ``card.feature_names`` MUST equal ``model.feature_names`` (the
        card pins the served column order). Re-registering an existing ``model_id``
        raises (``sqlite3.IntegrityError`` -> ``ValueError``); a candidate
        registered with ``status='champion'`` while a champion exists trips the
        single-champion unique index (use :meth:`promote` to switch champions).
        """
        if tuple(card.feature_names) != tuple(model.feature_names):
            raise ValueError(
                "card.feature_names must match model.feature_names (the card pins "
                f"served column order); card={card.feature_names} model={model.feature_names}"
            )
        tag = _class_tag(model)
        art_dir = self.artifact_path(card.model_id)
        art_dir.mkdir(parents=True, exist_ok=True)
        model.save(art_dir / _MODEL_FILENAME)
        (art_dir / _CARD_FILENAME).write_text(
            json.dumps(card.to_json_obj(), sort_keys=True, indent=2), encoding="utf-8"
        )
        if importance is not None:
            importance.to_parquet(art_dir / _IMPORTANCE_FILENAME)

        registered_at = self._next_registered_at()
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO models (model_id, trained_at, train_start, fit_end, "
                    "n_samples, feature_names, params_json, val_logloss, val_rank_ic, "
                    "code_git_sha, data_sha256, label_is_net, status, class_tag, "
                    "registered_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        card.model_id,
                        int(card.trained_at),
                        int(card.train_start),
                        int(card.fit_end),
                        int(card.n_samples),
                        json.dumps(list(card.feature_names)),
                        card.params_json,
                        _nan_to_none(card.val_logloss),
                        _nan_to_none(card.val_rank_ic),
                        card.code_git_sha,
                        card.data_sha256,
                        int(card.label_is_net),
                        card.status,
                        tag,
                        registered_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"cannot register model {card.model_id!r}: {exc}") from exc

    def _next_registered_at(self) -> int:
        """Monotone insert-order sequence (history ordering, independent of clock)."""
        row = self._conn.execute("SELECT MAX(registered_at) AS m FROM models").fetchone()
        current = row["m"]
        return 0 if current is None else int(current) + 1

    def champion(self) -> ModelCard | None:
        """The current champion's card, or ``None`` if no champion is registered."""
        row = self._conn.execute("SELECT * FROM models WHERE status = 'champion'").fetchone()
        return None if row is None else _card_from_row(row)

    def load_champion(self) -> ModelProtocol | None:
        """The current champion's model (loaded from its artifact), or ``None``."""
        card = self.champion()
        return None if card is None else self.load(card.model_id)

    def load(self, model_id: str) -> ModelProtocol:
        """Load a registered model by id (raises ``KeyError`` if unknown)."""
        row = self._conn.execute(
            "SELECT class_tag FROM models WHERE model_id = ?", (model_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown model_id {model_id!r}")
        return _load_model(str(row["class_tag"]), self.artifact_path(model_id) / _MODEL_FILENAME)

    def get_card(self, model_id: str) -> ModelCard:
        """The card for ``model_id`` (raises ``KeyError`` if unknown)."""
        row = self._conn.execute("SELECT * FROM models WHERE model_id = ?", (model_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown model_id {model_id!r}")
        return _card_from_row(row)

    def load_importance(self, model_id: str) -> pd.DataFrame | None:
        """The MDA importance report for ``model_id``, or ``None`` if none was stored."""
        if model_id not in {c.model_id for c in self.history()}:
            raise KeyError(f"unknown model_id {model_id!r}")
        path = self.artifact_path(model_id) / _IMPORTANCE_FILENAME
        return None if not path.exists() else pd.read_parquet(path)

    def promote(self, model_id: str) -> None:
        """Make ``model_id`` the champion; demote the current champion to ``retired``.

        A single transaction so the single-champion invariant never breaks: the old
        champion (if any, and if not ``model_id`` itself) goes to ``retired``, then
        ``model_id`` goes to ``champion``. Raises ``KeyError`` if ``model_id`` is
        unknown. Promoting the already-current champion is a no-op (it stays
        champion, nothing is retired).
        """
        with self._conn:
            target = self._conn.execute(
                "SELECT status FROM models WHERE model_id = ?", (model_id,)
            ).fetchone()
            if target is None:
                raise KeyError(f"unknown model_id {model_id!r}")
            self._conn.execute(
                "UPDATE models SET status = 'retired' WHERE status = 'champion' AND model_id != ?",
                (model_id,),
            )
            self._conn.execute(
                "UPDATE models SET status = 'champion' WHERE model_id = ?", (model_id,)
            )

    def history(self) -> list[ModelCard]:
        """Every registered card, newest-first (by insert order, clock-independent)."""
        rows = self._conn.execute("SELECT * FROM models ORDER BY registered_at DESC").fetchall()
        return [_card_from_row(row) for row in rows]
