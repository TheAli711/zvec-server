"""Unit tests for :class:`CollectionManager` against the real Zvec engine."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from zvec_server.adapter.runtime import init_zvec
from zvec_server.config import Settings
from zvec_server.db.metadata import MetadataStore
from zvec_server.errors import (
    CollectionAlreadyExistsError,
    CollectionNotFoundError,
    CollectionUnavailableError,
)
from zvec_server.manager import CollectionManager, ManagedCollection
from zvec_server.models.collections import CreateCollectionRequest, VectorFieldSpec


@pytest.fixture(autouse=True)
def _engine() -> None:
    init_zvec(log_level="ERROR")


@pytest.fixture
def manager(tmp_path: Path) -> Iterator[CollectionManager]:
    settings = Settings(data_dir=tmp_path / "data")
    settings.ensure_directories()
    assert settings.metadata_db_path is not None
    store = MetadataStore(settings.metadata_db_path)
    store.connect()
    mgr = CollectionManager(settings, store)
    try:
        yield mgr
    finally:
        mgr.close()
        store.close()


def _request(name: str = "docs", dim: int = 4) -> CreateCollectionRequest:
    return CreateCollectionRequest(
        name=name,
        vectors=[VectorFieldSpec(name="embedding", dim=dim, metric="cosine", index="flat")],
    )


def test_create_get_info(manager: CollectionManager) -> None:
    info = manager.create(_request())
    assert info.name == "docs"
    assert info.embedding_dimension == 4
    assert info.available is True
    assert info.stats is not None and info.stats.doc_count == 0
    assert len(info.vectors) == 1

    managed = manager.get("docs")
    assert managed.available is True
    assert managed.name == "docs"


def test_create_duplicate_raises(manager: CollectionManager) -> None:
    manager.create(_request())
    with pytest.raises(CollectionAlreadyExistsError):
        manager.create(_request())


def test_get_missing_raises(manager: CollectionManager) -> None:
    with pytest.raises(CollectionNotFoundError):
        manager.get("nope")


def test_list_and_counts(manager: CollectionManager) -> None:
    manager.create(_request("one"))
    manager.create(_request("two"))
    listing = manager.list()
    names = {c.name for c in listing.collections}
    assert names == {"one", "two"}
    assert manager.counts() == (2, 0)


def test_drop(manager: CollectionManager) -> None:
    info = manager.create(_request())
    assert Path(info.path).exists()
    manager.drop("docs")
    with pytest.raises(CollectionNotFoundError):
        manager.get("docs")
    assert not Path(info.path).exists()


def test_drop_missing_raises(manager: CollectionManager) -> None:
    with pytest.raises(CollectionNotFoundError):
        manager.drop("nope")


def test_load_all_reopens(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    settings.ensure_directories()
    assert settings.metadata_db_path is not None

    store1 = MetadataStore(settings.metadata_db_path)
    store1.connect()
    manager1 = CollectionManager(settings, store1)
    manager1.create(_request())
    manager1.close()
    store1.close()

    store2 = MetadataStore(settings.metadata_db_path)
    store2.connect()
    manager2 = CollectionManager(settings, store2)
    manager2.load_all()
    managed = manager2.get("docs")
    assert managed.available is True
    assert manager2.counts() == (1, 0)
    manager2.close()
    store2.close()


def test_load_all_marks_missing_unavailable(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    settings.ensure_directories()
    assert settings.metadata_db_path is not None

    store1 = MetadataStore(settings.metadata_db_path)
    store1.connect()
    manager1 = CollectionManager(settings, store1)
    info = manager1.create(_request())
    manager1.close()
    store1.close()

    # Simulate the on-disk collection disappearing.
    shutil.rmtree(info.path)

    store2 = MetadataStore(settings.metadata_db_path)
    store2.connect()
    manager2 = CollectionManager(settings, store2)
    manager2.load_all()

    assert manager2.counts() == (0, 1)
    # info() still works and reports unavailable; get() raises.
    assert manager2.info("docs").available is False
    with pytest.raises(CollectionUnavailableError):
        manager2.get("docs")
    manager2.close()
    store2.close()


def test_start_recovery_reopens_when_directory_reappears(tmp_path: Path) -> None:
    """A collection that failed to open at startup self-heals in the
    background once its directory becomes available again, with no request
    needed to trigger the retry."""
    settings = Settings(
        data_dir=tmp_path / "data",
        collection_recovery_initial_delay_seconds=0.01,
        collection_recovery_max_delay_seconds=0.05,
    )
    settings.ensure_directories()
    assert settings.metadata_db_path is not None

    store1 = MetadataStore(settings.metadata_db_path)
    store1.connect()
    manager1 = CollectionManager(settings, store1)
    info = manager1.create(_request())
    manager1.close()
    store1.close()

    # Simulate a transient outage (e.g. a rolling-restart lock race): the
    # directory is briefly unavailable when this process starts up.
    original = Path(info.path)
    moved_aside = tmp_path / "docs-moved-aside"
    shutil.move(str(original), str(moved_aside))

    store2 = MetadataStore(settings.metadata_db_path)
    store2.connect()
    manager2 = CollectionManager(settings, store2)
    manager2.load_all()
    assert manager2.counts() == (0, 1)

    async def _run() -> None:
        manager2.start_recovery()
        task = manager2._recovery_tasks["docs"]
        # The underlying issue clears shortly after the first retry attempt.
        await asyncio.sleep(0.02)
        shutil.move(str(moved_aside), str(original))
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(_run())

    assert manager2.counts() == (1, 0)
    assert manager2.get("docs").available is True
    manager2.close()
    store2.close()


def test_start_recovery_retries_with_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recovery task keeps retrying a still-broken collection (rather
    than giving up after one attempt) and stops once it succeeds."""
    settings = Settings(
        data_dir=tmp_path / "data",
        collection_recovery_initial_delay_seconds=0.01,
        collection_recovery_max_delay_seconds=0.05,
    )
    settings.ensure_directories()
    assert settings.metadata_db_path is not None

    store1 = MetadataStore(settings.metadata_db_path)
    store1.connect()
    manager1 = CollectionManager(settings, store1)
    info = manager1.create(_request())
    manager1.close()
    store1.close()

    shutil.rmtree(info.path)

    store2 = MetadataStore(settings.metadata_db_path)
    store2.connect()
    manager2 = CollectionManager(settings, store2)
    manager2.load_all()

    # Fail the first two open attempts and succeed on the third, so the test
    # doesn't depend on real Zvec/filesystem timing to exercise the backoff.
    calls = 0

    def _flaky_open_record(record):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        collection = object() if calls >= 3 else None
        return ManagedCollection(record.name, collection, record)

    monkeypatch.setattr(manager2, "_open_record", _flaky_open_record)

    async def _run() -> None:
        manager2.start_recovery()
        task = manager2._recovery_tasks["docs"]
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(_run())

    assert calls == 3
    assert manager2.counts() == (1, 0)
    manager2.close()
    store2.close()


def test_close_cancels_pending_recovery_task(tmp_path: Path) -> None:
    """Shutting down while a collection is still mid-recovery cancels the
    background retry loop cleanly instead of leaking a task."""
    settings = Settings(
        data_dir=tmp_path / "data",
        collection_recovery_initial_delay_seconds=10.0,
        collection_recovery_max_delay_seconds=10.0,
    )
    settings.ensure_directories()
    assert settings.metadata_db_path is not None

    store1 = MetadataStore(settings.metadata_db_path)
    store1.connect()
    manager1 = CollectionManager(settings, store1)
    info = manager1.create(_request())
    manager1.close()
    store1.close()

    shutil.rmtree(info.path)

    store2 = MetadataStore(settings.metadata_db_path)
    store2.connect()
    manager2 = CollectionManager(settings, store2)
    manager2.load_all()

    async def _run() -> None:
        manager2.start_recovery()
        task = manager2._recovery_tasks["docs"]
        manager2.close()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_run())
    store2.close()


def test_drop_cancels_pending_recovery_task(tmp_path: Path) -> None:
    """Dropping a collection that's still mid-recovery cancels its background
    retry loop instead of leaking a task that retries forever."""
    settings = Settings(
        data_dir=tmp_path / "data",
        collection_recovery_initial_delay_seconds=10.0,
        collection_recovery_max_delay_seconds=10.0,
    )
    settings.ensure_directories()
    assert settings.metadata_db_path is not None

    store1 = MetadataStore(settings.metadata_db_path)
    store1.connect()
    manager1 = CollectionManager(settings, store1)
    info = manager1.create(_request())
    manager1.close()
    store1.close()

    shutil.rmtree(info.path)

    store2 = MetadataStore(settings.metadata_db_path)
    store2.connect()
    manager2 = CollectionManager(settings, store2)
    manager2.load_all()

    async def _run() -> None:
        manager2.start_recovery()
        task = manager2._recovery_tasks["docs"]
        manager2.drop("docs")
        assert "docs" not in manager2._recovery_tasks
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_run())
    manager2.close()
    store2.close()


def test_close_releases_handles_for_reopen(tmp_path: Path) -> None:
    """close() releases each Zvec handle (and its on-disk lock) immediately,
    even while something still references the managed entry, so another
    manager can open the same collections straight away."""
    settings = Settings(data_dir=tmp_path / "data")
    settings.ensure_directories()
    assert settings.metadata_db_path is not None

    store1 = MetadataStore(settings.metadata_db_path)
    store1.connect()
    manager1 = CollectionManager(settings, store1)
    manager1.create(_request())
    lingering = manager1.get("docs")
    manager1.close()
    store1.close()

    assert lingering.available is False
    with pytest.raises(CollectionUnavailableError):
        asyncio.run(lingering.read(lambda c: c))

    store2 = MetadataStore(settings.metadata_db_path)
    store2.connect()
    manager2 = CollectionManager(settings, store2)
    manager2.load_all()
    assert manager2.counts() == (1, 0)
    manager2.close()
    store2.close()
