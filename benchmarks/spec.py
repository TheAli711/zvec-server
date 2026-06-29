"""Shared, engine-agnostic descriptions of *what* to benchmark.

A :class:`CollectionSpec` says how the collection under test is shaped (dim,
dtype, index, metric, build params). Every runner translates it into whatever
its tier needs — native ``zvec`` objects (engine), our Pydantic models
(in-proc), or JSON (http) — so the three tiers stay perfectly comparable.

These dataclasses deliberately mirror the server's
``models.collections.VectorFieldSpec`` vocabulary (``dtype`` strings like
``VECTOR_FP32``, ``index`` in ``hnsw|flat|ivf``, ``metric`` in ``cosine|ip|l2``)
without importing it, so the benchmark code does not depend on the server's
request models.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["CollectionSpec", "ScalarFieldSpec"]


@dataclass(frozen=True)
class ScalarFieldSpec:
    """A scalar field carried alongside vectors (used by filtered scenarios)."""

    name: str
    dtype: str = "INT64"
    indexed: bool = True
    nullable: bool = False


@dataclass(frozen=True)
class CollectionSpec:
    """How the collection under test is built.

    ``index_params`` assembles the same ``params`` dict the server expects on a
    vector field, so all three tiers feed identical build parameters to Zvec.
    """

    name: str
    dim: int
    dtype: str = "VECTOR_FP32"
    index: str = "hnsw"  # hnsw | flat | ivf
    metric: str = "l2"  # cosine | ip | l2
    # HNSW build params
    m: int | None = None
    ef_construction: int | None = None
    # IVF build params
    n_list: int | None = None
    n_iters: int | None = None
    # Optional scalar fields (only needed for filtered-search scenarios).
    scalar_fields: tuple[ScalarFieldSpec, ...] = field(default_factory=tuple)
    vector_field: str = "embedding"
    # Memory-mapped storage. Benchmarks default to False for clean, trustworthy
    # recall: zvec 0.5.0 has an mmap forward-store bug that can drop a few
    # freshly-optimized results (returning empty ids). The production server
    # defaults to True -- run the CLI with ``--mmap`` to benchmark that config.
    enable_mmap: bool = False

    def index_params(self) -> dict[str, int] | None:
        """Build the engine ``params`` dict for the vector field, or ``None``."""
        params: dict[str, int] = {}
        if self.index == "hnsw":
            if self.m is not None:
                params["m"] = self.m
            if self.ef_construction is not None:
                params["ef_construction"] = self.ef_construction
        elif self.index == "ivf":
            if self.n_list is not None:
                params["n_list"] = self.n_list
            if self.n_iters is not None:
                params["n_iters"] = self.n_iters
        return params or None
