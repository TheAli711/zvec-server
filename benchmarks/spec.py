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
    # Quantization: "fp16" | "int8" | "int4" (hnsw / flat / ivf),
    # "uniform_uint4" | "uniform_uint7" | "uniform_uint8" (hnsw + l2 only), or
    # "pq" (hnsw / ivf, VECTOR_FP32 only). ``enable_rotate`` is a random rotation
    # before quantizing (learned OPQ for ``pq``).
    quantize_type: str | None = None
    enable_rotate: bool = False
    # PQ-only quantizer params (None = engine default). ``fast_scan`` is IVF +
    # ``num_bits=4`` only; ``opq_iter`` / ``opq_pq_iter`` need ``enable_rotate``.
    num_chunk: int | None = None
    num_bits: int | None = None
    fast_scan: bool = False
    opq_iter: int | None = None
    opq_pq_iter: int | None = None
    # Optional scalar fields (only needed for filtered-search scenarios).
    scalar_fields: tuple[ScalarFieldSpec, ...] = field(default_factory=tuple)
    vector_field: str = "embedding"
    # Memory-mapped storage. Benchmarks default to False (historically because
    # of a zvec 0.5.x mmap bug, fixed in 0.7.0). The production server defaults
    # to True -- run the CLI with ``--mmap`` to benchmark that config.
    enable_mmap: bool = False

    def quantizer_params(self) -> dict[str, int | bool]:
        """The non-default PQ quantizer params, keyed by their server/engine names."""
        params: dict[str, int | bool] = {}
        for key in ("num_chunk", "num_bits", "opq_iter", "opq_pq_iter"):
            value = getattr(self, key)
            if value is not None:
                params[key] = value
        if self.fast_scan:
            params["fast_scan"] = True
        return params

    def index_params(self) -> dict[str, int | str | bool] | None:
        """Build the engine ``params`` dict for the vector field, or ``None``."""
        params: dict[str, int | str | bool] = {}
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
        if self.quantize_type is not None:
            params["quantize_type"] = self.quantize_type
            if self.enable_rotate:
                params["enable_rotate"] = True
            params.update(self.quantizer_params())
        return params or None
