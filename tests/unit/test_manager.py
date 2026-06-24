"""Unit tests for :class:`CollectionManager` against the real Zvec engine."""

from __future__ import annotations

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
from zvec_server.manager import CollectionManager
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
