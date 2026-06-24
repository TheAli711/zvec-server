"""Unit tests for the SQLite metadata store."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from zvec_server.db.metadata import (
    SCHEMA_VERSION,
    CollectionRecord,
    MetadataStore,
    now_iso,
)
from zvec_server.errors import CollectionAlreadyExistsError

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Iterator


def _make_record(name: str = "docs", **overrides: object) -> CollectionRecord:
    """Build a :class:`CollectionRecord` with sensible defaults for tests."""
    ts = now_iso()
    base: dict[str, object] = {
        "name": name,
        "path": f"/data/collections/{name}",
        "schema_version": 1,
        "embedding_dimension": 768,
        "embedding_model": "text-embedding-3-small",
        "primary_vector": "embedding",
        "metric": "cosine",
        "index_type": "hnsw",
        "options_json": '{"enable_mmap": true}',
        "schema_json": '{"vectors": [], "fields": []}',
        "created_at": ts,
        "updated_at": ts,
    }
    base.update(overrides)
    return CollectionRecord(**base)  # type: ignore[arg-type]


@pytest.fixture
def store(tmp_path: pathlib.Path) -> Iterator[MetadataStore]:
    """Provide a connected metadata store backed by a tmp database file."""
    s = MetadataStore(tmp_path / "metadata.db")
    s.connect()
    yield s
    s.close()


def test_now_iso_is_utc_and_parseable() -> None:
    value = now_iso()
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    offset = parsed.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 0


def test_connect_creates_schema_and_sets_pragmas(tmp_path: pathlib.Path) -> None:
    db_path = tmp_path / "metadata.db"
    store = MetadataStore(db_path)
    store.connect()
    try:
        assert db_path.exists()
        # Inspect via an independent connection to avoid touching internals.
        with sqlite3.connect(str(db_path)) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.lower() == "wal"

            version = conn.execute("PRAGMA user_version").fetchone()[0]
            assert version == SCHEMA_VERSION

            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "collections" in tables

            cols = {row[1] for row in conn.execute("PRAGMA table_info(collections)").fetchall()}
            assert cols == {
                "name",
                "path",
                "schema_version",
                "embedding_dimension",
                "embedding_model",
                "primary_vector",
                "metric",
                "index_type",
                "options_json",
                "schema_json",
                "created_at",
                "updated_at",
            }

            # `name` must be the primary key.
            pk = [
                row[1]
                for row in conn.execute("PRAGMA table_info(collections)").fetchall()
                if row[5]  # pk flag
            ]
            assert pk == ["name"]
    finally:
        store.close()


def test_connect_is_idempotent(store: MetadataStore) -> None:
    # Calling connect again on an already-connected store should be a no-op.
    store.connect()
    assert store.list() == []


def test_add_and_get_round_trip(store: MetadataStore) -> None:
    record = _make_record("alpha")
    store.add(record)

    fetched = store.get("alpha")
    assert fetched == record


def test_get_missing_returns_none(store: MetadataStore) -> None:
    assert store.get("nope") is None


def test_add_nullable_fields(store: MetadataStore) -> None:
    record = _make_record(
        "minimal",
        embedding_dimension=None,
        embedding_model=None,
        primary_vector=None,
        metric=None,
        index_type=None,
    )
    store.add(record)
    fetched = store.get("minimal")
    assert fetched == record
    assert fetched is not None
    assert fetched.embedding_dimension is None
    assert fetched.embedding_model is None


def test_list_returns_all_ordered_by_name(store: MetadataStore) -> None:
    store.add(_make_record("gamma"))
    store.add(_make_record("alpha"))
    store.add(_make_record("beta"))

    names = [r.name for r in store.list()]
    assert names == ["alpha", "beta", "gamma"]


def test_list_empty(store: MetadataStore) -> None:
    assert store.list() == []


def test_duplicate_add_raises(store: MetadataStore) -> None:
    store.add(_make_record("dup"))
    with pytest.raises(CollectionAlreadyExistsError) as exc_info:
        store.add(_make_record("dup"))
    assert "dup" in str(exc_info.value)
    assert exc_info.value.details == {"name": "dup"}
    # The first record must still be intact after the failed insert.
    assert store.get("dup") is not None
    assert len(store.list()) == 1


def test_delete_removes_record(store: MetadataStore) -> None:
    store.add(_make_record("temp"))
    assert store.get("temp") is not None

    store.delete("temp")
    assert store.get("temp") is None
    assert store.list() == []


def test_delete_missing_is_noop(store: MetadataStore) -> None:
    # Should not raise.
    store.delete("ghost")
    assert store.list() == []


def test_touch_updates_updated_at(store: MetadataStore) -> None:
    record = _make_record("touched", updated_at="2020-01-01T00:00:00+00:00")
    store.add(record)

    new_ts = now_iso()
    store.touch("touched", new_ts)

    fetched = store.get("touched")
    assert fetched is not None
    assert fetched.updated_at == new_ts
    # created_at must be untouched.
    assert fetched.created_at == record.created_at


def test_touch_missing_is_noop(store: MetadataStore) -> None:
    # Should not raise and should not create a row.
    store.touch("ghost", now_iso())
    assert store.get("ghost") is None


def test_reopen_preserves_rows(tmp_path: pathlib.Path) -> None:
    db_path = tmp_path / "metadata.db"

    store1 = MetadataStore(db_path)
    store1.connect()
    record = _make_record("persisted")
    store1.add(record)
    store1.close()

    store2 = MetadataStore(db_path)
    store2.connect()
    try:
        fetched = store2.get("persisted")
        assert fetched == record
        # user_version is preserved across reopen.
        assert [r.name for r in store2.list()] == ["persisted"]
    finally:
        store2.close()


def test_use_after_close_raises(tmp_path: pathlib.Path) -> None:
    store = MetadataStore(tmp_path / "metadata.db")
    store.connect()
    store.close()
    with pytest.raises(RuntimeError):
        store.list()


def test_close_is_idempotent(tmp_path: pathlib.Path) -> None:
    store = MetadataStore(tmp_path / "metadata.db")
    store.connect()
    store.close()
    # Second close must not raise.
    store.close()


def test_concurrent_access_smoke(store: MetadataStore) -> None:
    """Many threads add/get/list concurrently without corruption or errors."""
    n_threads = 8
    per_thread = 10
    errors: list[Exception] = []
    barrier = threading.Barrier(n_threads)

    def worker(worker_id: int) -> None:
        try:
            barrier.wait()
            for i in range(per_thread):
                name = f"c-{worker_id}-{i}"
                store.add(_make_record(name))
                assert store.get(name) is not None
                # Concurrent reads of the full list must always succeed.
                store.list()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(store.list()) == n_threads * per_thread
