"""In-memory collection registry and lifecycle management.

The :class:`CollectionManager` opens every registered collection once at startup
and keeps the resulting handles in memory for the lifetime of the process. API
requests resolve a collection from the registry in O(1) and never open or close
it themselves.

This module never imports :mod:`zvec`; all engine interaction goes through the
adapter layer. Each collection carries a reader/writer lock so reads (search,
fetch, stats) run concurrently while writes (insert/upsert/update/delete) are
exclusive. Blocking engine work is offloaded to a threadpool inside the lock so
the event loop is never blocked.
"""

from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from readerwriterlock import rwlock
from starlette.concurrency import run_in_threadpool

from zvec_server.adapter import collections as zcol
from zvec_server.adapter import schema_mapper
from zvec_server.db.metadata import SCHEMA_VERSION, CollectionRecord, now_iso
from zvec_server.errors import (
    CollectionAlreadyExistsError,
    CollectionNotFoundError,
    CollectionUnavailableError,
)
from zvec_server.logging import get_logger
from zvec_server.models.collections import (
    CollectionInfo,
    CollectionListResponse,
    CollectionOptions,
    CollectionStats,
    CollectionSummary,
    CreateCollectionRequest,
)

if TYPE_CHECKING:
    from zvec_server.config import Settings
    from zvec_server.db.metadata import MetadataStore

logger = get_logger(__name__)

T = TypeVar("T")


class ManagedCollection:
    """A registered collection plus its concurrency primitives.

    Attributes:
        name: Collection name.
        collection: The opaque open ``zvec.Collection`` handle, or ``None`` when
            the collection is registered but could not be opened on disk.
        record: The persisted metadata record.
        rwlock: Per-collection fair reader/writer lock.
    """

    def __init__(self, name: str, collection: Any, record: CollectionRecord) -> None:
        self.name = name
        self.collection = collection
        self.record = record
        self.rwlock = rwlock.RWLockFair()

    @property
    def available(self) -> bool:
        """Whether the collection is open and ready to serve requests."""
        return self.collection is not None

    async def read(self, fn: Callable[[Any], T]) -> T:
        """Run ``fn(collection)`` under a shared read lock in a worker thread.

        The lock is acquired inside the thread so the event loop never blocks.
        """
        collection = self._require_open()

        def _locked() -> T:
            with self.rwlock.gen_rlock():
                return fn(collection)

        return await run_in_threadpool(_locked)

    async def write(self, fn: Callable[[Any], T]) -> T:
        """Run ``fn(collection)`` under an exclusive write lock in a worker thread."""
        collection = self._require_open()

        def _locked() -> T:
            with self.rwlock.gen_wlock():
                return fn(collection)

        return await run_in_threadpool(_locked)

    def _require_open(self) -> Any:
        if self.collection is None:
            raise CollectionUnavailableError(
                f"Collection '{self.name}' is registered but not open.",
                {"name": self.name},
            )
        return self.collection


class CollectionManager:
    """Owns the in-memory registry of open collections and their metadata.

    Args:
        settings: Server settings (data directory, mmap default, ...).
        store: The metadata persistence layer.
    """

    def __init__(self, settings: Settings, store: MetadataStore) -> None:
        self._settings = settings
        self._store = store
        self._registry: dict[str, ManagedCollection] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ startup
    def load_all(self) -> None:
        """Open every registered collection and populate the registry.

        Collections whose on-disk directory is missing (or which fail to open)
        are kept as *unavailable* entries instead of aborting startup, so the
        rest of the server still comes up and ``GET /collections/{name}`` reports
        ``available=false``.
        """
        records = self._store.list()
        with self._lock:
            self._registry.clear()
            for record in records:
                self._registry[record.name] = self._open_record(record)
        loaded, unavailable = self.counts()
        logger.info("Loaded collections", extra={"loaded": loaded, "unavailable": unavailable})

    def _open_record(self, record: CollectionRecord) -> ManagedCollection:
        """Try to open a single collection; return an (un)available managed entry."""
        if not Path(record.path).exists():
            logger.warning(
                "Collection directory missing; marking unavailable",
                extra={"collection": record.name, "path": record.path},
            )
            return ManagedCollection(record.name, None, record)
        try:
            enable_mmap = self._record_mmap(record)
            collection = zcol.open_collection(record.path, enable_mmap)
        except Exception:
            logger.exception(
                "Failed to open collection; marking unavailable",
                extra={"collection": record.name, "path": record.path},
            )
            return ManagedCollection(record.name, None, record)
        logger.info("Opened collection", extra={"collection": record.name})
        return ManagedCollection(record.name, collection, record)

    # ------------------------------------------------------------------- create
    def create(self, req: CreateCollectionRequest) -> CollectionInfo:
        """Create a new collection on disk and register it.

        Rolls back the on-disk collection if persisting the metadata row fails.

        Raises:
            CollectionAlreadyExistsError: If the name is already registered.
            SchemaValidationError: If the requested schema is invalid.
        """
        with self._lock:
            if req.name in self._registry:
                raise CollectionAlreadyExistsError(
                    f"Collection '{req.name}' already exists.", {"name": req.name}
                )

            assert self._settings.collections_dir is not None  # set by Settings validator
            path = self._settings.collections_dir / req.name
            enable_mmap = self._effective_mmap(req.options)
            schema = schema_mapper.build_collection_schema(req.name, req.vectors, req.fields)
            primary_name, primary_dim = schema_mapper.primary_vector_info(req)
            primary = req.vectors[0]

            collection = zcol.create_collection(str(path), schema, enable_mmap)
            try:
                vectors_dicts, fields_dicts = zcol.schema_to_dicts(collection.schema)
                timestamp = now_iso()
                record = CollectionRecord(
                    name=req.name,
                    path=str(path),
                    schema_version=SCHEMA_VERSION,
                    embedding_dimension=primary_dim,
                    embedding_model=req.embedding_model,
                    primary_vector=primary_name,
                    metric=primary.metric,
                    index_type=primary.index,
                    options_json=json.dumps({"enable_mmap": enable_mmap}),
                    schema_json=json.dumps({"vectors": vectors_dicts, "fields": fields_dicts}),
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                self._store.add(record)
            except Exception:
                logger.exception(
                    "Rolling back collection after metadata failure", extra={"collection": req.name}
                )
                try:
                    zcol.destroy_collection(collection)
                except Exception:
                    logger.exception("Rollback destroy failed", extra={"collection": req.name})
                raise

            managed = ManagedCollection(req.name, collection, record)
            self._registry[req.name] = managed
            logger.info("Created collection", extra={"collection": req.name})
            return self._build_info(managed)

    # --------------------------------------------------------------------- drop
    def drop(self, name: str) -> None:
        """Destroy a collection's data on disk and remove it from the registry.

        Raises:
            CollectionNotFoundError: If the collection is not registered.
        """
        with self._lock:
            managed = self._registry.get(name)
            if managed is None:
                raise CollectionNotFoundError(f"Collection '{name}' not found.", {"name": name})
            if managed.available:
                zcol.destroy_collection(managed.collection)
            else:
                directory = Path(managed.record.path)
                if directory.exists():
                    shutil.rmtree(directory, ignore_errors=True)
            self._store.delete(name)
            del self._registry[name]
            logger.info("Dropped collection", extra={"collection": name})

    # ---------------------------------------------------------------- accessors
    def get(self, name: str) -> ManagedCollection:
        """Return the managed collection, raising if absent or unavailable.

        Raises:
            CollectionNotFoundError: If the collection is not registered.
            CollectionUnavailableError: If it is registered but not open.
        """
        managed = self._registry.get(name)
        if managed is None:
            raise CollectionNotFoundError(f"Collection '{name}' not found.", {"name": name})
        if not managed.available:
            raise CollectionUnavailableError(
                f"Collection '{name}' is registered but not open.", {"name": name}
            )
        return managed

    def list(self) -> CollectionListResponse:
        """Return a summary of every registered collection."""
        with self._lock:
            managed_list = list(self._registry.values())
        summaries = [
            CollectionSummary(
                name=managed.record.name,
                embedding_dimension=managed.record.embedding_dimension,
                embedding_model=managed.record.embedding_model,
                doc_count=self._safe_doc_count(managed),
                created_at=managed.record.created_at,
            )
            for managed in managed_list
        ]
        return CollectionListResponse(collections=summaries)

    def info(self, name: str) -> CollectionInfo:
        """Return full information for a collection (available or not).

        Raises:
            CollectionNotFoundError: If the collection is not registered.
        """
        managed = self._registry.get(name)
        if managed is None:
            raise CollectionNotFoundError(f"Collection '{name}' not found.", {"name": name})
        return self._build_info(managed)

    def counts(self) -> tuple[int, int]:
        """Return ``(loaded, unavailable)`` collection counts."""
        with self._lock:
            loaded = sum(1 for m in self._registry.values() if m.available)
            unavailable = len(self._registry) - loaded
        return loaded, unavailable

    # ----------------------------------------------------------------- shutdown
    def flush_all(self) -> None:
        """Flush every open collection (best-effort)."""
        with self._lock:
            managed_list = list(self._registry.values())
        for managed in managed_list:
            if not managed.available:
                continue
            try:
                with managed.rwlock.gen_wlock():
                    zcol.flush_collection(managed.collection)
            except Exception:
                logger.exception("Error flushing collection", extra={"collection": managed.name})

    def close(self) -> None:
        """Flush and release all collections (called at shutdown)."""
        self.flush_all()
        with self._lock:
            self._registry.clear()

    # ------------------------------------------------------------------ helpers
    def _effective_mmap(self, options: CollectionOptions | None) -> bool:
        if options is not None and options.enable_mmap is not None:
            return options.enable_mmap
        return self._settings.enable_mmap

    def _record_mmap(self, record: CollectionRecord) -> bool:
        try:
            opts = json.loads(record.options_json) if record.options_json else {}
        except json.JSONDecodeError:
            opts = {}
        value = opts.get("enable_mmap")
        return bool(value) if value is not None else self._settings.enable_mmap

    def _safe_doc_count(self, managed: ManagedCollection) -> int | None:
        if not managed.available:
            return None
        try:
            with managed.rwlock.gen_rlock():
                return zcol.get_stats(managed.collection).doc_count
        except Exception:
            logger.exception("Failed to read doc_count", extra={"collection": managed.name})
            return None

    def _build_info(self, managed: ManagedCollection) -> CollectionInfo:
        record = managed.record
        try:
            schema_data = json.loads(record.schema_json) if record.schema_json else {}
        except json.JSONDecodeError:
            schema_data = {}
        try:
            options = json.loads(record.options_json) if record.options_json else {}
        except json.JSONDecodeError:
            options = {}

        stats: CollectionStats | None = None
        if managed.available:
            with managed.rwlock.gen_rlock():
                stats = zcol.get_stats(managed.collection)

        return CollectionInfo(
            name=record.name,
            path=record.path,
            schema_version=record.schema_version,
            embedding_dimension=record.embedding_dimension,
            embedding_model=record.embedding_model,
            vectors=schema_data.get("vectors", []),
            fields=schema_data.get("fields", []),
            options=options,
            stats=stats,
            available=managed.available,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
