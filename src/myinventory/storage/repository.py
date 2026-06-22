"""Inventory persistence.

The default implementation writes a single ``inventory.json``. A new scan is
merged into the prior one (by stable ID) so the file is an evolving source of
truth, not a snapshot that loses history.

Alongside the cumulative state, the repository keeps a *snapshot history* — the
raw result of each scan, before merging. That history is what powers change
tracking (M5): diffing consecutive scans, the Markdown changelog and stale-host
detection. Removals only show up here, since the merged state never drops a host.

Two backends implement the same interface: :class:`JsonInventoryRepository`
(files on disk) and :class:`SqliteInventoryRepository` (a single database file).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from ..models import Inventory


class InventoryRepository(ABC):
    @abstractmethod
    def load(self) -> Inventory | None:
        """Return the stored cumulative inventory, or ``None`` if there is none."""

    @abstractmethod
    def save(self, inventory: Inventory) -> None:
        """Persist ``inventory`` as the cumulative state, replacing any prior."""

    # --- snapshot history -------------------------------------------------
    @abstractmethod
    def append_snapshot(self, inventory: Inventory) -> str:
        """Record ``inventory`` as a point-in-time snapshot; return its id."""

    @abstractmethod
    def snapshot_ids(self) -> list[str]:
        """Return snapshot ids, oldest first."""

    @abstractmethod
    def load_snapshot(self, snapshot_id: str) -> Inventory | None:
        """Return the snapshot with ``snapshot_id``, or ``None``."""

    # --- convenience ------------------------------------------------------
    def snapshots(self, limit: int | None = None) -> list[tuple[str, Inventory]]:
        """Return ``(id, inventory)`` pairs, oldest first (optionally the last N)."""
        ids = self.snapshot_ids()
        if limit is not None:
            ids = ids[-limit:]
        out: list[tuple[str, Inventory]] = []
        for sid in ids:
            inv = self.load_snapshot(sid)
            if inv is not None:
                out.append((sid, inv))
        return out

    def save_merged(self, inventory: Inventory, *, keep_history: bool = True) -> Inventory:
        """Snapshot ``inventory``, merge it over stored state, persist, return it.

        The fresh scan is snapshotted *before* the merge so the history records
        exactly what each scan saw (the merged state can never lose a host).
        """
        if keep_history:
            self.append_snapshot(inventory)
        prior = self.load()
        if prior is not None:
            prior.merge(inventory)
            merged = prior
        else:
            merged = inventory
        self.save(merged)
        return merged


def _snapshot_stamp() -> str:
    """A filesystem- and id-safe UTC stamp, e.g. ``20260622T143005Z``."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class JsonInventoryRepository(InventoryRepository):
    """Cumulative state in ``inventory.json``; snapshots under ``history/``."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @property
    def history_dir(self) -> Path:
        return self.path.parent / "history"

    def load(self) -> Inventory | None:
        if not self.path.exists():
            return None
        return Inventory.from_json(self.path.read_text())

    def save(self, inventory: Inventory) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(inventory.to_json())

    def append_snapshot(self, inventory: Inventory) -> str:
        self.history_dir.mkdir(parents=True, exist_ok=True)
        stamp = _snapshot_stamp()
        # Guard against >1 scan in the same second.
        candidate = self.history_dir / f"{stamp}.json"
        suffix = 1
        while candidate.exists():
            suffix += 1
            candidate = self.history_dir / f"{stamp}-{suffix}.json"
        candidate.write_text(inventory.to_json())
        return candidate.stem

    def snapshot_ids(self) -> list[str]:
        if not self.history_dir.exists():
            return []
        return sorted(p.stem for p in self.history_dir.glob("*.json"))

    def load_snapshot(self, snapshot_id: str) -> Inventory | None:
        path = self.history_dir / f"{snapshot_id}.json"
        if not path.exists():
            return None
        return Inventory.from_json(path.read_text())


class SqliteInventoryRepository(InventoryRepository):
    """A single-file SQLite backend behind the same interface.

    One row in ``current`` holds the cumulative inventory; the ``snapshots``
    table holds the raw-scan history. The JSON serialization of the model is
    reused verbatim as the stored payload, so the two backends stay in lockstep.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        import sqlite3

        self.path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(str(self.path))

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS current "
                "(id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS snapshots "
                "(snapshot_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, "
                "payload TEXT NOT NULL)"
            )

    def load(self) -> Inventory | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM current WHERE id = 1").fetchone()
        if row is None:
            return None
        return Inventory.from_json(row[0])

    def save(self, inventory: Inventory) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO current (id, payload) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
                (inventory.to_json(),),
            )

    def append_snapshot(self, inventory: Inventory) -> str:
        stamp = _snapshot_stamp()
        payload = inventory.to_json()
        with self._connect() as conn:
            snapshot_id = stamp
            suffix = 1
            while conn.execute(
                "SELECT 1 FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone():
                suffix += 1
                snapshot_id = f"{stamp}-{suffix}"
            conn.execute(
                "INSERT INTO snapshots (snapshot_id, created_at, payload) "
                "VALUES (?, ?, ?)",
                (snapshot_id, inventory.generated_at, payload),
            )
        return snapshot_id

    def snapshot_ids(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT snapshot_id FROM snapshots ORDER BY snapshot_id"
            ).fetchall()
        return [r[0] for r in rows]

    def load_snapshot(self, snapshot_id: str) -> Inventory | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone()
        if row is None:
            return None
        return Inventory.from_json(row[0])


def make_repository(
    backend: str, out_dir: str | Path
) -> InventoryRepository:
    """Construct the configured repository rooted at ``out_dir``.

    * ``json``   -> ``<out_dir>/inventory.json`` (+ ``history/``)
    * ``sqlite`` -> ``<out_dir>/inventory.db``
    """
    out = Path(out_dir)
    if backend == "json":
        return JsonInventoryRepository(out / "inventory.json")
    if backend == "sqlite":
        return SqliteInventoryRepository(out / "inventory.db")
    raise ValueError(f"unknown storage backend {backend!r}; use 'json' or 'sqlite'")
