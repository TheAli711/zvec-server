"""SQLite-backed persistence for collection metadata.

This module stores **only** lightweight metadata describing each collection
(name, on-disk path, schema fingerprint, denormalized embedding columns, and
timestamps). Vectors, document text, and embeddings are never persisted here;
they live inside the Zvec engine on disk.

The store uses the standard-library :mod:`sqlite3` driver in WAL mode with
``check_same_thread=False`` and guards every database access with a
:class:`threading.Lock`, because the server services requests from a
thread pool.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import astuple, dataclass, fields
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from zvec_server.errors import CollectionAlreadyExistsError

if TYPE_CHECKING:
    import pathlib

#: Current metadata schema version. ``connect`` migrates databases up to this
#: value, keyed off SQLite's ``PRAGMA user_version``.
SCHEMA_VERSION = 1


def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string.

    Returns:
        A timezone-aware ISO 8601 timestamp, e.g. ``"2026-06-23T12:00:00+00:00"``.
    """
    return datetime.now(UTC).isoformat()


@dataclass
class CollectionRecord:
    """A row in the ``collections`` table describing a single collection.

    Attributes:
        name: Unique collection name (the primary key).
        path: Absolute on-disk path of the Zvec collection.
        schema_version: Schema version recorded for the collection.
        embedding_dimension: Dimension of the primary vector, if known.
        embedding_model: Optional name of the embedding model used.
        primary_vector: Name of the primary vector field, if any.
        metric: Distance metric of the primary vector (e.g. ``"cosine"``).
        index_type: Index type of the primary vector (e.g. ``"hnsw"``).
        options_json: JSON-encoded collection options.
        schema_json: JSON-encoded full schema snapshot.
        created_at: ISO 8601 creation timestamp.
        updated_at: ISO 8601 last-update timestamp.
    """

    name: str
    path: str
    schema_version: int
    embedding_dimension: int | None
    embedding_model: str | None
    primary_vector: str | None
    metric: str | None
    index_type: str | None
    options_json: str
    schema_json: str
    created_at: str
    updated_at: str


#: Ordered tuple of column names, derived once from :class:`CollectionRecord`.
_COLUMNS: tuple[str, ...] = tuple(f.name for f in fields(CollectionRecord))

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS collections (
    name TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    embedding_dimension INTEGER,
    embedding_model TEXT,
    primary_vector TEXT,
    metric TEXT,
    index_type TEXT,
    options_json TEXT NOT NULL,
    schema_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_INSERT_SQL = (
    f"INSERT INTO collections ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' for _ in _COLUMNS)})"
)

_SELECT_COLUMNS = ", ".join(_COLUMNS)


class MetadataStore:
    """Thread-safe SQLite store for collection metadata.

    The store owns a single long-lived connection (the server opens it once at
    startup and closes it at shutdown). All database access is serialized with
    an internal lock so the connection can be shared safely across threads.
    """

    def __init__(self, db_path: pathlib.Path) -> None:
        """Initialize the store.

        Args:
            db_path: Filesystem path of the SQLite database file. The file is
                created on :meth:`connect` if it does not exist; the parent
                directory is expected to exist already.
        """
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        """Open the database connection and ensure the schema is current.

        Opens the connection with ``check_same_thread=False``, enables WAL mode
        and foreign-key enforcement, creates the ``collections`` table if it is
        missing, and runs migrations up to :data:`SCHEMA_VERSION` keyed off
        ``PRAGMA user_version``.

        Idempotent: calling :meth:`connect` on an already-connected store is a
        no-op.
        """
        with self._lock:
            if self._conn is not None:
                return
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(_CREATE_TABLE_SQL)
            self._migrate(conn)
            conn.commit()
            self._conn = conn

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Run schema migrations up to :data:`SCHEMA_VERSION`.

        Migrations are applied incrementally based on the database's current
        ``PRAGMA user_version``. Version 1 establishes the baseline schema
        (the table is created in :meth:`connect`).

        Args:
            conn: An open connection to migrate.
        """
        current = int(conn.execute("PRAGMA user_version").fetchone()[0])
        # Version 1: baseline schema. Nothing extra to do beyond table creation.
        if current < 1:
            current = 1
        # Future migrations: bump `current` and apply DDL here, one step at a time.
        conn.execute(f"PRAGMA user_version={current}")

    def close(self) -> None:
        """Close the database connection.

        Idempotent: closing an already-closed store is a no-op.
        """
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _require_conn(self) -> sqlite3.Connection:
        """Return the active connection or raise if the store is closed.

        Returns:
            The open SQLite connection.

        Raises:
            RuntimeError: If :meth:`connect` has not been called (or the store
                has been closed).
        """
        if self._conn is None:
            raise RuntimeError("MetadataStore is not connected; call connect() first.")
        return self._conn

    def add(self, record: CollectionRecord) -> None:
        """Insert a new collection record.

        Args:
            record: The record to persist.

        Raises:
            CollectionAlreadyExistsError: If a collection with the same name
                already exists (a UNIQUE/primary-key violation).
        """
        with self._lock:
            conn = self._require_conn()
            try:
                conn.execute(_INSERT_SQL, astuple(record))
                conn.commit()
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise CollectionAlreadyExistsError(
                    f"Collection '{record.name}' already exists.",
                    {"name": record.name},
                ) from exc

    def get(self, name: str) -> CollectionRecord | None:
        """Fetch a single collection record by name.

        Args:
            name: The collection name to look up.

        Returns:
            The matching :class:`CollectionRecord`, or ``None`` if no row exists.
        """
        with self._lock:
            conn = self._require_conn()
            row = conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM collections WHERE name = ?",
                (name,),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def list(self) -> list[CollectionRecord]:
        """Return all collection records, ordered by name.

        Returns:
            A list of :class:`CollectionRecord` instances (possibly empty).
        """
        with self._lock:
            conn = self._require_conn()
            rows = conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM collections ORDER BY name"
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def delete(self, name: str) -> None:
        """Delete a collection record by name.

        Deleting a non-existent collection is a silent no-op.

        Args:
            name: The collection name to remove.
        """
        with self._lock:
            conn = self._require_conn()
            conn.execute("DELETE FROM collections WHERE name = ?", (name,))
            conn.commit()

    def touch(self, name: str, updated_at: str) -> None:
        """Update the ``updated_at`` timestamp of a collection.

        Updating a non-existent collection is a silent no-op.

        Args:
            name: The collection name to update.
            updated_at: The new ISO 8601 timestamp.
        """
        with self._lock:
            conn = self._require_conn()
            conn.execute(
                "UPDATE collections SET updated_at = ? WHERE name = ?",
                (updated_at, name),
            )
            conn.commit()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> CollectionRecord:
        """Convert a database row into a :class:`CollectionRecord`.

        Args:
            row: A :class:`sqlite3.Row` selected with the canonical column order.

        Returns:
            The reconstructed record.
        """
        return CollectionRecord(*(row[col] for col in _COLUMNS))
