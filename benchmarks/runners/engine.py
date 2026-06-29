"""Tier 1 — the raw ``zvec`` engine driven directly, in-process.

This is the performance *floor*: it builds the collection with native ``zvec``
objects and issues ``insert``/``query``/``optimize`` straight against the engine,
bypassing the server entirely (no Pydantic models, no ``ManagedCollection`` lock,
no adapter/operations layer, no socket). Every gap a higher tier shows over this
one is therefore attributable to that tier's added machinery.

Concurrency is supplied by the harness's worker threads calling :meth:`search`;
the engine's own query threadpool is sized via ``query_threads`` at init.
"""

from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path

import numpy as np
import zvec

from benchmarks.runners.base import SearchOutcome
from benchmarks.spec import CollectionSpec
from zvec_server.adapter.runtime import init_zvec

__all__ = ["EngineRunner"]


class EngineRunner:
    """Runner for the raw-engine tier (native ``zvec``, no server logic)."""

    name = "engine"

    def __init__(self, data_dir: Path, *, query_threads: int | None = None) -> None:
        self._data_dir = Path(data_dir)
        self._query_threads = query_threads
        self._collection: zvec.Collection | None = None
        self._spec: CollectionSpec | None = None

    # ----------------------------------------------------------------- lifecycle
    def setup(self, spec: CollectionSpec) -> None:
        """Create a fresh native collection from ``spec`` (dropping any prior one)."""
        init_zvec(log_level="WARNING", query_threads=self._query_threads)
        if self._data_dir.exists():
            shutil.rmtree(self._data_dir, ignore_errors=True)
        self._data_dir.mkdir(parents=True, exist_ok=True)

        schema = self._build_schema(spec)
        option = zvec.CollectionOption(enable_mmap=spec.enable_mmap, read_only=False)
        path = self._data_dir / spec.name
        self._collection = zvec.create_and_open(str(path), schema, option)
        self._spec = spec

    def teardown(self) -> None:
        """Destroy the collection (best-effort) and remove its data directory."""
        if self._collection is not None:
            with contextlib.suppress(Exception):
                self._collection.destroy()
        shutil.rmtree(self._data_dir, ignore_errors=True)
        self._collection = self._spec = None

    def target_pid(self) -> int | None:
        """Same interpreter as the harness; RSS is process-wide (documented caveat)."""
        return os.getpid()

    # -------------------------------------------------------------------- writes
    def ingest(
        self,
        ids: list[str],
        vectors: np.ndarray,
        fields: list[dict[str, object]] | None,
    ) -> None:
        """Insert one batch of documents straight into the engine."""
        assert self._collection is not None and self._spec is not None
        field = self._spec.vector_field
        docs = [
            zvec.Doc(
                id=ids[i],
                vectors={field: vectors[i].tolist()},
                fields=(fields[i] if fields is not None else {}),
            )
            for i in range(len(ids))
        ]
        self._collection.insert(docs)

    def optimize(self) -> None:
        """Flush pending writes and build/optimize the index."""
        assert self._collection is not None
        self._collection.flush()
        self._collection.optimize(zvec.OptimizeOption())

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
        """Run one nearest-neighbour query against the engine and return hit ids."""
        assert self._collection is not None and self._spec is not None
        param = self._build_query_param(ef=ef, nprobe=nprobe)
        query = zvec.Query(
            field_name=self._spec.vector_field,
            vector=vector.tolist(),
            param=param,
        )
        hits = self._collection.query(
            queries=[query],
            topk=topk,
            filter=filter,
            include_vector=include_vector,
        )
        return SearchOutcome(ids=[hit.id for hit in hits])

    # ------------------------------------------------------------------- helpers
    def _build_schema(self, spec: CollectionSpec) -> zvec.CollectionSchema:
        """Translate ``spec`` into a native ``zvec.CollectionSchema``."""
        metric = zvec.MetricType.__members__[spec.metric.upper()]
        dtype = zvec.DataType.__members__[spec.dtype.upper()]
        index_param = self._build_index_param(spec, metric)
        vector_schema = zvec.VectorSchema(
            name=spec.vector_field,
            data_type=dtype,
            dimension=spec.dim,
            index_param=index_param,
        )
        fields = [
            zvec.FieldSchema(
                name=f.name,
                data_type=zvec.DataType.__members__[f.dtype.upper()],
                nullable=f.nullable,
                index_param=zvec.InvertIndexParam() if f.indexed else None,
            )
            for f in spec.scalar_fields
        ]
        return zvec.CollectionSchema(name=spec.name, fields=fields, vectors=[vector_schema])

    def _build_index_param(self, spec: CollectionSpec, metric: zvec.MetricType) -> object:
        """Build the native vector index param for ``spec.index``."""
        if spec.index == "hnsw":
            kwargs: dict[str, int] = {}
            if spec.m is not None:
                kwargs["m"] = spec.m
            if spec.ef_construction is not None:
                kwargs["ef_construction"] = spec.ef_construction
            return zvec.HnswIndexParam(metric_type=metric, **kwargs)
        if spec.index == "ivf":
            kwargs = {}
            if spec.n_list is not None:
                kwargs["n_list"] = spec.n_list
            if spec.n_iters is not None:
                kwargs["n_iters"] = spec.n_iters
            return zvec.IVFIndexParam(metric_type=metric, **kwargs)
        return zvec.FlatIndexParam(metric_type=metric)

    def _build_query_param(self, *, ef: int | None, nprobe: int | None) -> object | None:
        """Build the per-query search param matching the collection's index, or ``None``."""
        assert self._spec is not None
        if self._spec.index == "hnsw" and ef is not None:
            return zvec.HnswQueryParam(ef=ef)
        if self._spec.index == "ivf" and nprobe is not None:
            return zvec.IVFQueryParam(nprobe=nprobe)
        return None
