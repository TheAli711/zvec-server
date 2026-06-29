"""A VectorDBBench client plugin that drives Zvec Server over its REST API.

This is "Track B" of the benchmark suite: rather than calling the engine in
process (Track A, ``python -m benchmarks run``), it points the community-standard
`VectorDBBench <https://github.com/zilliztech/VectorDBBench>`_ harness at a
running ``zvec-server`` so the resulting QPS / recall / build-time numbers are
directly comparable to the figures published on zvec.org.

What this measures
------------------
This plugin exercises *only the served (network) path*: every operation crosses
loopback TCP, FastAPI/Pydantic, the adapter, and JSON (de)serialization of the
float vectors. For the in-process-vs-network decomposition, use Track A.

The VectorDBBench client interface
----------------------------------
Custom clients subclass ``vectordb_bench.backend.clients.api.VectorDB`` and pair
with a ``DBConfig`` (connection settings) and a ``DBCaseConfig`` (per-case index
and search params). The interface has drifted across releases, so this module is
written to tolerate both the stable line and ``main``:

* stable ``v0.0.20`` (``pip install vectordb-bench``)::

      def __init__(self, dim, db_config, db_case_config,
                   collection_name, drop_old=False, **kwargs) -> None
      @contextmanager
      def init(self) -> None
      def insert_embeddings(self, embeddings, metadata, **kwargs) -> (int, Exception)
      def search_embedding(self, query, k=100, filters: dict | None = None) -> list[int]
      def optimize(self) -> None
      def need_normalize_cosine(self) -> bool

  Source:
  https://github.com/zilliztech/VectorDBBench/blob/v0.0.20/vectordb_bench/backend/clients/api.py

* ``main`` evolved ``insert_embeddings`` (adds ``labels_data`` /
  ``tenant_labels_data``), replaced ``search_embedding``'s ``filters`` with a
  ``payload_profile`` argument, and gave ``optimize`` a ``data_size`` parameter.
  Source:
  https://github.com/zilliztech/VectorDBBench/blob/main/vectordb_bench/backend/clients/api.py

We absorb the version-specific extras with ``**kwargs`` and accept either a
``filters`` dict or a ``payload_profile`` keyword, so the same file works on
both. ``filters`` (when present) is the canonical VectorDBBench filtered-search
dict ``{"id": <int>}`` meaning ``id >= <int>`` -- the same convention the
built-in pgvector client uses
(https://github.com/zilliztech/VectorDBBench/blob/v0.0.20/vectordb_bench/backend/clients/pgvector/pgvector.py).

Registration
------------
VectorDBBench has no plugin-discovery hook; built-in clients are wired through
the ``DB`` enum in ``vectordb_bench/backend/clients/__init__.py`` (three
properties: ``init_cls``, ``config_cls``, ``case_config_cls``). To avoid forking
the package, register at runtime by handing :class:`ZvecRest`,
:class:`ZvecRestConfig` and :class:`ZvecRestHNSWConfig` straight to a
``TaskConfig`` (the ``db`` enum value is only used to look those classes back up,
so any registered member works) -- see this directory's ``README.md`` for a
copy-paste snippet.

int8 / quantization caveat
--------------------------
zvec.org's Cohere runs use int8 quantization. The server's REST collection
schema does **not** expose a quantize/SQ parameter today, so Track B runs
``VECTOR_FP32`` over REST. Recall will match fp32; absolute QPS/memory will
differ from an int8 run until the server adds a quantization param to the
create-collection body.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import httpx

# --- Guarded optional import -------------------------------------------------
# ``vectordb_bench`` is a heavy, manual dependency and is NOT installed in this
# project's environment. We must stay importable without it (so the module lints
# and so ``benchmarks`` can be imported), yet still subclass the real ABC when it
# *is* present. We therefore bind the base classes to the real ones if available
# and fall back to ``object`` otherwise, raising a clear error only when someone
# actually tries to construct the client.
if TYPE_CHECKING:  # pragma: no cover - type-checker view only
    from vectordb_bench.backend.clients.api import (  # type: ignore[import-not-found]
        DBCaseConfig,
        DBConfig,
        VectorDB,
    )

    _BENCH_IMPORT_ERROR: ImportError | None = None
else:
    try:
        from vectordb_bench.backend.clients.api import (
            DBCaseConfig,
            DBConfig,
            VectorDB,
        )

        _BENCH_IMPORT_ERROR = None
    except ImportError as exc:  # pragma: no cover - exercised only without the dep
        # Minimal stand-ins so the subclasses below are still definable (and
        # lintable). They cannot be *used*; instantiation re-raises the cause.
        VectorDB = object  # type: ignore[assignment, misc]
        DBConfig = object  # type: ignore[assignment, misc]
        DBCaseConfig = object  # type: ignore[assignment, misc]
        _BENCH_IMPORT_ERROR = exc


__all__ = ["ZvecRest", "ZvecRestConfig", "ZvecRestHNSWConfig"]

# VectorDBBench MetricType string values (uppercase) -> the server's metric token.
# https://github.com/zilliztech/VectorDBBench/blob/v0.0.20/vectordb_bench/backend/clients/api.py
_METRIC_MAP = {
    "L2": "l2",
    "COSINE": "cosine",
    "IP": "ip",
}


def _zvec_metric(raw: object) -> str:
    """Map a VectorDBBench metric (enum or string) to the server's token.

    Accepts ``MetricType.COSINE`` (``str``-valued ``StrEnum``), the bare string
    ``"COSINE"``, or our own lowercase ``"cosine"`` -- and validates it.
    """
    token = str(getattr(raw, "value", raw)).upper()
    try:
        return _METRIC_MAP[token]
    except KeyError:
        supported = ", ".join(sorted(_METRIC_MAP))
        raise ValueError(f"unsupported metric {raw!r}; Zvec REST supports: {supported}") from None


def _require_bench() -> None:
    """Raise a clear error if ``vectordb_bench`` could not be imported."""
    if _BENCH_IMPORT_ERROR is not None:
        raise ImportError(
            "VectorDBBench is required to use the Zvec REST client but is not "
            "installed. Install it (ideally in its own venv) with "
            "'pip install vectordb-bench' -- see benchmarks/vdbbench/README.md."
        ) from _BENCH_IMPORT_ERROR


class ZvecRestConfig(DBConfig):
    """Connection settings: where the running ``zvec-server`` lives.

    A VectorDBBench ``DBConfig`` is a pydantic model whose ``to_dict()`` becomes
    the ``db_config`` dict handed to the client's ``__init__``. We keep it to the
    base URL plus an optional request timeout.
    """

    host: str = "127.0.0.1"
    port: int = 8000
    # Generous default: index optimize() on a large collection can be slow.
    timeout: float = 600.0

    def to_dict(self) -> dict:
        """Serialize to the ``db_config`` dict passed to :class:`ZvecRest`."""
        return {
            "base_url": f"http://{self.host}:{self.port}",
            "timeout": self.timeout,
        }


class ZvecRestHNSWConfig(DBCaseConfig):
    """Per-case HNSW build/search params, driven by the case so sweeps work.

    ``index_param`` feeds the create-collection body (``m`` / ``ef_construction``)
    and ``search_param`` feeds the per-query ``ef``. zvec.org headline settings:
    Cohere 1M ``M=15, ef=180``; Cohere 10M ``M=50, ef=118``.
    """

    # ``metric_type`` is a VectorDBBench MetricType (StrEnum) at runtime; typed
    # loosely so the module imports without the dependency.
    metric_type: Any = None
    M: int = 15
    efConstruction: int = 200
    ef: int | None = 180

    def index_param(self) -> dict:
        """Build params consumed by :meth:`ZvecRest._create_collection`."""
        return {
            "metric": _zvec_metric(self.metric_type),
            "m": self.M,
            "ef_construction": self.efConstruction,
        }

    def search_param(self) -> dict:
        """Search params consumed by :meth:`ZvecRest.search_embedding`."""
        return {"ef": self.ef}


class ZvecRest(VectorDB):
    """VectorDBBench client that talks to Zvec Server's REST API.

    One instance owns the collection lifecycle for a benchmark run. The
    ``init()`` contextmanager opens the shared :class:`httpx.Client`; the harness
    calls ``insert_embeddings`` in batches, then ``optimize`` (flush + build),
    then ``search_embedding`` many times to measure QPS and recall.
    """

    name = "ZvecRest"

    def __init__(
        self,
        dim: int,
        db_config: dict,
        db_case_config: DBCaseConfig | None,
        collection_name: str,
        drop_old: bool = False,
        **kwargs: Any,
    ) -> None:
        _require_bench()
        self.dim = dim
        self.collection_name = collection_name
        self.db_case_config = db_case_config
        self._base_url = db_config["base_url"]
        self._timeout = float(db_config.get("timeout", 600.0))
        self._index_param: dict = db_case_config.index_param() if db_case_config is not None else {}
        self._search_param: dict = (
            db_case_config.search_param() if db_case_config is not None else {}
        )
        # Live only inside init(); the harness may pickle this object to ship it
        # to a worker process, and httpx.Client is not picklable.
        self._client: httpx.Client | None = None

        # Recreate the collection up front so the build is part of the run.
        with httpx.Client(base_url=self._base_url, timeout=self._timeout) as client:
            if drop_old:
                self._drop(client)
            self._create_collection(client)

    @contextmanager
    def init(self) -> Any:
        """Open the shared HTTP client for the duration of a phase.

        ``httpx.Client`` is safe to call concurrently from the harness's worker
        threads, so a single client backs both ingest and the search sweep.
        """
        self._client = httpx.Client(base_url=self._base_url, timeout=self._timeout)
        try:
            yield
        finally:
            self._client.close()
            self._client = None

    def need_normalize_cosine(self) -> bool:
        """Server normalizes for cosine itself, so the harness must not."""
        return False

    # ------------------------------------------------------------------- writes
    def insert_embeddings(
        self,
        embeddings: list[list[float]],
        metadata: list[int],
        **kwargs: Any,
    ) -> tuple[int, Exception | None]:
        """Insert one batch; return ``(count_written, error_or_None)``.

        VectorDBBench supplies integer ids in ``metadata`` and the matching
        ``embeddings`` (lists or numpy arrays). The server wants string ids,
        list-valued vectors, and the id mirrored into the scalar ``id`` field so
        filtered cases (``id >= X``) can match. Newer harness versions pass extra
        ``labels_data`` / ``tenant_labels_data`` kwargs, which we ignore.
        """
        client = self._client_or_raise()
        field = "embedding"
        docs = [
            {
                "id": str(int(idx)),
                "vectors": {field: _to_list(vec)},
                "fields": {"id": int(idx)},
            }
            for idx, vec in zip(metadata, embeddings, strict=True)
        ]
        try:
            resp = client.post(
                f"/collections/{self.collection_name}/docs/insert",
                json={"docs": docs},
            )
            resp.raise_for_status()
        except Exception as exc:
            return 0, exc
        return len(docs), None

    def optimize(self, data_size: int | None = None, **kwargs: Any) -> None:
        """Flush buffered writes, then build/optimize the index.

        ``data_size`` (newer harness) is accepted and ignored: the server sizes
        the index itself.
        """
        client = self._client_or_raise()
        client.post(f"/collections/{self.collection_name}/flush", json={}).raise_for_status()
        client.post(f"/collections/{self.collection_name}/optimize", json={}).raise_for_status()

    # ------------------------------------------------------------------ queries
    def search_embedding(
        self,
        query: list[float],
        k: int = 100,
        filters: dict | None = None,
        **kwargs: Any,
    ) -> list[int]:
        """Run one query; return the hit ids as ``int`` so recall can be scored.

        ``filters`` is VectorDBBench's filtered-search dict ``{"id": <int>}``,
        meaning ``id >= <int>`` -- translated to the server's SQL-like filter
        string. (Newer harness versions pass a ``payload_profile`` keyword
        instead of ``filters``; it carries no value here, so it is ignored.)
        """
        client = self._client_or_raise()
        ef = self._search_param.get("ef")
        params: dict | None = {"ef": ef} if ef is not None else None
        body = {
            "queries": [{"field": "embedding", "vector": _to_list(query), "params": params}],
            "topk": k,
            "filter": _filter_string(filters),
            "include_vector": False,
        }
        resp = client.post(f"/collections/{self.collection_name}/search", json=body)
        resp.raise_for_status()
        results = resp.json()["results"]
        return [int(r["id"]) for r in results]

    # ------------------------------------------------------------------ helpers
    def _client_or_raise(self) -> httpx.Client:
        if self._client is None:
            raise RuntimeError("HTTP client is not open; call within `with db.init():`.")
        return self._client

    def _create_collection(self, client: httpx.Client) -> None:
        """Create the collection from the case's index params (idempotent-ish).

        A scalar ``id`` field (INT64, indexed) is always added so filtered cases
        can express ``id >= X`` against it.
        """
        metric = self._index_param.get("metric", "l2")
        params: dict[str, int] = {}
        if "m" in self._index_param:
            params["m"] = int(self._index_param["m"])
        if "ef_construction" in self._index_param:
            params["ef_construction"] = int(self._index_param["ef_construction"])
        body = {
            "name": self.collection_name,
            "vectors": [
                {
                    "name": "embedding",
                    "dim": self.dim,
                    "dtype": "VECTOR_FP32",
                    "index": "hnsw",
                    "metric": metric,
                    "params": params or None,
                }
            ],
            "fields": [{"name": "id", "dtype": "INT64", "indexed": True}],
        }
        resp = client.post("/collections", json=body)
        resp.raise_for_status()

    def _drop(self, client: httpx.Client) -> None:
        """Delete the collection if it exists; ignore a 404."""
        resp = client.delete(f"/collections/{self.collection_name}")
        if resp.status_code not in (200, 204, 404):
            resp.raise_for_status()


def _to_list(vec: Any) -> list[float]:
    """Coerce a numpy array / sequence to a plain JSON-serializable list."""
    tolist = getattr(vec, "tolist", None)
    return tolist() if callable(tolist) else list(vec)


def _filter_string(filters: dict | None) -> str | None:
    """Translate VectorDBBench's ``{"id": <int>}`` filter to a SQL-like string.

    The harness's filtered cases mean "id >= value"; the server's filter grammar
    uses a single ``=`` and single-quoted strings (integers need no quoting).
    Returns ``None`` for the unfiltered case.
    """
    if not filters:
        return None
    value = filters.get("id")
    if value is None:
        return None
    return f"id >= {int(value)}"
