"""The runner contract every tier implements.

Runners are **synchronous**: one call issues one operation and blocks. The
harness (:mod:`benchmarks.harness`) supplies concurrency by calling a runner
from many worker threads at once. This keeps all three tiers comparable under a
single closed-loop concurrency model, and faithfully mirrors the real server,
whose blocking Zvec work also runs in worker threads (``run_in_threadpool``)
serialized by a per-collection reader/writer lock.

Design notes per tier:

* **engine** drives ``zvec`` directly; constructor takes a ``data_dir``.
* **inproc** drives ``adapter.operations`` under a ``ManagedCollection`` RW lock
  (Pydantic models + mappers + lock, but no socket); constructor takes a
  ``data_dir``.
* **http** owns a uvicorn subprocess and a shared ``httpx.Client``; constructor
  takes a ``data_dir`` and a port.

A runner must be safe to call ``search`` on concurrently from many threads
*after* ``setup``/``ingest``/``optimize`` (which the harness calls single-threaded).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

from benchmarks.spec import CollectionSpec

__all__ = ["Runner", "SearchOutcome", "server_query_params"]


@dataclass
class SearchOutcome:
    """Result of a single search call.

    ``ids`` are the returned document ids, best-first (doc ids are the row index
    rendered as a string, so the harness recovers integer ids for recall). The
    byte counts are populated only by the HTTP tier to quantify JSON payload
    overhead.
    """

    ids: list[str]
    request_bytes: int | None = None
    response_bytes: int | None = None


@runtime_checkable
class Runner(Protocol):
    """A tier under test. All methods are synchronous and blocking."""

    name: str

    def setup(self, spec: CollectionSpec) -> None:
        """Create a fresh, empty collection from ``spec`` (dropping any prior one)."""
        ...

    def ingest(
        self,
        ids: list[str],
        vectors: np.ndarray,
        fields: list[dict[str, object]] | None,
    ) -> None:
        """Write one batch of documents (called single-threaded, repeatedly)."""
        ...

    def optimize(self) -> None:
        """Flush + build/optimize the index (called once after ingest)."""
        ...

    def search(
        self,
        vector: np.ndarray,
        topk: int,
        *,
        ef: int | None = None,
        nprobe: int | None = None,
        filter: str | None = None,
        include_vector: bool = False,
        refine: float | None = None,
    ) -> SearchOutcome:
        """Run one nearest-neighbour query and return the hit ids.

        ``refine`` turns on the query-time refiner (re-score quantized candidates
        against the full-precision vectors) with that ``scale_factor``; ``None``
        leaves it off.
        """
        ...

    def teardown(self) -> None:
        """Release resources (close collection, stop subprocess, remove data)."""
        ...

    def target_pid(self) -> int | None:
        """PID whose RSS reflects the engine's memory (subprocess for http)."""
        ...


def server_query_params(
    index: str,
    *,
    ef: int | None,
    nprobe: int | None,
    refine: float | None = None,
) -> dict[str, int | float | bool] | None:
    """Build the server's search ``params`` for ``index``, mirroring the engine tier.

    The server rejects params the field's index doesn't support, so only the
    knobs that apply are sent: ``ef`` for HNSW, ``nprobe`` for IVF, plus
    ``is_using_refiner`` + ``scale_factor`` on either when ``refine`` is set.
    """
    params: dict[str, int | float | bool] = {}
    if index == "hnsw" and ef is not None:
        params["ef"] = ef
    elif index == "ivf" and nprobe is not None:
        params["nprobe"] = nprobe
    if refine is not None and index in ("hnsw", "ivf"):
        params["is_using_refiner"] = True
        params["scale_factor"] = refine
    return params or None
