"""Tier 2 — the server's request logic in-process, with no HTTP.

This drives the exact code an API handler runs *after* the socket: build the
Pydantic request model, take the ``ManagedCollection`` reader/writer lock, call
``adapter.operations.*``, return the response model. It deliberately skips only
the network, the ASGI/uvicorn stack, and JSON-over-the-wire — so the gap between
this tier and Tier 1 is the *server logic tax*, and the gap up to Tier 3 is the
*transport tax*.

The lock is taken synchronously here (the harness provides concurrency via
worker threads), which mirrors the server: its async handlers offload the same
locked, blocking work to a threadpool.
"""

from __future__ import annotations

import contextlib
import shutil
from pathlib import Path

import numpy as np

from benchmarks.runners.base import SearchOutcome
from benchmarks.spec import CollectionSpec
from zvec_server.adapter import operations
from zvec_server.adapter.runtime import init_zvec
from zvec_server.config import Settings
from zvec_server.db.metadata import MetadataStore
from zvec_server.manager import CollectionManager, ManagedCollection
from zvec_server.models.collections import (
    CollectionOptions,
    CreateCollectionRequest,
    ScalarFieldSpec,
    VectorFieldSpec,
)
from zvec_server.models.search import QuerySpec, SearchRequest
from zvec_server.models.vectors import DocIn, WriteRequest

__all__ = ["InprocRunner"]


class InprocRunner:
    """Runner for the in-process server-logic tier."""

    name = "inproc"

    def __init__(self, data_dir: Path, *, query_threads: int | None = None) -> None:
        self._data_dir = Path(data_dir)
        self._query_threads = query_threads
        self._settings: Settings | None = None
        self._store: MetadataStore | None = None
        self._manager: CollectionManager | None = None
        self._managed: ManagedCollection | None = None
        self._spec: CollectionSpec | None = None

    # ----------------------------------------------------------------- lifecycle
    def setup(self, spec: CollectionSpec) -> None:
        init_zvec(log_level="WARNING", query_threads=self._query_threads)
        if self._data_dir.exists():
            shutil.rmtree(self._data_dir, ignore_errors=True)
        self._data_dir.mkdir(parents=True, exist_ok=True)

        settings = Settings(data_dir=self._data_dir, log_format="console")
        settings.ensure_directories()
        assert settings.metadata_db_path is not None
        store = MetadataStore(settings.metadata_db_path)
        store.connect()
        manager = CollectionManager(settings, store)

        manager.create(self._build_create_request(spec))
        self._settings, self._store, self._manager = settings, store, manager
        self._managed = manager.get(spec.name)
        self._spec = spec

    def teardown(self) -> None:
        if self._manager is not None and self._spec is not None:
            with contextlib.suppress(Exception):
                self._manager.drop(self._spec.name)
        if self._store is not None:
            self._store.close()
        shutil.rmtree(self._data_dir, ignore_errors=True)
        self._managed = self._manager = self._store = None

    def target_pid(self) -> int | None:
        # Same interpreter as the harness; RSS is process-wide (documented caveat).
        import os

        return os.getpid()

    # -------------------------------------------------------------------- writes
    def ingest(
        self,
        ids: list[str],
        vectors: np.ndarray,
        fields: list[dict[str, object]] | None,
    ) -> None:
        assert self._managed is not None and self._spec is not None
        field = self._spec.vector_field
        docs = [
            DocIn(
                id=ids[i],
                vectors={field: vectors[i].tolist()},
                fields=(fields[i] if fields is not None else {}),
            )
            for i in range(len(ids))
        ]
        req = WriteRequest(docs=docs)
        with self._managed.rwlock.gen_wlock():
            operations.insert(self._managed.collection, req.docs, "insert")

    def optimize(self) -> None:
        assert self._managed is not None
        from zvec_server.adapter import collections as zcol

        with self._managed.rwlock.gen_wlock():
            zcol.flush_collection(self._managed.collection)
            zcol.optimize_collection(self._managed.collection)

    # ------------------------------------------------------------------- queries
    def search(
        self,
        vector: np.ndarray,
        topk: int,
        *,
        ef: int | None = None,
        nprobe: int | None = None,
        filter: str | None = None,
        include_vector: bool = False,
    ) -> SearchOutcome:
        assert self._managed is not None and self._spec is not None
        params: dict[str, int] | None = {"ef": ef} if ef is not None else None
        query = QuerySpec(field=self._spec.vector_field, vector=vector.tolist(), params=params)
        req = SearchRequest(
            queries=[query],
            topk=topk,
            filter=filter,
            include_vector=include_vector,
        )
        with self._managed.rwlock.gen_rlock():
            resp = operations.search(self._managed.collection, req)
        return SearchOutcome(ids=[hit.id for hit in resp.results])

    # ------------------------------------------------------------------- helpers
    def _build_create_request(self, spec: CollectionSpec) -> CreateCollectionRequest:
        return CreateCollectionRequest(
            name=spec.name,
            vectors=[
                VectorFieldSpec(
                    name=spec.vector_field,
                    dim=spec.dim,
                    dtype=spec.dtype,
                    index=spec.index,
                    metric=spec.metric,
                    params=spec.index_params(),
                )
            ],
            fields=[
                ScalarFieldSpec(name=f.name, dtype=f.dtype, indexed=f.indexed, nullable=f.nullable)
                for f in spec.scalar_fields
            ],
            options=CollectionOptions(enable_mmap=spec.enable_mmap),
        )
